"""Source isolation with temporary SQLite and mocked ASR/MT only; no cloud calls."""
import asyncio
import time
from unittest.mock import AsyncMock
import pytest
from test_core import factory, client, seed
from app.config import settings
from app.models import Session, SegmentRevision, Translation, Event, ProcessingTask, Outbox, Chunk
from app.providers.aliyun import AliyunProvider, ProviderError
from app.services.events import save_final, save_interrupted, latest_segments, unconfirmed_segments
from app.api.sessions import export_text
from app.services.knowledge import retrieve
from app.ws.live import LiveCapture
from app.workers.tasks import execute_task
import app.ws.live as live


def capture(factory, mode='real'):
    with factory() as db:seed(db,mode=mode)
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode=mode;c.started=time.monotonic()
    return c


def asr(text='오늘은 인공지능을 공부합니다.', final=False, sid='1'):
    return {'sentence_id':sid,'text':text,'start_ms':100,'end_ms':800,'final':final}


async def close_preview(c):
    if c.preview:await c.preview.close()
    for t in c.translation_tasks.values():t.cancel()
    await asyncio.gather(*c.translation_tasks.values(),return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('incremental',[False,True])
async def test_blocked_mt_never_blocks_next_source_or_final(factory,monkeypatch,incremental):
    monkeypatch.setattr(settings,'incremental_translation_enabled',incremental)
    monkeypatch.setattr(settings,'preview_max_wait_seconds',0)
    from app.services.incremental_translation import PreviewBudget
    monkeypatch.setattr('app.services.incremental_translation.preview_budget',PreviewBudget())
    entered=asyncio.Event();release=asyncio.Event()
    async def blocked(*args,**kwargs):
        entered.set();await release.wait();yield 'later'
    monkeypatch.setattr(AliyunProvider,'translate_stream',blocked)
    c=capture(factory)
    try:
        await c.consume(asr())
        await asyncio.wait_for(entered.wait(),1)
        await asyncio.wait_for(c.consume(asr('다음 원문입니다.',sid='2')),1)
        assert c.ws.send_json.call_args.args[0]['text']=='다음 원문입니다.'
        await asyncio.wait_for(c.consume(asr(final=True)),1)
        assert 'stream:1' in c.finalized and not release.is_set()
        with factory() as db:
            assert db.query(SegmentRevision).one().text==asr()['text']
            assert db.query(Translation).count()==0
            assert {t.kind for t in db.query(ProcessingTask)}=={'translate','index_segment'}
    finally:await close_preview(c)


@pytest.mark.asyncio
async def test_commit_failure_does_not_poison_retry_or_claim_success(factory,monkeypatch):
    c=capture(factory);await c.consume(asr('짧은 원문'))
    original=live.save_final
    def rollback(db,*args,**kwargs):
        original(db,*args,**{**kwargs,'commit':False})
        raise RuntimeError('mock commit failure')
    monkeypatch.setattr(live,'save_final',rollback)
    with pytest.raises(ProviderError,match='正式原文保存失败'):await c.consume(asr('짧은 원문',True))
    assert not c.finalized and not c.final_results
    assert c.current_revisions['stream:1']==1 and c.unconfirmed['stream:1']['text']=='짧은 원문'
    with factory() as db:
        assert db.query(SegmentRevision).count()==db.query(Outbox).count()==db.query(Event).count()==0
    monkeypatch.setattr(live,'save_final',original)
    await c.consume(asr('짧은 원문',True));await c.consume(asr('짧은 원문',True))
    with factory() as db:assert db.query(SegmentRevision).count()==1
    assert 'stream:1' in c.finalized and not c.unconfirmed


@pytest.mark.asyncio
async def test_none_result_is_not_false_success_but_verified_idempotence_is(factory,monkeypatch):
    c=capture(factory)
    original=live.save_final
    monkeypatch.setattr(live,'save_final',lambda *a,**k:None)
    with pytest.raises(ProviderError):await c.consume(asr('짧은 원문',True))
    assert not c.finalized and not c.current_revisions
    monkeypatch.setattr(live,'save_final',original)
    with factory() as db:save_final(db,'lesson','stream','stream:1',1,'짧은 원문',100,800)
    await c.consume(asr('짧은 원문',True))
    assert 'stream:1' in c.finalized
    with factory() as db:assert db.query(SegmentRevision).count()==1


@pytest.mark.asyncio
@pytest.mark.parametrize('incremental',[False,True])
@pytest.mark.parametrize('ending',['normal_final','unfinished','network_failure'])
async def test_drain_persists_unfinished_before_stopped_without_formal_evidence(factory,monkeypatch,incremental,ending):
    monkeypatch.setattr(settings,'incremental_translation_enabled',incremental)
    c=capture(factory)
    async def provider(self,audio,**kwargs):
        await kwargs['on_ready']()
        if ending=='network_failure':yield asr('정식 원문',True,sid='saved')
        yield asr('아직 미완성')
        if ending=='normal_final':yield asr('완성된 문장',True)
        if ending=='network_failure':raise ProviderError('network_error','mock disconnected')
    monkeypatch.setattr(AliyunProvider,'stream_asr',provider)
    await c.run()
    with factory() as db:
        events=db.query(Event).order_by(Event.event_seq).all()
        unfinished=[e for e in events if e.type=='transcript.interrupted']
        if ending=='normal_final':
            assert unfinished==[] and len(latest_segments(db,'lesson'))==1
        else:
            assert len(unfinished)==1 and unfinished[0].payload['text']=='아직 미완성'
            stop=next(e for e in events if e.type=='session.state' and e.payload.get('state')=='stopped')
            assert unfinished[0].event_seq<stop.event_seq
            assert all(r.text!='아직 미완성' for r in latest_segments(db,'lesson'))
            assert all(t.payload.get('segment_id') is not None for t in db.query(ProcessingTask).filter_by(kind='index_segment'))
            assert '아직 미완성' not in export_text(db,db.get(Session,'lesson'))
            assert len(unconfirmed_segments(db,'lesson'))==1
        if ending=='unfinished':
            assert db.query(SegmentRevision).count()==db.query(ProcessingTask).count()==db.query(Chunk).count()==0
        if ending=='network_failure':assert latest_segments(db,'lesson')[0].text=='정식 원문'


@pytest.mark.asyncio
async def test_interrupted_snapshot_ownership_replacement_clear_and_rag_exclusion(client,factory):
    with factory() as db:
        seed(db)
        snapshot={'sentence_id':'stream:1','source_revision':2,'text':'UNCONFIRMED EVIDENCE','start_ms':100,'end_ms':800}
        save_interrupted(db,'lesson','stream',snapshot);db.commit()
        assert save_interrupted(db,'lesson','stream',snapshot) is None
        save_interrupted(db,'lesson','stream',{**snapshot,'source_revision':3,'text':'LAST PARTIAL'});db.commit()
        assert await retrieve(db,'alice','LAST PARTIAL','session','lesson',[],'demo')==[]
        assert db.query(SegmentRevision).count()==db.query(ProcessingTask).count()==0
        seed(db,owner='bob',session_id='private',stream_id='private-stream')
        save_interrupted(db,'private','private-stream',{**snapshot,'sentence_id':'private:1'});db.commit()
    detail=client.get('/api/sessions/lesson').json()
    assert detail['segments']==[] and len(detail['unconfirmed_segments'])==1
    assert detail['unconfirmed_segments'][0]['text']=='LAST PARTIAL'
    assert detail['unconfirmed_segments'][0]['source_final'] is False
    assert client.get('/api/sessions/private').status_code==404
    assert client.post('/api/sessions/lesson/summarize').status_code==409
    with factory() as db:save_final(db,'lesson','stream','stream:1',4,'Official final',100,900,translation='正式')
    detail=client.get('/api/sessions/lesson').json()
    assert detail['unconfirmed_segments']==[] and detail['segments'][0]['text']=='Official final'
    assert client.delete('/api/sessions/lesson/segments').status_code==200
    assert client.get('/api/sessions/lesson').json()['unconfirmed_segments']==[]
    with factory() as db:assert db.query(Event).filter_by(session_id='lesson',type='transcript.interrupted').count()==0


@pytest.mark.asyncio
async def test_old_stream_cannot_publish_or_persist_into_replacement(factory):
    c=capture(factory)
    with factory() as db:db.get(Session,'lesson').active_stream_id=None;db.commit()
    await c.consume(asr());await c.consume(asr(final=True))
    assert not c.finalized and not c.unconfirmed and c.ws.send_json.await_count==0
    with factory() as db:assert db.query(SegmentRevision).count()==0


@pytest.mark.asyncio
async def test_mt_failure_is_bound_to_saved_source_and_does_not_rollback_it(factory,monkeypatch):
    c=capture(factory);await c.consume(asr('정식 원문',True))
    async def failure(*a,**k):
        raise ProviderError('timeout','mock MT timeout')
        yield ''
    monkeypatch.setattr(AliyunProvider,'translate_stream',failure)
    with factory() as db:tid=db.query(ProcessingTask).filter_by(kind='translate').one().id
    await execute_task(tid)
    with factory() as db:
        assert latest_segments(db,'lesson')[0].text=='정식 원문'
        e=db.query(Event).filter_by(type='processing.failed').one().payload
        assert e['task_kind']=='translate' and e['sentence_id']=='stream:1' and e['source_revision']==1 and e['stream_id']=='stream'
        assert db.query(Translation).count()==0


@pytest.mark.asyncio
async def test_cleanup_storage_failure_reports_without_fake_stopped(factory,monkeypatch,caplog):
    c=capture(factory)
    async def provider(self,audio,**kwargs):
        await kwargs['on_ready']();yield asr('미완성')
    monkeypatch.setattr(AliyunProvider,'stream_asr',provider)
    def broken(*a,**k):raise RuntimeError('mock storage failure')
    monkeypatch.setattr(live,'save_interrupted',broken)
    await c.run()
    assert 'source_cleanup_failed' in caplog.text
    assert c.ws.send_json.call_args.args[0]['code']=='source_storage_failed'
    assert c.unconfirmed
    with factory() as db:
        assert not any(e.payload.get('state')=='stopped' for e in db.query(Event))
        assert db.query(SegmentRevision).count()==0


@pytest.mark.asyncio
async def test_pending_tracking_bound_and_last_revision_not_longest(factory,monkeypatch):
    monkeypatch.setattr(settings,'incremental_translation_enabled',False)
    c=capture(factory)
    await c.consume(asr('긴 미완성 원문'))
    await c.consume(asr('짧은 원문'))
    assert c.unconfirmed['stream:1']['text']=='짧은 원문'
    for i in range(2,201):await c.consume(asr('미완성',sid=str(i)))
    with pytest.raises(ProviderError,match='保护上限'):await c.consume(asr('미완성',sid='201'))
    assert len(c.unconfirmed)==200


@pytest.mark.asyncio
async def test_evicted_final_identity_still_rejects_late_partial_and_duplicate(factory):
    c=capture(factory);await c.consume(asr('정식 원문',True))
    c.finalized.clear();c.current_revisions.clear();c.last_results.clear();c.final_results.clear()
    await c.consume(asr('늦은 임시'))
    await c.consume(asr('정식 원문',True))
    assert c.ws.send_json.await_count==0
    with factory() as db:assert db.query(SegmentRevision).count()==1
    await c.consume(asr('정식 수정 원문',True))
    with factory() as db:assert [r.source_revision for r in db.query(SegmentRevision).order_by(SegmentRevision.source_revision)]==[1,2]


@pytest.mark.asyncio
@pytest.mark.parametrize('incremental',[False,True])
async def test_user_stop_waits_for_provider_final_before_interrupted_cleanup(factory,monkeypatch,incremental):
    monkeypatch.setattr(settings,'incremental_translation_enabled',incremental)
    c=capture(factory);partial_seen=asyncio.Event()
    async def provider(self,audio,**kwargs):
        await kwargs['on_ready']();yield asr('미완성')
        partial_seen.set()
        async for _ in audio:pass
        yield asr('정식 마무리',True)
    monkeypatch.setattr(AliyunProvider,'stream_asr',provider)
    c.task=asyncio.create_task(c.run())
    await asyncio.wait_for(partial_seen.wait(),1)
    await c.stop()
    with factory() as db:
        assert latest_segments(db,'lesson')[0].text=='정식 마무리'
        assert db.query(Event).filter_by(type='transcript.interrupted').count()==0
        assert db.get(Session,'lesson').status=='stopped'


def test_websocket_replays_interrupted_without_starting_microphone(client,factory):
    with factory() as db:
        seed(db)
        save_interrupted(db,'lesson','stream',{'sentence_id':'stream:1','source_revision':1,'text':'未确认', 'start_ms':0,'end_ms':100});db.commit()
    with client.websocket_connect('/ws/sessions/lesson?after_seq=0',headers={'Origin':'http://localhost:5173'}) as ws:
        assert ws.receive_json()['type']=='session.state'
        replay=ws.receive_json();assert replay['type']=='transcript.interrupted' and replay['event_seq']==1
        assert replay['source_final'] is False
    with client.websocket_connect('/ws/sessions/lesson?after_seq=1',headers={'Origin':'http://localhost:5173'}) as ws:
        assert ws.receive_json()['recovered'] is True
        ws.send_json({'type':'ping'});assert ws.receive_json()['type']=='connection.pong'
