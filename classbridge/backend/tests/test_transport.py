import asyncio
import ssl
import threading
import time

import pytest

from app.providers import transport
from unittest.mock import AsyncMock
from test_core import factory, seed
from app.ws.live import LiveCapture
from app.models import Event


@pytest.mark.asyncio
async def test_slow_certificate_load_is_shared_and_does_not_stall_audio_loop(monkeypatch):
    monkeypatch.setattr(transport, '_contexts', {})
    monkeypatch.delenv('SSL_CERT_FILE', raising=False)
    monkeypatch.delenv('SSL_CERT_DIR', raising=False)
    loop_thread = threading.get_ident()
    calls = []
    context = object()

    def slow_store(**kwargs):
        assert threading.get_ident() != loop_thread
        calls.append(kwargs)
        time.sleep(.12)
        return context

    monkeypatch.setattr(transport.ssl, 'create_default_context', slow_store)
    tasks = [asyncio.create_task(transport.tls_context()) for _ in range(4)]
    audio_ticks = 0
    while not all(task.done() for task in tasks):
        audio_ticks += 1
        await asyncio.sleep(.01)
    assert await asyncio.gather(*tasks) == [context] * 4
    assert len(calls) == 1
    assert audio_ticks >= 5, '20 ms PCM handling must keep running during certificate I/O'
    assert await transport.tls_context() is context
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_tls_verification_and_private_ca_precedence_are_preserved(monkeypatch):
    monkeypatch.setattr(transport, '_contexts', {})
    monkeypatch.delenv('SSL_CERT_FILE', raising=False)
    monkeypatch.delenv('SSL_CERT_DIR', raising=False)
    context = await transport.tls_context()
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    calls = []
    monkeypatch.setattr(transport.ssl, 'create_default_context', lambda **kw: calls.append(kw) or context)
    monkeypatch.setenv('SSL_CERT_FILE', 'private-ca.pem')
    monkeypatch.setenv('SSL_CERT_DIR', 'private-certs')
    await transport.tls_context()
    assert calls == [{'cafile': 'private-ca.pem', 'capath': None}]


def test_asr_glossary_uses_valid_source_words_without_translation_or_foreign_data():
    from app.services.asr_options import asr_vocabulary
    result = asr_vocabulary([
        {'source': 'working memory', 'target': '工作记忆'}, '인지 부하',
        {'term': 'RAG'}, 'working memory', {'source': None},
        '가' * 16, 'one two three four five six seven eight',
    ])
    assert result == {'working memory': 2, '인지 부하': 2, 'RAG': 2}
    assert len(asr_vocabulary([f'term{i}' for i in range(250)])) == 200


def test_glossary_reports_skipped_terms_and_normalizes_korean_without_inventing_words():
    import unicodedata
    from app.services.asr_options import asr_vocabulary_report
    word='작업기억'
    report=asr_vocabulary_report([unicodedata.normalize('NFD',word),word,'가'*16,
        'one two three four five six seven eight',{'source':''}, {'source':'인지부하','target':'认知负荷'}],4)
    assert report['vocabulary']=={'작업기억':4,'인지부하':4}
    assert [item['index'] for item in report['skipped']]==[1,2,3,4]
    assert '重复' in report['skipped'][0]['reason']
    assert '15' in report['skipped'][1]['reason']
    assert '7' in report['skipped'][2]['reason']
    assert asr_vocabulary_report([],4)=={'vocabulary':{},'skipped':[]}


@pytest.mark.asyncio
@pytest.mark.parametrize('delay_ms',[100,300,500,1000,2000])
async def test_pcm_jitter_budget_order_and_full_stop(factory,delay_ms):
    """Hold the first send while exactly delay_ms/20 incoming frames arrive.

    Virtual audio cadence: deterministic queue load, no network/timer randomness.
    """
    with factory() as db:seed(db,mode='real')
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode='real';c.ready=True;c.started=time.monotonic()
    entered=asyncio.Event();release=asyncio.Event();sent=[]
    async def forward():
        async for frame in c.audio_iter():
            entered.set();await release.wait();sent.append(frame)
    c.task=asyncio.create_task(forward())
    frames=[i.to_bytes(2,'little')*320 for i in range(delay_ms//20+1)]
    await c.audio(frames[0]);await entered.wait()
    for frame in frames[1:]:await c.audio(frame)
    assert c.queued_bytes==delay_ms*32 and c.audio_queue_peak<=64000
    if delay_ms==2000:
        failed=asyncio.Event();original=c.fail
        async def fail(*a,**k):await original(*a,**k);failed.set()
        c.fail=fail
        overflow=asyncio.create_task(c.audio(b'\xff\x00'*320))
        await asyncio.wait_for(failed.wait(),2)
        release.set();await overflow
        with factory() as db:
            errors=db.query(Event).filter_by(type='processing.failed').all()
            assert len(errors)==1 and errors[0].payload['code']=='audio_backlog'
    else:release.set();await c.stop()
    await c.stop() # idempotent; no extra close/failure
    assert sent==frames and c.queued_bytes==0
    assert c.received_audio_ms==len(frames)*20
    assert sum(len(f)//2 for f in sent)==len(frames)*320
    assert c.task.done()
    assert c.diagnostics()['queue_frames']==0


@pytest.mark.asyncio
async def test_audio_ingress_never_queries_database(factory,monkeypatch):
    import app.ws.live as live
    c=LiveCapture(AsyncMock(),'lesson','alice');c.mode='real';c.ready=True;c.started=time.monotonic()
    c.task=asyncio.create_task(asyncio.Event().wait())
    def forbidden():raise AssertionError('Audio ingress must not open a database Session')
    monkeypatch.setattr(live,'SessionLocal',forbidden)
    try:
        for i in range(100):await c.audio(i.to_bytes(2,'little')*320)
        assert c.queued_bytes==64000 and c.received_audio_ms==2000
    finally:
        c.task.cancel();await asyncio.gather(c.task,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('user_stopped',[False,True])
async def test_duration_limit_does_not_discard_accepted_tail(factory,monkeypatch,user_stopped):
    from app.config import settings
    with factory() as db:seed(db,mode='real')
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode='real';c.ready=True;c.started=time.monotonic()
    c.task=asyncio.create_task(asyncio.Event().wait())
    frames=[i.to_bytes(2,'little')*320 for i in range(10)]
    try:
        for frame in frames:await c.audio(frame)
        monkeypatch.setattr(settings,'capture_max_seconds',1)
        c.started-=2
        if user_stopped:c.signal_stop()
        assert [frame async for frame in c.audio_iter()]==frames
        assert c.stopping and c.queued_bytes==c.queued_frames==0
        with factory() as db:
            errors=db.query(Event).filter_by(type='processing.failed').all()
            assert len(errors)==(0 if user_stopped else 1)
            if errors:assert errors[0].payload['code']=='application_duration_limit'
    finally:c.task.cancel();await asyncio.gather(c.task,return_exceptions=True)


@pytest.mark.asyncio
async def test_slow_final_commit_keeps_audio_ingress_and_atomic_source(factory,monkeypatch):
    import app.ws.live as live
    from app.models import SegmentRevision,Outbox
    with factory() as db:seed(db,mode='real')
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode='real';c.ready=True;c.started=time.monotonic()
    c.task=asyncio.create_task(asyncio.Event().wait())
    entered=threading.Event();release=threading.Event();original=live.save_final
    def delayed(*a,**k):
        entered.set();assert release.wait(3);return original(*a,**k)
    monkeypatch.setattr(live,'save_final',delayed)
    pending=asyncio.create_task(c.consume({'sentence_id':'1','text':'Official source','start_ms':0,'end_ms':20,'final':True}))
    try:
        assert await asyncio.to_thread(entered.wait,2)
        for i in range(20):await c.audio(i.to_bytes(2,'little')*320)
        assert c.queued_bytes==12800 and not pending.done() and not c.finalized
        release.set();await pending
        with factory() as db:
            assert db.query(SegmentRevision).count()==1 and db.query(Outbox).count()==2
    finally:
        release.set();await asyncio.gather(pending,return_exceptions=True)
        c.task.cancel();await asyncio.gather(c.task,return_exceptions=True)


@pytest.mark.asyncio
async def test_archive_batches_do_not_block_ingress_and_cancellation_joins_write(factory):
    c=LiveCapture(AsyncMock(),'lesson','alice');c.mode='real';c.ready=True;c.started=time.monotonic()
    c.task=asyncio.create_task(asyncio.Event().wait())
    entered=threading.Event();release=threading.Event();written=[]
    class Disk:
        def writeframesraw(self,data):entered.set();assert release.wait(3);written.append(data)
    c.audio_file=Disk()
    frames=[i.to_bytes(2,'little')*320 for i in range(10)]
    for frame in frames[:5]:await c.audio(frame)
    writer=asyncio.create_task(c.flush_archive())
    try:
        assert await asyncio.to_thread(entered.wait,2)
        for frame in frames[5:]:await c.audio(frame)
        assert c.archive_bytes==6400 and not writer.done()
        writer.cancel();await asyncio.sleep(0)
        assert not writer.done(), 'Must not close WAV while its thread is writing'
        release.set();await asyncio.gather(writer,return_exceptions=True)
        await c.flush_archive()
        assert b''.join(written)==b''.join(frames) and c.audio_bytes==6400 and c.archive_bytes==0
    finally:
        release.set();c.task.cancel();await asyncio.gather(c.task,writer,return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_archive_reports_write_failure(factory):
    from app.providers.aliyun import ProviderError
    c=LiveCapture(AsyncMock(),'lesson','alice')
    entered=threading.Event();release=threading.Event()
    class Disk:
        def writeframesraw(self,data):
            entered.set();assert release.wait(3);raise OSError('mock disk full')
    c.audio_file=Disk();c.archive_queue.append(bytes(640));c.archive_bytes=640
    writer=asyncio.create_task(c.flush_archive())
    try:
        assert await asyncio.to_thread(entered.wait,2)
        writer.cancel();await asyncio.sleep(0);release.set()
        with pytest.raises(ProviderError) as error:await writer
        assert error.value.code=='audio_storage_failed' and c.audio_bytes==0
    finally:release.set();await asyncio.gather(writer,return_exceptions=True)


@pytest.mark.asyncio
async def test_slow_commit_serializes_failure_event_without_blocking_loop(factory,monkeypatch):
    import app.ws.live as live
    with factory() as db:seed(db,mode='real')
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode='real';c.started=time.monotonic()
    entered=threading.Event();release=threading.Event();original=live.save_final
    def delayed(*a,**k):
        entered.set();assert release.wait(3);return original(*a,**k)
    monkeypatch.setattr(live,'save_final',delayed)
    saving=asyncio.create_task(c.consume({'sentence_id':'1','text':'source','start_ms':0,'end_ms':20,'final':True}))
    failing=None
    try:
        assert await asyncio.to_thread(entered.wait,2)
        failing=asyncio.create_task(c.fail('first_error','mock failure'))
        await asyncio.sleep(0)
        assert not failing.done()
        release.set();await asyncio.gather(saving,failing)
        await c.fail('second_error','must not replace first')
        with factory() as db:
            events=db.query(Event).order_by(Event.event_seq).all()
            assert [e.type for e in events]==['transcript.final','processing.failed']
            assert [e.event_seq for e in events]==[1,2]
            assert events[-1].payload['code']=='first_error'
    finally:
        release.set();await asyncio.gather(saving,*([failing] if failing else []),return_exceptions=True)
