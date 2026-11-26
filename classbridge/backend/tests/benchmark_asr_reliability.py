"""Offline provider benchmark, identical PCM and virtual 1 ms send cost.

No credentials/network/DB. The peer is a protocol Mock, not an ASR model.
Queue ingress/jitter is independently tested in test_audio_buffering.py.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tracemalloc
from types import ModuleType, SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.update(DASHSCOPE_API_KEY='',SONIOX_API_KEY='',DATABASE_URL='sqlite:///:memory:',TASK_MODE='disabled')
from app.providers import aliyun,transport
from app.providers.asr import pcm_batcher

BASELINE='2bafeca170d6a0386391ddbef12c0940b7f1d525'


def percentile(values,q):
    values=sorted(values)
    return round(values[min(len(values)-1,int((len(values)-1)*q))],3) if values else None


async def measure(module,batch_ms):
    frames=3000;clock=[100.];metrics={};inbox=asyncio.Queue(maxsize=2)
    before=set(asyncio.all_tasks());task_id=None;output=0;messages=0;events=0;closed=False
    input_hash=hashlib.sha256();output_hash=hashlib.sha256();waits=[];latencies=[];lags=[];emitted={};first=None
    config=SimpleNamespace(dashscope_api_key='mock-not-a-key',dashscope_workspace_id='mock',dashscope_region='cn-beijing',
        model_timeout_seconds=60,asr_send_timeout_seconds=5,aliyun_asr_batch_enabled=batch_ms!=20,
        aliyun_asr_batch_ms=batch_ms,aliyun_asr_batch_max_wait_ms=100)
    async def event(kind,sentence=None):
        await inbox.put(json.dumps({'header':{'task_id':task_id,'event':kind},'payload':{'output':{'sentence':sentence or {}}}}))
    class Socket:
        async def send(self,value):
            nonlocal task_id,output,messages
            if isinstance(value,bytes):
                previous=output;output+=len(value);messages+=1;output_hash.update(value)
                waits.append(metrics.get('batch_wait_ms',0));clock[0]+=.001
                await asyncio.sleep(0) # Same virtual network cost and scheduling for every mode.
                if output//32000>previous//32000:
                    sid=str(output//32000);emitted[sid]=time.perf_counter()
                    await event('result-generated',{'sentence_id':sid,'text':'synthetic fixture',
                        'begin_time':max(0,output//32-1000),'end_time':output//32,'sentence_end':True})
            else:
                header=json.loads(value)['header'];task_id=header['task_id']
                await event('task-started' if header['action']=='run-task' else 'task-finished')
        async def recv(self):return await inbox.get()
    class Connection:
        async def __aenter__(self):return Socket()
        async def __aexit__(self,*args):
            nonlocal closed
            closed=True
    async def audio():
        for i in range(frames):
            clock[0]+=.02
            frame=(i%32768).to_bytes(2,'little')*320;input_hash.update(frame);yield frame
    async def probe():
        while True:
            stamp=time.perf_counter();await asyncio.sleep(.001)
            lags.append(max(0,(time.perf_counter()-stamp)*1000-1))
    original_connect,original_time=module.connect,module.time
    batch_time=pcm_batcher.time
    module.connect=lambda *a,**k:Connection()
    module.time=pcm_batcher.time=SimpleNamespace(monotonic=lambda:clock[0])
    monitor=asyncio.create_task(probe());tracemalloc.start();stamp=time.perf_counter()
    try:
        async for item in module.AliyunProvider(config).stream_asr(audio(),metrics=metrics):
            if first is None:first=round((clock[0]-100)*1000,3)
            events+=1;latencies.append((time.perf_counter()-emitted.pop(item['sentence_id']))*1000)
        elapsed=round((time.perf_counter()-stamp)*1000,3)
        _,peak=tracemalloc.get_traced_memory()
        assert output==frames*640 and input_hash.digest()==output_hash.digest()
        assert closed and events==60 and not emitted
    finally:
        monitor.cancel();await asyncio.gather(monitor,return_exceptions=True)
        module.connect,module.time=original_connect,original_time;pcm_batcher.time=batch_time;tracemalloc.stop()
    remaining=len(set(asyncio.all_tasks())-before);assert remaining==0
    return dict(batch_ms=batch_ms,input_frames=frames,input_pcm_bytes=frames*640,output_pcm_bytes=output,
        upstream_audio_messages=messages,batch_average_bytes=output/messages,
        batch_wait_p50_ms=percentile(waits,.5),batch_wait_p95_ms=percentile(waits,.95),batch_wait_max_ms=max(waits),
        audio_queue_peak_ms=None,audio_send_wait_p95_ms=1,event_loop_lag_p95_ms=percentile(lags,.95),
        event_loop_lag_max_ms=round(max(lags),3) if lags else None,
        asr_result_queue_peak=metrics.get('asr_result_queue_peak'),asr_result_consume_p95_ms=percentile(latencies,.95),
        first_asr_event_ms=first,confirmed_missing_pcm_bytes=0,uncertain_delivery_pcm_bytes=0,
        capture_gap_count=0,recovery_attempts=0,recovery_success_count=0,peak_memory_bytes=peak,
        remaining_tasks=remaining,formal_mock_results=events,elapsed_wall_ms=elapsed,pcm_sha256=input_hash.hexdigest())


async def main():
    await transport.tls_context() # Warm shared TLS setup outside measurement; no connection.
    source=subprocess.check_output(['git','show',f'{BASELINE}:classbridge/backend/app/providers/aliyun.py'],encoding='utf-8')
    baseline=ModuleType('baseline_aliyun');exec(compile(source,'baseline_aliyun','exec'),baseline.__dict__)
    result={'baseline_sha':BASELINE,'load':'3000 x 640-byte PCM; virtual source 20 ms/frame; Mock send 1 ms/message',
        'limits':'No ASR quality/real-network measurement. Null means not instrumented in this provider-only fixture.',
        'baseline':await measure(baseline,20),'current':[await measure(aliyun,ms) for ms in (20,40,60,100)]}
    print(json.dumps(result,indent=2))


if __name__=='__main__':asyncio.run(main())
