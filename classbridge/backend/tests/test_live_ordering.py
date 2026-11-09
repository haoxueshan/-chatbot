import time
import asyncio
from unittest.mock import AsyncMock

import pytest

from test_core import factory, seed
from app.config import settings
from app.models import Event, Outbox, ProcessingTask, SegmentRevision
from app.ws.live import LiveCapture


@pytest.mark.asyncio
@pytest.mark.parametrize('incremental',[False,True])
@pytest.mark.parametrize('language',['zh-CN','en','ko','ja','ar'])
@pytest.mark.parametrize('ending',['blocked','complete','failed'])
async def test_timestamp_only_partials_keep_one_mt_request(factory,monkeypatch,incremental,language,ending):
    from types import SimpleNamespace
    import app.ws.live as live
    from app.providers.aliyun import AliyunProvider
    from app.services.incremental_translation import PreviewBudget
    with factory() as db:
        row=seed(db,mode='real');row.target_language=language;db.commit()
    monkeypatch.setattr(settings,'incremental_translation_enabled',incremental)
    monkeypatch.setattr(settings,'preview_max_wait_seconds',0)
    monkeypatch.setattr('app.services.incremental_translation.preview_budget',PreviewBudget())
    clock=[100.];calls=[];cancelled=[]
    monkeypatch.setattr(live,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    async def direct(fn,*args):return fn(*args)
    monkeypatch.setattr(live,'blocking_call',direct)
    async def mt(self,text,**kwargs):
        from app.services.translation_languages import target_name
        assert kwargs['target_lang']==target_name(language)
        calls.append(text)
        try:
            yield '今天学习'
            if ending=='complete':yield '完整';return
            if ending=='failed':raise RuntimeError('mock MT failure')
            await asyncio.Event().wait()
        except asyncio.CancelledError:cancelled.append(text);raise
    monkeypatch.setattr(AliyunProvider,'translate_stream',mt)
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode='real';c.started=100
    if incremental:c.ensure_preview().clock=lambda:clock[0]
    text='We study artificial intelligence today' if language=='ko' else '오늘은 인공지능을 공부합니다'
    try:
        for i in range(20):
            clock[0]=100+i*1.3
            await c.consume({'sentence_id':'1','text':text,'start_ms':0,'end_ms':1200+100*i,'final':False})
            for _ in range(4):await asyncio.sleep(0)
        print({'incremental':incremental,'requests':len(calls),'cancelled':len(cancelled)})
        assert len(calls)==1 and cancelled==[]
        assert len([call for call in c.ws.send_json.call_args_list if call.args[0]['type']=='translation.partial'])<=2
        assert c.unconfirmed['stream:1']['end_ms']==3100
        final={'sentence_id':'1','text':text,'start_ms':0,'end_ms':3200,'final':True}
        await c.consume(final);await c.consume(final)
        with factory() as db:
            row=db.query(SegmentRevision).one()
            assert row.end_ms==3200 and row.text==text
            assert db.query(ProcessingTask).filter_by(kind='translate').count()==1
    finally:
        if c.preview:await c.preview.close()
        for task in c.translation_tasks.values():task.cancel()
        await asyncio.gather(*c.translation_tasks.values(),return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('incremental',[False,True])
async def test_korean_growth_produces_bounded_preview_and_complete_formal_translation(factory,monkeypatch,incremental):
    from types import SimpleNamespace
    import app.ws.live as live
    from app.providers.aliyun import AliyunProvider
    from app.models import Translation,Session
    from app.services.events import serialize_segment
    from app.services.incremental_translation import PreviewBudget
    from app.workers.tasks import execute_task
    with factory() as db:seed(db,mode='real')
    monkeypatch.setattr(settings,'incremental_translation_enabled',incremental)
    monkeypatch.setattr('app.services.incremental_translation.preview_budget',PreviewBudget())
    clock=[100.];calls=[]
    monkeypatch.setattr(live,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    async def direct(fn,*args):return fn(*args)
    monkeypatch.setattr(live,'blocking_call',direct)
    async def mt(self,text,**kwargs):calls.append(text);yield '译：';yield text
    monkeypatch.setattr(AliyunProvider,'translate_stream',mt)
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode='real';c.started=100
    if incremental:c.ensure_preview().clock=lambda:clock[0]
    try:
        texts=['오늘은','오늘은 인공지능','오늘은 인공지능을','오늘은 인공지능을 공부합니다']
        for i,text in enumerate(texts):
            clock[0]=100+i*.5
            await c.consume({'sentence_id':'1','text':text,'start_ms':0,'end_ms':i*500,'final':False})
            for _ in range(8):await asyncio.sleep(0)
        clock[0]=104
        if c.preview:c.preview.tick()
        else:c.tick_legacy()
        for _ in range(8):await asyncio.sleep(0)
        assert 1<=len(calls)<=2
        final={'sentence_id':'1','text':texts[-1],'start_ms':0,'end_ms':2000,'final':True}
        await c.consume(final);await c.consume(final)
        with factory() as db:tid=db.query(ProcessingTask).filter_by(kind='translate').one().id
        await execute_task(tid)
        with factory() as db:
            assert db.query(Translation).one().text=='译：'+texts[-1]
            snapshot=serialize_segment(db,db.query(SegmentRevision).one())
            assert snapshot['source_final'] and snapshot['translation_final']
            assert db.query(Event).filter_by(type='translation.final').count()==1
        assert len(calls)<=3
    finally:
        if c.preview:await c.preview.close()
        for task in c.translation_tasks.values():task.cancel()
        await asyncio.gather(*c.translation_tasks.values(),return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('incremental',[False,True])
async def test_korean_rewrite_rejects_tokens_returned_after_cancellation(factory,monkeypatch,incremental):
    from types import SimpleNamespace
    import app.ws.live as live
    from app.providers.aliyun import AliyunProvider
    from app.services.incremental_translation import PreviewBudget
    with factory() as db:seed(db,mode='real')
    monkeypatch.setattr(settings,'incremental_translation_enabled',incremental)
    monkeypatch.setattr(settings,'preview_max_wait_seconds',0)
    monkeypatch.setattr('app.services.incremental_translation.preview_budget',PreviewBudget())
    clock=[100.];calls=[]
    monkeypatch.setattr(live,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    async def direct(fn,*args):return fn(*args)
    monkeypatch.setattr(live,'blocking_call',direct)
    async def mt(self,text,**kwargs):
        calls.append(text)
        if text.startswith('오늘'):
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:yield '迟到旧译文'
        else:yield '昨天学习了人工智能。'
    monkeypatch.setattr(AliyunProvider,'translate_stream',mt)
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode='real';c.started=100
    if incremental:c.ensure_preview().clock=lambda:clock[0]
    try:
        await c.consume({'sentence_id':'1','text':'오늘은 인공지능을 공부합니다.','end_ms':1000})
        for _ in range(8):await asyncio.sleep(0)
        clock[0]=103
        await c.consume({'sentence_id':'1','text':'어제는 인공지능을 공부했습니다.','end_ms':2000})
        for _ in range(8):await asyncio.sleep(0)
        if c.preview:c.preview.tick()
        else:c.tick_legacy()
        for _ in range(8):await asyncio.sleep(0)
        events=[call.args[0] for call in c.ws.send_json.call_args_list if call.args[0]['type']=='translation.partial']
        assert len(calls)==2 and events
        assert all(e['translation']=='昨天学习了人工智能。' and e['source_revision']==2 for e in events)
    finally:
        if c.preview:await c.preview.close()
        for task in c.translation_tasks.values():task.cancel()
        await asyncio.gather(*c.translation_tasks.values(),return_exceptions=True)


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
