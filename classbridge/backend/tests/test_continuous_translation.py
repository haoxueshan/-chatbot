import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.config import settings
from app.models import ProcessingTask, SegmentRevision, Translation, Event, Outbox
from app.services.incremental_translation import PreviewBudget
from app.ws.live import LiveCapture
from app.workers.tasks import execute_task
from test_core import factory, seed
from test_incremental_translation import scheduler, flush
from app.services.translation_languages import LANGUAGES, target_name

SHORT = ['네','아니요','맞아요','잠깐만요','질문이 있습니다','교수님, 질문이 있습니다',
         '잘 모르겠습니다','다시 설명해 주세요','Yes.','No.','Excuse me.','I have a question.','Could you explain that again?']

@pytest.mark.asyncio
@pytest.mark.parametrize('text', SHORT)
async def test_short_expression_before_final_without_forging_agreement(text):
    s,p,clock,events=scheduler()
    try:
        s.update('short',1,text,0,400);s.tick();await flush();assert not p.calls
        clock[0]=.34;s.tick();await flush();assert not p.calls
        clock[0]=.35;s.tick();await flush()
        assert p.calls==[text]
        for i in range(20):s.update('short',i+2,text,0,500+i);s.tick();await flush()
        assert p.calls==[text] and events[-1][-1]['preview_complete']
        assert s.prefix.view('stream','short',clock[0]).stable_preview==''
    finally:await s.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('text', SHORT)
async def test_legacy_short_expression_before_final(factory,monkeypatch,text):
    import app.ws.live as live
    from app.providers.aliyun import AliyunProvider
    with factory() as db:seed(db,mode='real')
    monkeypatch.setattr(settings,'incremental_translation_enabled',False)
    monkeypatch.setattr('app.services.incremental_translation.preview_budget',PreviewBudget())
    clock=[100.];calls=[]
    monkeypatch.setattr(live,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    async def direct(fn,*args):return fn(*args)
    monkeypatch.setattr(live,'blocking_call',direct)
    async def mt(self,text,**kwargs):calls.append(text);yield '完整预译'
    monkeypatch.setattr(AliyunProvider,'translate_stream',mt)
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode='real';c.started=100
    try:
        await c.consume({'sentence_id':'a','text':text,'end_ms':400})
        clock[0]=100.36;c.tick_legacy();await flush()
        assert calls==[text]
        for i in range(20):await c.consume({'sentence_id':'a','text':text,'end_ms':500+i})
        await flush();assert calls==[text]
        with factory() as db:assert db.query(SegmentRevision).count()==0
    finally:
        for task in c.translation_tasks.values():task.cancel()
        await asyncio.gather(*c.translation_tasks.values(),return_exceptions=True)

@pytest.mark.asyncio
@pytest.mark.parametrize('incremental',[False,True])
@pytest.mark.parametrize('ending',['completed','stopped','failed'])
async def test_final_preserves_matching_inflight_and_outbox_waits(factory,monkeypatch,incremental,ending):
    import app.ws.live as live
    from app.providers.aliyun import AliyunProvider,ProviderError
    with factory() as db:seed(db,mode='real')
    monkeypatch.setattr(settings,'incremental_translation_enabled',incremental)
    monkeypatch.setattr('app.services.incremental_translation.preview_budget',PreviewBudget())
    clock=[100.];calls=[];cancelled=[];release=asyncio.Event()
    monkeypatch.setattr(live,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    async def direct(fn,*args):return fn(*args)
    monkeypatch.setattr(live,'blocking_call',direct)
    async def mt(self,text,**kwargs):
        calls.append(text)
        try:
            yield '今天';await release.wait()
            if ending=='failed' and len(calls)==1:raise ProviderError('timeout','mock interrupted',retryable=True)
            yield '学习人工智能。'
        except asyncio.CancelledError:cancelled.append(text);raise
    monkeypatch.setattr(AliyunProvider,'translate_stream',mt)
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode='real';c.started=100
    if incremental:c.ensure_preview().clock=lambda:clock[0]
    event={'sentence_id':'a','text':'오늘은 인공지능을 공부합니다.','start_ms':0,'end_ms':900,'final':False}
    try:
        await c.consume(event);clock[0]=103
        if c.preview:c.preview.tick()
        else:c.tick_legacy()
        await flush();assert len(calls)==1
        await c.consume({**event,'final':True});await flush()
        assert cancelled==[]
        with factory() as db:
            assert db.query(SegmentRevision).one().text==event['text']
            task=db.query(ProcessingTask).filter_by(kind='translate').one();tid=task.id
            assert db.query(Outbox).filter_by(task_id=tid).count()==1
        # A different worker Session must observe durable deferral, not an asyncio.Task.
        await execute_task(tid);assert len(calls)==1
        with factory() as db:assert db.get(ProcessingTask,tid).attempts==0
        if ending=='stopped':
            c.stopping=True
            c.ws.send_json.side_effect=RuntimeError('browser already disconnected')
        release.set();await flush()
        await c.drain_final_translations()
        await execute_task(tid);await execute_task(tid)
        with factory() as db:
            assert db.query(Translation).one().text=='今天学习人工智能。'
            assert db.query(Event).filter_by(type='translation.final').count()==1
        assert len(calls)==(2 if ending=='failed' else 1) and cancelled==[]
        assert not c.final_translations
    finally:
        release.set()
        if hasattr(c,'drain_final_translations'):await c.drain_final_translations()
        if c.preview:await c.preview.close()
        for t in c.translation_tasks.values():t.cancel()
        await asyncio.gather(*c.translation_tasks.values(),return_exceptions=True)

@pytest.mark.asyncio
async def test_incomplete_korean_endings_and_neutral_period_do_not_churn():
    s,p,clock,events=scheduler()
    try:
        for i,text in enumerate(['인공지능','인공지능을','인공지능을 공부']):
            clock[0]=i;s.update('a',i+1,text,0,500);s.tick();await flush()
        assert not p.calls
        clock[0]=4;s.update('a',4,'아니요',0,600)
        clock[0]=4.36;s.tick();await flush()
        clock[0]=6;s.update('a',5,'아니요.',0,700);s.tick();await flush()
        clock[0]=9;s.tick();await flush()
        clock[0]=10;s.update('a',6,'아니요',0,800);s.tick();await flush()
        assert p.calls==['아니요']
    finally:await s.close()

@pytest.mark.asyncio
async def test_thirty_seconds_growth_has_bounded_calls_and_no_cancellation():
    s,p,clock,events=scheduler(preview_calls_per_minute=8)
    try:
        for i in range(30):
            clock[0]=i
            text=('오늘은 인공지능 모델을 설명하겠습니다. '+('교수님 질문이 있습니다. '*(i//5+1))).strip()
            s.update('turn',i+1,text,0,i*1000);s.tick();await flush()
            clock[0]=i+.5;s.tick();await flush()
        assert 2<=len(p.calls)<=8 and s.metrics['cancelled']==0
        assert len(s.sentences)==1 and len(s.tasks)==0
        assert all(event[0]=='turn' for event in events) # no invented speaker/ASR boundary
        assert p.calls[0].startswith('오늘은')
    finally:await s.close()

@pytest.mark.asyncio
async def test_continuous_expression_changes_cannot_reset_max_wait():
    s,p,clock,events=scheduler()
    try:
        for i in range(40):
            clock[0]=i/10
            s.update('a',i+1,f'{i}개 모델을 설명합니다',0,i*100);s.tick();await flush()
        assert len(p.calls)==1 and p.calls[0]=='24개 모델을 설명합니다'
        assert events[-1][-1]['preview_complete']
    finally:await s.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('language',list(LANGUAGES))
async def test_complete_continuous_preview_reused_for_all_targets(factory,monkeypatch,language):
    import app.ws.live as live
    from app.providers.aliyun import AliyunProvider
    with factory() as db:
        row=seed(db,mode='real');row.target_language=language;db.commit()
    monkeypatch.setattr(settings,'incremental_translation_enabled',True)
    monkeypatch.setattr('app.services.incremental_translation.preview_budget',PreviewBudget())
    clock=[100.];calls=[]
    monkeypatch.setattr(live,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    async def direct(fn,*args):return fn(*args)
    monkeypatch.setattr(live,'blocking_call',direct)
    async def mt(self,text,**kwargs):calls.append(kwargs['target_lang']);yield language+': mock full text'
    monkeypatch.setattr(AliyunProvider,'translate_stream',mt)
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode='real';c.started=100
    c.ensure_preview().clock=lambda:clock[0]
    text='I have a question.' if language=='ko' else '질문이 있습니다'
    try:
        await c.consume({'sentence_id':'a','text':text,'end_ms':500})
        clock[0]=100.36;c.preview.tick();await flush()
        await c.consume({'sentence_id':'a','text':text,'end_ms':500,'final':True})
        with factory() as db:tid=db.query(ProcessingTask).filter_by(kind='translate').one().id
        await execute_task(tid);await execute_task(tid)
        assert calls==[target_name(language)]
        with factory() as db:
            tr=db.query(Translation).one();assert tr.target_language==language and tr.text==language+': mock full text'
            assert db.get(ProcessingTask,tid).result['translation_reused']==1
            assert db.query(Event).filter_by(type='translation.final').count()==1
    finally:await c.preview.close()

@pytest.mark.asyncio
async def test_fallback_timeout_never_saves_partial_or_retries(factory,monkeypatch):
    from app.providers.aliyun import AliyunProvider
    from test_translation_scheduling import prepare
    tid,_=prepare(factory);calls=[];closed=[]
    monkeypatch.setattr(settings,'model_timeout_seconds',.03)
    async def mt(self,text,**kwargs):
        calls.append(text)
        try:yield '部分';await asyncio.Event().wait()
        finally:closed.append(True)
    monkeypatch.setattr(AliyunProvider,'translate_stream',mt)
    await execute_task(tid);await execute_task(tid)
    with factory() as db:
        assert db.get(ProcessingTask,tid).status=='failed'
        assert db.query(Event).filter_by(type='processing.failed').one().payload['code']=='timeout'
        assert db.query(SegmentRevision).count()==1 and db.query(Translation).count()==0
        assert db.query(Event).filter_by(type='translation.final').count()==0
    assert len(calls)==1 and closed==[True]

@pytest.mark.asyncio
@pytest.mark.parametrize('incremental',[False,True])
@pytest.mark.parametrize('outcome',['completed','failed','rewritten','final_only'])
async def test_verified_snapshots_or_one_necessary_fallback(factory,monkeypatch,incremental,outcome):
    import app.ws.live as live
    from app.providers.aliyun import AliyunProvider,ProviderError
    from app.services.events import serialize_segment
    with factory() as db:seed(db,mode='real')
    monkeypatch.setattr(settings,'incremental_translation_enabled',incremental)
    monkeypatch.setattr('app.services.incremental_translation.preview_budget',PreviewBudget())
    clock=[100.];calls=[]
    monkeypatch.setattr(live,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    async def direct(fn,*args):return fn(*args)
    monkeypatch.setattr(live,'blocking_call',direct)
    async def mt(self,text,**kwargs):
        calls.append(text);yield '译文：'
        if outcome=='failed' and len(calls)==1:raise ProviderError('timeout','mock interrupted',retryable=True)
        yield text
    monkeypatch.setattr(AliyunProvider,'translate_stream',mt)
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode='real';c.started=100
    if incremental:c.ensure_preview().clock=lambda:clock[0]
    event={'sentence_id':'a','text':'오늘은 인공지능을 공부합니다.','end_ms':1000}
    try:
        if outcome!='final_only':
            await c.consume(event);clock[0]=103
            if c.preview:c.preview.tick()
            else:c.tick_legacy()
            await flush()
        if outcome=='rewritten':event['text']='어제는 인공지능을 공부했습니다.'
        await c.consume({**event,'final':True});await c.consume({**event,'final':True})
        await c.drain_final_translations()
        with factory() as db:tid=db.query(ProcessingTask).filter_by(kind='translate').one().id
        await execute_task(tid);await execute_task(tid)
        assert len(calls)==(2 if outcome in ('failed','rewritten') else 1)
        with factory() as db:
            row=db.query(SegmentRevision).one()
            assert row.text==event['text']
            assert serialize_segment(db,row)['translation']=='译文：'+event['text']
            assert db.query(Event).filter_by(type='translation.final').count()==1
    finally:
        await c.drain_final_translations()
        if c.preview:await c.preview.close()
        for t in c.translation_tasks.values():t.cancel()
        await asyncio.gather(*c.translation_tasks.values(),return_exceptions=True)

@pytest.mark.asyncio
@pytest.mark.parametrize('resolved',[False,True])
async def test_separate_celery_executor_process_observes_durable_handoff(factory,monkeypatch,resolved):
    import os,sys
    from datetime import timedelta
    from app.models import now
    from app.services.translation_dispatch import finish_handoff
    from test_translation_scheduling import prepare,candidate
    tid,_=prepare(factory)
    with factory() as db:
        task=db.get(ProcessingTask,tid)
        task.payload={**task.payload,'preview_handoff':{'request_id':7,'deadline':(now()+timedelta(seconds=30)).isoformat()}}
        db.commit()
    code='''import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.workers import tasks
from app.providers.aliyun import AliyunProvider
tasks.SessionLocal=sessionmaker(bind=create_engine(sys.argv[1]),expire_on_commit=False)
def forbidden(*a,**k): raise AssertionError('worker must not call a paid model')
AliyunProvider.translate_stream=forbidden
tasks.process_task.run(sys.argv[2])
'''
    async def worker():
        env={**os.environ,'DASHSCOPE_API_KEY':'','DASHSCOPE_WORKSPACE_ID':'','DATABASE_URL':str(factory.kw['bind'].url),'TASK_MODE':'disabled'}
        child=await asyncio.create_subprocess_exec(sys.executable,'-c',code,str(factory.kw['bind'].url),tid,
            env=env,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        _,err=await asyncio.wait_for(child.communicate(),15)
        assert child.returncode==0,err.decode(errors='replace')
    await worker()
    with factory() as db:
        task=db.get(ProcessingTask,tid);assert task.status=='pending' and task.attempts==0
        if resolved:assert finish_handoff(db,tid,7,candidate())
        else:
            task.payload={**task.payload,'preview_handoff':{'request_id':7,'deadline':(now()-timedelta(seconds=1)).isoformat()}};db.commit()
    await worker();await worker()
    with factory() as db:
        assert db.query(SegmentRevision).count()==1
        assert db.get(ProcessingTask,tid).status==('completed' if resolved else 'failed')
        assert db.query(Translation).count()==int(resolved)
        assert db.query(Event).filter_by(type='translation.final').count()==int(resolved)
        if not resolved:
            assert db.query(Event).filter_by(type='processing.failed').one().payload['code']=='preview_outcome_unknown'
