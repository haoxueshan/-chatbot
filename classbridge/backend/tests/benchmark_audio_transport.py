"""Mock-only before/after ingress benchmark. Run from backend; no API or real DB.

Each backlog query costs 50 ms; 100 ordered frames at requested 20 ms cadence.
The baseline is loaded from the reviewed Git SHA, never from a remote URL.
"""
import asyncio
import json
import os
import subprocess
import time
import types
from pathlib import Path
from unittest.mock import AsyncMock
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['DASHSCOPE_API_KEY']=''
from app.ws import live

BASELINE='6e0c638fd663f9f96ef2d335966a05f4612b0783'


class MockDatabase:
    calls=0
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def query(self,*args):return self
    def filter(self,*args):return self
    def count(self):MockDatabase.calls+=1;time.sleep(.05);return 0


async def measure(module):
    module.SessionLocal=MockDatabase
    MockDatabase.calls=0
    c=module.LiveCapture(AsyncMock(),'benchmark','mock-user')
    c.mode='real';c.ready=True;c.started=time.monotonic()
    frames=[i.to_bytes(2,'little')*320 for i in range(100)]
    sent=[];waits=[];lag=[];enqueue=[];peak=0;gaps=[]
    put=c.queue.put_nowait
    def tracked_put(frame):
        nonlocal peak
        if frame is not None:peak=max(peak,(c.queued_bytes+len(frame))/32)
        put(frame)
    c.queue.put_nowait=tracked_put
    async def gap(*args):gaps.append(args)
    c.gap=gap
    async def sender():
        async for frame in c.audio_iter():
            at=time.perf_counter();await asyncio.sleep(0)
            waits.append((time.perf_counter()-at)*1000);sent.append(frame)
    async def ticker():
        while True:
            at=time.perf_counter();await asyncio.sleep(.001)
            lag.append(max(0,(time.perf_counter()-at)*1000-1))
    c.task=asyncio.create_task(sender());probe=asyncio.create_task(ticker())
    await asyncio.sleep(0)
    started=time.perf_counter()
    try:
        for frame in frames:
            at=time.perf_counter();await c.audio(frame)
            enqueue.append((time.perf_counter()-at)*1000)
            await asyncio.sleep(.02)
        c.stopping=True;c.queue.put_nowait(None)
        await c.task
        assert sent==frames and c.queued_bytes==0
        return dict(frames=len(sent),queue_peak_ms=peak,ingress_db_queries=MockDatabase.calls,enqueue_max_ms=round(max(enqueue),3),
            send_wait_max_ms=round(max(waits),3),event_loop_lag_max_ms=round(max(lag),3),
            total_ms=round((time.perf_counter()-started)*1000,3),gaps=len(gaps))
    finally:
        probe.cancel();c.task.cancel()
        await asyncio.gather(probe,c.task,return_exceptions=True)


async def main():
    source=subprocess.check_output(['git','show',f'{BASELINE}:classbridge/backend/app/ws/live.py'],encoding='utf-8')
    baseline=types.ModuleType('baseline_audio_live');exec(compile(source,'baseline_audio_live','exec'),baseline.__dict__)
    print(json.dumps({'baseline_sha':BASELINE,'load':'100 x 640 bytes, 20 ms cadence; Mock backlog query 50 ms',
        'baseline':await measure(baseline),'current':await measure(live)},indent=2))


if __name__=='__main__':asyncio.run(main())
