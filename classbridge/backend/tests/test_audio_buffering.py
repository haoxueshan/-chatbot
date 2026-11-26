import asyncio
import time
from unittest.mock import AsyncMock
import pytest
from app.config import Settings, settings
from app.ws.live import LiveCapture
from app.services.audio_diagnostics import captures,process_buffer_bytes,LoopHealth
from app.models import Event
from test_core import factory,seed,client


@pytest.mark.parametrize('values',[
    {'audio_queue_warning_ms':4000}, {'browser_audio_buffer_max_ms':100},
    {'audio_process_max_buffer_bytes':65536}, {'asr_recovery_enabled':True},
    {'asr_recovery_auto_replay_uncertain':True}, {'aliyun_asr_batch_ms':25},
    {'processing_backlog_hard_limit':100}, {'asr_send_timeout_seconds':0},
])
def test_invalid_or_unverified_configuration_rejected(values):
    with pytest.raises(ValueError):Settings(_env_file=None,**values)


def test_public_runtime_allowlist(client):
    runtime=client.get('/api/settings').json()['audio_runtime']
    assert runtime==settings.audio_runtime() and runtime['server_queue_max_ms']==8000
    assert not any(x in str(runtime).lower() for x in ['key','secret','url','path'])


@pytest.mark.asyncio
@pytest.mark.parametrize('delay',[100,500,1000,2000,3000,5000,7980])
async def test_configured_jitter_preserves_every_admitted_sample(factory,delay):
    with factory() as db:seed(db,mode='real')
    c=LiveCapture(AsyncMock(),'lesson','alice');c.mode='real';c.ready=True;c.stream_id='stream';c.started=time.monotonic()
    block=asyncio.Event();entered=asyncio.Event();sent=[]
    async def sender():
        async for data in c.audio_iter():
            entered.set();await block.wait();sent.append(data)
            c.asr_metrics['sent_audio_ms']=c.asr_metrics.get('sent_audio_ms',0)+len(data)/32
    c.task=asyncio.create_task(sender())
    frames=[i.to_bytes(2,'little')*320 for i in range(delay//20+1)]
    try:
        await c.audio(frames[0]);await entered.wait()
        for frame in frames[1:]:await c.audio(frame)
        assert c.outstanding_bytes()==len(frames)*640 and not c.stopping
        assert c.diagnostics()['buffer_state']==('OVERFLOW' if delay==7980 else 'DEGRADED' if delay>=3000 else 'BUFFERING' if delay>=1500 else 'NORMAL')
        block.set();await c.stop()
        assert sent==frames and c.outstanding_bytes()==0
        with factory() as db:assert db.query(Event).filter_by(type='capture.gap').count()==0
    finally:
        c.task.cancel();await asyncio.gather(c.task,return_exceptions=True);captures.discard(c)


@pytest.mark.asyncio
@pytest.mark.parametrize('capacity',['audio','archive','archive_nodes','process'])
async def test_overflow_closes_admission_before_slow_diagnostics(factory,monkeypatch,capacity):
    with factory() as db:seed(db,mode='real')
    c=LiveCapture(AsyncMock(),'lesson','alice');c.mode='real';c.ready=True;c.stream_id='stream';c.started=time.monotonic()
    c.task=asyncio.create_task(asyncio.Event().wait())
    if capacity=='audio':c.received_audio_ms=8000 # Includes unsent batches/in-flight, not just queue nodes.
    if capacity=='archive':c.audio_file=object();c.archive_bytes=8000*32
    if capacity=='archive_nodes':c.audio_file=object();c.archive_queue.extend([bytes(2)]*4096);c.archive_bytes=8192
    if capacity=='process':monkeypatch.setattr(settings,'audio_process_max_buffer_bytes',1000)
    entered=asyncio.Event();release=asyncio.Event()
    async def fail(*args):entered.set();await release.wait()
    c.fail=fail;c.stop=AsyncMock();c.gap=AsyncMock()
    operation=asyncio.create_task(c.audio(bytes(640)))
    try:
        await entered.wait();assert c.stopping and c.rejected_pcm_bytes==640
        await c.audio(bytes(640));assert c.rejected_pcm_bytes==1280 and c.queued_bytes==0
        release.set();await operation
    finally:
        release.set();c.task.cancel();await asyncio.gather(operation,c.task,return_exceptions=True);captures.discard(c)


def test_loop_health_is_bounded():
    health=LoopHealth()
    for i in range(1000):health.record(i)
    assert len(health.samples)==120 and health.snapshot()['event_loop_lag_peak_ms']==999


def test_final_wav_publication_streams_without_loading_entire_file(tmp_path,monkeypatch):
    from pathlib import Path
    from app.services.storage import LocalStorage,S3Storage,OSSStorage
    from types import SimpleNamespace
    source=tmp_path/'recording.wav';data=bytes(range(256))*4096;source.write_bytes(data)
    original=Path.read_bytes
    def guarded(path):
        assert path!=source,'Do not materialize the whole WAV in memory'
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',guarded)
    local=LocalStorage(tmp_path/'store');local.put_file('audio/test.wav',source)
    assert local.read('audio/test.wav')==data and source.exists()
    readers=[]
    def put(reader):
        assert hasattr(reader,'read') and not isinstance(reader,bytes)
        assert reader.read(256)==data[:256];readers.append(reader)
    s3=object.__new__(S3Storage);s3.bucket='mock';s3.client=SimpleNamespace(put_object=lambda **kw:put(kw['Body']))
    oss=object.__new__(OSSStorage);oss.bucket=SimpleNamespace(put_object=lambda key,reader:put(reader))
    for storage in (s3,oss):storage.put_file('audio/test.wav',source)
    assert all(reader.closed for reader in readers)
    with pytest.raises(ValueError):local.put_file('../escape',source)
