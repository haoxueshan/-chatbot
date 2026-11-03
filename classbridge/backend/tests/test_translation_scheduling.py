import asyncio
import contextlib
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.config import settings
from app.models import ProcessingTask,Outbox,SegmentRevision,Translation,Event,User,now
from app.services.events import save_final,enqueue
from app.services.incremental_translation import reuse_candidate,validated_reuse,translation_spec,spec_digest
from app.services import translation_dispatch
from app.workers import tasks
from test_core import factory,seed


def prepare(factory,candidate=None):
    with factory() as db:
        seed(db,mode='real')
        save_final(db,'lesson','stream','stream:1',2,'Hello world.',0,1000,preview_candidate=candidate)
        row=db.query(SegmentRevision).one()
        task=db.query(ProcessingTask).filter_by(kind='translate').one()
        return task.id,row.id


def candidate(text='Hello world.'):
    record={'text':text,'translation':'你好世界。','spec_digest':spec_digest(translation_spec(settings,[])),
        'stream_id':'stream','sentence_id':'stream:1','completed_at':100,'complete':True}
    return reuse_candidate(SimpleNamespace(completed=record),text,2,settings,stamp=101)


@pytest.mark.asyncio
async def test_safe_reuse_is_durable_formal_idempotent_and_not_paid(factory,monkeypatch):
    monkeypatch.setattr(settings,'incremental_translation_enabled',True)
    tid,sid=prepare(factory,candidate())
    def forbidden(*args,**kwargs):raise AssertionError('no paid call for exact reuse')
    monkeypatch.setattr('app.providers.aliyun.AliyunProvider.translate_stream',forbidden)
    await tasks.execute_task(tid);await tasks.execute_task(tid)
    with factory() as db:
        assert db.query(Translation).count()==1
        event=db.query(Event).filter_by(type='translation.final').one().payload
        assert event['source_revision']==2 and event['translation_revision']==1
        assert event['latency']['translation_reused'] is True
        task=db.get(ProcessingTask,tid)
        assert task.status=='completed' and task.attempts==1 and 'preview_candidate' not in task.payload
        # Crash after translation commit but before task completion: no repeated paid call.
        task.status='retry';db.commit()
    await tasks.execute_task(tid)
    with factory() as db:assert db.get(ProcessingTask,tid).result['skipped']=='translation_already_saved'


@pytest.mark.parametrize('field,value',[
    ('text','Different text'),('stream_id','old'),('sentence_id','other'),('source_revision',1),
    ('spec_digest','changed'),('complete',False),('translation',' '),
    ('expires_at','2000-01-01T00:00:00+00:00'),('saved_at','2100-01-01T00:00:00+00:00')])
def test_reuse_validation_rejects_mismatch(field,value):
    c=candidate();c[field]=value
    row=SimpleNamespace(text='Hello world.',stream_id='stream',sentence_id='stream:1',source_revision=2)
    assert validated_reuse(c,row,translation_spec(settings,[]),now()) is None


@pytest.mark.parametrize('field,value',[
    ('model','changed'),('terms',[{'source':'hello','target':'您好'}]),('context','new'),
    ('source_lang','Korean'),('target_lang','English'),('memory',[{'source':'x','target':'y'}])])
def test_reuse_checks_all_translation_configuration(field,value):
    spec=translation_spec(settings,[]);spec[field]=value
    row=SimpleNamespace(text='Hello world.',stream_id='stream',sentence_id='stream:1',source_revision=2)
    assert validated_reuse(candidate(),row,spec,now()) is None


@pytest.mark.asyncio
async def test_mismatch_falls_back_to_streaming_and_batches_database_events(factory,monkeypatch):
    monkeypatch.setattr(settings,'incremental_translation_enabled',True)
    c=candidate();c['text']='not final source';tid,sid=prepare(factory,c)
    calls=[]
    async def model(self,text,**kwargs):
        calls.append(text)
        for _ in range(100):yield '中'
    monkeypatch.setattr('app.providers.aliyun.AliyunProvider.translate_stream',model)
    await tasks.execute_task(tid)
    with factory() as db:
        assert calls==['Hello world.']
        assert db.query(Event).filter_by(type='translation.partial').count()==1
        assert len(db.query(Translation).one().text)==100
        assert db.get(SegmentRevision,sid).latency['translation_reused'] is False
        assert db.get(SegmentRevision,sid).latency['translation_queue_ms']>=0


def test_priority_and_backoff_filter_before_limit(factory,monkeypatch):
    monkeypatch.setattr(settings,'incremental_translation_enabled',True)
    with factory() as db:
        seed(db)
        for i in range(60):
            t=enqueue(db,'alice','index_segment',f'index-{i}',{},session_id='lesson')
            t.status='retry';t.attempts=1;t.updated_at=now()
        normal=enqueue(db,'alice','summarize','summary',{},session_id='lesson')
        urgent=enqueue(db,'alice','translate','urgent',{},session_id='lesson');db.commit()
        assert tasks.pending_task_ids(db)==[urgent.id,normal.id]


@pytest.mark.asyncio
async def test_only_committed_outbox_wakes_worker(factory,monkeypatch):
    monkeypatch.setattr(settings,'incremental_translation_enabled',True)
    wake=asyncio.Event()
    monkeypatch.setattr(translation_dispatch,'worker_loop',asyncio.get_running_loop())
    monkeypatch.setattr(translation_dispatch,'worker_wakeup',wake)
    with factory() as db:
        seed(db)
        enqueue(db,'alice','translate','rolled-back',{},session_id='lesson')
        assert not wake.is_set();db.rollback();await asyncio.sleep(0);assert not wake.is_set()
        assert db.query(Outbox).count()==0
        enqueue(db,'alice','translate','committed',{},session_id='lesson')
        db.commit();await asyncio.sleep(0);assert wake.is_set()
        assert db.query(Outbox).count()==1


@pytest.mark.asyncio
async def test_local_worker_reserves_capacity_without_adding_workers(factory,monkeypatch):
    monkeypatch.setattr(settings,'incremental_translation_enabled',True)
    monkeypatch.setattr(tasks,'expire_audio',lambda:None)
    monkeypatch.setattr(tasks,'recover_abandoned',lambda:None)
    started=[];block=asyncio.Event();translated=asyncio.Event()
    async def execute(tid):
        with factory() as db:
            t=db.get(ProcessingTask,tid);t.status='running';kind=t.kind;db.commit()
        started.append(kind)
        if kind=='translate':translated.set()
        await block.wait()
    monkeypatch.setattr(tasks,'execute_task',execute)
    with factory() as db:
        seed(db)
        for i in range(3):enqueue(db,'alice','index_segment',f'index-{i}',{},session_id='lesson')
        db.commit()
    worker=asyncio.create_task(tasks.local_worker_loop())
    try:
        await asyncio.sleep(.03)
        with factory() as db:enqueue(db,'alice','translate','urgent',{},session_id='lesson');db.commit()
        await asyncio.wait_for(translated.wait(),1)
        assert started==['index_segment','translate']
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):await worker


def test_preview_cache_requires_complete_exact_fresh_result():
    entry=SimpleNamespace(completed=None)
    assert reuse_candidate(entry,'x',2,settings,stamp=1) is None
    entry.completed={'complete':True,'text':'x','translation':'中','completed_at':0}
    assert reuse_candidate(entry,'y',2,settings,stamp=1) is None
    assert reuse_candidate(entry,'x',2,settings,stamp=100) is None


def test_celery_priority_and_duplicate_dispatch_bound(factory,monkeypatch):
    monkeypatch.setattr(settings,'incremental_translation_enabled',True)
    calls=[]
    monkeypatch.setattr(tasks.process_task,'apply_async',lambda **kwargs:calls.append(kwargs))
    with factory() as db:
        seed(db)
        background=enqueue(db,'alice','summarize','summary',{},session_id='lesson')
        urgent=enqueue(db,'alice','translate','urgent',{},session_id='lesson');db.commit()
        ids=[urgent.id,background.id]
    tasks.dispatch_outbox();tasks.dispatch_outbox()
    assert [c['args'][0] for c in calls]==ids
    assert [c['priority'] for c in calls]==[0,6]
