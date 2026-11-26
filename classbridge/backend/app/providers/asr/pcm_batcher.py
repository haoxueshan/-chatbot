"""Aliyun-only PCM framing. One persistent read; deadline flush never cancels it."""
import asyncio
import time
from app.providers.transport import PCM_BYTES_PER_MS


async def pcm_batch_stream(audio, target_ms, max_wait_ms, metrics):
    if target_ms not in (20,40,60,80,100,200) or not 1<=max_wait_ms<=200:
        raise ValueError('Invalid PCM batch duration')
    target=target_ms*PCM_BYTES_PER_MS
    iterator=aiter(audio);pending=None;buffer=bytearray();since=None;ended=False
    metrics['batch_pending_pcm_bytes']=0
    try:
        while True:
            if buffer and (len(buffer)>=target or ended or time.monotonic()-since>=max_wait_ms/1000):
                size=min(target,len(buffer));chunk=bytes(buffer[:size]);del buffer[:size]
                metrics['batch_pending_pcm_bytes']=len(buffer)
                metrics['batch_wait_ms']=round((time.monotonic()-since)*1000,3)
                if not buffer:since=None
                yield chunk
                continue
            if ended:break
            if pending is None:pending=asyncio.create_task(anext(iterator))
            wait=None if since is None else max(0,max_wait_ms/1000-(time.monotonic()-since))
            done,_=await asyncio.wait((pending,),timeout=wait)
            if not done:continue  # Keep the SAME anext task alive across a timed flush.
            try:frame=pending.result()
            except StopAsyncIteration:ended=True;pending=None;continue
            pending=None
            if not frame or len(frame)%2 or len(frame)>32000:
                raise ValueError('PCM must contain 1..16000 int16 samples')
            if since is None:since=time.monotonic()
            buffer.extend(frame);metrics['batch_pending_pcm_bytes']=len(buffer)
    finally:
        if pending is not None:
            pending.cancel();await asyncio.gather(pending,return_exceptions=True)
        if hasattr(iterator,'aclose'):await iterator.aclose()
        metrics['batch_unsent_pcm_bytes']=len(buffer)
        buffer.clear();metrics['batch_pending_pcm_bytes']=0
