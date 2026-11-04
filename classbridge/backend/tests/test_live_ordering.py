import time
import asyncio
from unittest.mock import AsyncMock

import pytest

from test_core import factory, seed
from app.config import settings
from app.models import Event, Outbox, ProcessingTask, SegmentRevision
from app.ws.live import LiveCapture


@pytest.mark.asyncio
async def test_blocked_preview_does_not_block_final_and_failure_drains(factory,monkeypatch):
    from app.providers.aliyun import AliyunProvider
    with factory() as db:seed(db,mode='real')
    partial_sent=asyncio.Event();release=asyncio.Event();final_saved=asyncio.Event()
    class Socket:
        async def send_json(self,payload):
            partial_sent.set();await release.wait();raise RuntimeError('mock browser disconnected')
    c=LiveCapture(Socket(),'lesson','alice');c.stream_id='stream';c.mode='real'
    async def provider(self,audio,**kwargs):
        await kwargs['on_ready']()
        yield {'sentence_id':'1','text':'partial','start_ms':0,'end_ms':100,'final':False}
        await partial_sent.wait()
        yield {'sentence_id':'1','text':'official','start_ms':0,'end_ms':200,'final':True}
        final_saved.set()
        async for _ in audio:pass
        # Final received during graceful failure drain must also persist.
        yield {'sentence_id':'2','text':'drained final','start_ms':200,'end_ms':300,'final':True}
    monkeypatch.setattr(AliyunProvider,'stream_asr',provider)
    c.task=asyncio.create_task(c.run())
    await asyncio.wait_for(final_saved.wait(),2)
    with factory() as db:assert db.query(SegmentRevision).one().text=='official'
    assert not c.task.done()
    release.set();await asyncio.wait_for(c.task,3)
    with factory() as db:
        assert db.query(SegmentRevision).count()==2
        errors=db.query(Event).filter_by(type='processing.failed').all()
        assert len(errors)==1 and errors[0].payload['code']=='subtitle_delivery_failed'
    assert not c.delivery_pending and not c.translation_tasks and c.delivery is None


@pytest.mark.asyncio
async def test_final_is_not_demoted_by_late_partial_or_duplicated(factory):
    with factory() as db:
        seed(db, mode='real')
    capture = LiveCapture(AsyncMock(), 'lesson', 'alice')
    capture.stream_id = 'stream'
    capture.mode = 'real'
    capture.started = time.monotonic()
    event = {'sentence_id': '1', 'text': '작업기억', 'start_ms': 0, 'end_ms': 800, 'final': False}
    await capture.consume(event)
    await capture.consume({**event, 'final': True})
    sent = capture.ws.send_json.await_count
    revision = capture.current_revisions['stream:1']
    await capture.consume({**event, 'text': '작업'})
    await capture.consume({**event, 'final': True})
    assert capture.ws.send_json.await_count == sent, 'A finalized sentence must ignore late provisional text'
    assert capture.current_revisions['stream:1'] == revision
    with factory() as db:
        assert db.query(SegmentRevision).count() == 1
        assert db.query(Event).filter_by(type='transcript.final').count() == 1
        assert db.query(ProcessingTask).count() == db.query(Outbox).count() == 2
    # An actual revised final is retained as a separate stable source version.
    await capture.consume({**event, 'text': '작업기억입니다.', 'final': True})
    await capture.consume({**event, 'final': True})  # Older duplicate after the revised final.
    with factory() as db:
        assert db.query(SegmentRevision).count() == 2
        assert db.query(SegmentRevision).order_by(SegmentRevision.source_revision.desc()).first().text == '작업기억입니다.'


@pytest.mark.asyncio
async def test_empty_and_repeated_hypotheses_do_not_invalidate_revision(factory):
    with factory() as db:seed(db,mode='real')
    capture = LiveCapture(AsyncMock(), 'lesson', 'alice')
    capture.stream_id = 'stream'
    capture.started = time.monotonic()
    event = {'sentence_id': '1', 'text': '작업기억', 'start_ms': 0, 'end_ms': None, 'final': False}
    await capture.consume({**event, 'text': ' '})
    assert capture.current_revisions == {}
    await capture.consume(event)
    await capture.consume(event)
    assert capture.current_revisions['stream:1'] == 1
    assert capture.ws.send_json.await_count == 1


@pytest.mark.asyncio
async def test_capture_control_events_bind_to_start_request(factory, monkeypatch):
    from app.providers.aliyun import AliyunProvider
    with factory() as db:
        seed(db, mode='real')
    socket = AsyncMock()
    capture = LiveCapture(socket, 'lesson', 'alice')
    await capture.start('rejected-request')
    rejected = socket.send_json.call_args.args[0]
    assert rejected['code'] == 'missing_api_key'
    assert rejected['request_id'] == 'rejected-request'
    assert capture.task is None

    monkeypatch.setattr(settings, 'dashscope_api_key', 'mock-provider-only')
    async def provider(self, audio, **kwargs):
        await kwargs['on_ready']()
        async for frame in audio:
            pass
        if False:
            yield {}
    monkeypatch.setattr(AliyunProvider, 'stream_asr', provider)
    await capture.start('current-request')
    await capture.fail('test_failure', 'Injected failure')
    await capture.stop()
    with factory() as db:
        controls = [e.payload for e in db.query(Event).all() if e.type in ('session.state', 'processing.failed')]
        assert {e.get('state') for e in controls if e['type'] == 'session.state'} == {'preparing', 'recording', 'processing', 'stopped'}
        assert all(e['request_id'] == 'current-request' for e in controls)
        assert all(e['stream_id'] == capture.stream_id for e in controls)
