import asyncio
import pytest

from app.providers.asr.pcm_batcher import pcm_batch_stream


@pytest.mark.asyncio
@pytest.mark.parametrize('ms,count', [(20,100),(40,50),(60,34),(80,25),(100,20),(200,10)])
async def test_batches_preserve_samples_and_tail(ms,count):
    frames=[i.to_bytes(2,'little')*320 for i in range(100)]
    async def source():
        for frame in frames:yield frame
    metrics={}
    result=[x async for x in pcm_batch_stream(source(),ms,100,metrics)]
    assert len(result)==count
    assert b''.join(result)==b''.join(frames)
    assert all(0<len(x)<=ms*32 and len(x)%2==0 for x in result)
    assert metrics['batch_pending_pcm_bytes']==0


@pytest.mark.asyncio
async def test_timeout_flush_keeps_one_read_alive_and_closes_it():
    release=asyncio.Event();closed=[];reads=0
    async def source():
        nonlocal reads
        try:
            reads+=1;yield b'\x01\x00'*10
            reads+=1;await release.wait();yield b'\x02\x00'*3
        finally:closed.append(True)
    stream=pcm_batch_stream(source(),100,10,{})
    assert await anext(stream)==b'\x01\x00'*10
    assert reads==2 and not closed
    release.set()
    assert await anext(stream)==b'\x02\x00'*3
    with pytest.raises(StopAsyncIteration):await anext(stream)
    assert closed==[True]


@pytest.mark.asyncio
@pytest.mark.parametrize('frame',[b'',b'x',b'x'*32002])
async def test_invalid_pcm_is_explicit(frame):
    async def source():yield frame
    with pytest.raises(ValueError):
        _=[x async for x in pcm_batch_stream(source(),100,100,{})]


@pytest.mark.asyncio
async def test_arbitrary_even_frames_and_cancel_release_reader():
    frames=[b'\x01\x00',b'\x02\x00'*15999,b'\x03\x00'*17]
    async def source():
        for frame in frames:yield frame
    assert b''.join([x async for x in pcm_batch_stream(source(),60,100,{})])==b''.join(frames)
    before=set(asyncio.all_tasks());closed=[]
    async def blocked():
        try:
            yield bytes(20)
            await asyncio.Event().wait()
        finally:closed.append(True)
    metrics={};stream=pcm_batch_stream(blocked(),100,10,metrics)
    assert await anext(stream)==bytes(20)
    await stream.aclose()
    assert closed==[True] and set(asyncio.all_tasks())==before


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled,messages',[(False,100),(True,20)])
async def test_aliyun_batches_then_finishes_without_changing_protocol(monkeypatch,enabled,messages):
    import json
    from types import SimpleNamespace
    import app.providers.aliyun as module
    inbox=asyncio.Queue();sent=[];task=None;closed=[]
    class Socket:
        async def send(self,value):
            nonlocal task
            if isinstance(value,bytes):sent.append(value);return
            header=json.loads(value)['header'];task=header['task_id']
            kind='task-started' if header['action']=='run-task' else 'task-finished'
            await inbox.put(json.dumps({'header':{'task_id':task,'event':kind}}))
        async def recv(self):return await inbox.get()
    class Connection:
        async def __aenter__(self):return Socket()
        async def __aexit__(self,*args):closed.append(True)
    monkeypatch.setattr(module,'connect',lambda *a,**k:Connection())
    config=SimpleNamespace(dashscope_api_key='mock-only',dashscope_region='cn-beijing',dashscope_workspace_id='mock-space',model_timeout_seconds=1,
        aliyun_asr_batch_enabled=enabled,aliyun_asr_batch_ms=100,aliyun_asr_batch_max_wait_ms=100)
    frames=[i.to_bytes(2,'little')*320 for i in range(100)]
    async def source():
        for frame in frames:yield frame
    metrics={}
    assert [e async for e in module.AliyunProvider(config).stream_asr(source(),metrics=metrics)]==[]
    assert len(sent)==messages and b''.join(sent)==b''.join(frames)
    assert metrics['upstream_sent_pcm_bytes']==64000 and metrics['upstream_inflight_pcm_bytes']==0
    assert closed==[True]
