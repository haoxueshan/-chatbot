import asyncio
from unittest.mock import AsyncMock
import pytest
from app.config import Settings, settings
from app.services.incremental_translation import IncrementalTranslator, PreviewBudget, translation_spec
from app.ws.live import LiveCapture
from app.models import SegmentRevision, Chunk
from test_core import factory, seed


def config(**kwargs):
    return Settings(_env_file=None, incremental_translation_enabled=True,
                    preview_min_stable_seconds=0, preview_interval_seconds=.2, **kwargs)


class Provider:
    def __init__(self):self.calls=[]
    async def translate_stream(self,text,**kwargs):
        self.calls.append(text)
        yield '临时';yield '中文'


def scheduler(provider=None, **kwargs):
    c=config(**kwargs);clock=[0.];published=[]
    async def publish(*args):published.append(args)
    p=provider or Provider()
    s=IncrementalTranslator(c,'stream',translation_spec(c,[]),p,publish,
        clock=lambda:clock[0],budget=PreviewBudget())
    return s,p,clock,published


async def flush():
    for _ in range(4):await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_compatible_growth_waits_for_running_preview_instead_of_cancelling():
    release=asyncio.Event()
    class Slow(Provider):
        async def translate_stream(self,text,**kwargs):
            self.calls.append(text);yield '译';await release.wait();yield '文'
    s,p,clock,events=scheduler(Slow())
    try:
        s.update('a',1,'오늘은 인공지능을 공부합니다.',0,1000)
        clock[0]=3;s.tick();await flush()
        clock[0]=6;s.update('a',2,'오늘은 인공지능을 공부합니다. 다음 내용을 설명합니다.',0,2000);s.tick();await flush()
        assert s.metrics['cancelled']==0 and len(p.calls)==1
        release.set();await flush();s.tick();await flush()
        assert len(p.calls)==2 and events[-1][-1]['preview_complete']
    finally:release.set();await s.close()


@pytest.mark.asyncio
async def test_timestamp_liveness_does_not_expire_failed_attempt_or_forge_agreement():
    class Broken(Provider):
        async def translate_stream(self,text,**kwargs):
            self.calls.append(text);raise RuntimeError('mock failure')
            yield ''
    s,p,clock,events=scheduler(Broken())
    try:
        for i in range(15):
            clock[0]=i*5
            s.update('a',i+1,'오늘은 인공지능을 공부합니다.',0,i*100)
            s.tick();await flush()
        assert len(p.calls)==1 and s.metrics['failed']==1 and not events
        assert s.prefix.view('stream','a',clock[0]).hypothesis_revision==1
        assert s.prefix.view('stream','a',clock[0]).stable_preview==''
    finally:await s.close()


@pytest.mark.asyncio
async def test_agreement_dedup_compatible_tail_and_timed_fallback():
    s,p,clock,events=scheduler()
    s.update('a',1,'We study neural net',0,500)
    clock[0]=.5;s.update('a',2,'We study neural networks',0,600);s.tick();await flush()
    assert p.calls==['We study neural']
    assert events[-1][1]==2 and events[-1][-1]['preview_complete']
    clock[0]=1;s.update('a',3,'We study neural networks today',0,700);s.tick();await flush()
    assert p.calls==['We study neural'] # one small extra word cannot churn the API
    clock[0]=3;s.tick();await flush()
    assert len(p.calls)==2
    s.tick();await flush();assert len(p.calls)==2
    await s.close()


@pytest.mark.asyncio
async def test_single_hypothesis_fallback_waits_without_confirming_source():
    s,p,clock,events=scheduler()
    s.update('a',1,'오늘 수업입니다.',0,1000);s.tick();await flush();assert not p.calls
    clock[0]=2.5;s.tick();await flush()
    assert p.calls==['오늘 수업입니다.']
    assert s.prefix.view('stream','a',3).stable_preview==''
    await s.close()


@pytest.mark.asyncio
async def test_cancelled_cloud_response_cannot_publish_after_rewrite_or_final():
    entered=asyncio.Event();release=asyncio.Event()
    class Late:
        async def translate_stream(self,text,**kwargs):
            entered.set()
            try:await release.wait()
            except asyncio.CancelledError:pass # emulate provider delivering a late response
            yield '旧中文不能出现'
    s,p,clock,events=scheduler(Late())
    s.update('a',1,'We study neural net',0,500)
    clock[0]=.5;s.update('a',2,'We study neural networks',0,500);s.tick();await entered.wait()
    s.update('a',3,'A different hypothesis',0,600)
    await flush();assert events==[]
    assert s.metrics['cancelled']==1
    s.finalize('a');release.set();await flush();assert events==[]
    assert not s.sentences and not s.prefix.states
    await s.close()


@pytest.mark.asyncio
async def test_shared_admission_limit_multiple_sentences_and_failure_is_optional():
    s,p,clock,events=scheduler(preview_calls_per_minute=2)
    for sid in ('a','b','c'):
        s.update(sid,1,'Meaningful complete sentence.',0,1000)
    clock[0]=3
    for _ in range(4):s.tick();await flush()
    assert len(p.calls)==2 and s.budget.active==0
    clock[0]=65;s.tick();await flush() # entries expire, no delayed paid request
    assert len(p.calls)==2 and not s.sentences
    await s.close()
    class Broken:
        async def translate_stream(self,*a,**k):
            raise RuntimeError('mock failure')
            yield ''
    s,p,clock,events=scheduler(Broken())
    s.update('a',1,'Complete sentence.',0,1000);clock[0]=3;s.tick();await flush()
    s.tick();await flush()
    assert s.metrics['failed']==s.metrics['requests']==1 and not events
    await s.close()


@pytest.mark.asyncio
async def test_two_captures_share_gate_and_cleanup_is_bounded():
    gate=PreviewBudget();s,p,clock,_=scheduler(preview_max_sentences=4)
    other,_,other_clock,_=scheduler();s.budget=other.budget=gate
    for i in range(10000):s.update(str(i),1,'Complete sentence.',0,1000)
    assert len(s.sentences)==len(s.prefix.states)==4
    other.update('a',1,'Complete sentence.',0,1000)
    clock[0]=other_clock[0]=3;s.tick();other.tick()
    assert gate.active==1
    await flush();await s.close();await other.close();assert gate.active==0


@pytest.mark.asyncio
async def test_live_feature_gate_rag_isolation_late_final_and_stream_switch(factory,monkeypatch):
    monkeypatch.setattr(settings,'incremental_translation_enabled',True)
    with factory() as db:seed(db,mode='real')
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode='real';c.started=0
    event={'sentence_id':'a','text':'오늘은 RAG 공부', 'start_ms':0,'end_ms':100,'final':False}
    await c.consume(event)
    first=c.ws.send_json.call_args.args[0]
    assert first['stable_preview']=='' and first['hypothesis_revision']==1
    with factory() as db:assert db.query(SegmentRevision).count()==db.query(Chunk).count()==0
    await c.consume({**event,'final':True})
    assert not c.preview.sentences and not c.preview.prefix.states
    sent=c.ws.send_json.call_count
    await c.consume(event);assert c.ws.send_json.call_count==sent
    with factory() as db:assert db.query(SegmentRevision).count()==1
    await c.preview.close()
    demo=LiveCapture(AsyncMock(),'lesson','alice');demo.mode='demo'
    assert demo.ensure_preview() is None
    monkeypatch.setattr(settings,'incremental_translation_enabled',False)
    legacy=LiveCapture(AsyncMock(),'lesson','alice');legacy.mode='real'
    assert legacy.ensure_preview() is None


def test_new_stream_cannot_reuse_old_sentence_state():
    s,_,_,_=scheduler()
    s.update('a',1,'Old stream text.',0,1000)
    other,_,_,_=scheduler();other.stream_id='new'
    assert not other.sentences and not other.prefix.states
