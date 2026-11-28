import asyncio
import json
import subprocess
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import event as sql_event
from test_core import factory, seed
from app.models import Session, SegmentRevision, ProcessingTask
from app.providers.errors import ProviderError
from app.providers.transport import ASRResultQueue
from app.services.transcript_processor import normalize_update
from app.services.transcript_state import HypothesisStore, Decision
from app.ws.live import LiveCapture


def event(**changes):
    return {'sentence_id':'1','text':'한국어 English','start_ms':1000,'end_ms':2500,'final':False,**changes}


def test_offset_unknown_and_provisional_are_distinct():
    value=normalize_update(event(final=True),'stream',60000)
    assert (value.start_ms,value.end_ms,value.end_state)==(61000,62500,'confirmed')
    assert normalize_update(event(end_ms=None),'stream',60000).end_state=='unknown'
    value=normalize_update(event(end_ms=None,provisional_end_ms=2000),'stream',60000)
    assert value.end_ms==62000 and value.end_state=='provisional'
    assert normalize_update(event(stream_id='old'),'stream',60000) is None
    with pytest.raises(ProviderError):normalize_update(event(final=True,end_ms=None),'stream',0)


def test_state_eviction_requires_lookup_and_keeps_bounded_hypotheses():
    store=HypothesisStore()
    for i in range(600):
        value=normalize_update(event(sentence_id=str(i),final=True),'s',0)
        store.commit_final(value,1);store.trim()
    assert len(store.finalized)==512 and len(store.final_results)<=2048
    assert store.assess(normalize_update(event(sentence_id='0'),'s',0))==Decision.REQUIRES_LOOKUP
    assert store.assess(normalize_update(event(sentence_id='599'),'s',0))==Decision.STALE
    assert store.assess(normalize_update(event(sentence_id='599',final=True,text='new'),'s',0),allow_final_revision=False)==Decision.CONFLICT
    store.unconfirmed.update({str(i):{} for i in range(200)})
    with pytest.raises(ProviderError):store.check_partial_capacity('overflow')


@pytest.mark.asyncio
async def test_invalid_final_storage_failure_and_conflicting_final_keep_evidence(factory,monkeypatch):
    import app.ws.live as live
    with factory() as db:seed(db,mode='real')
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream'
    c.update_legacy=lambda *a:None
    await c.consume(event())
    with pytest.raises(ProviderError):await c.consume(event(final=True,end_ms=None))
    assert c.unconfirmed['stream:1']['text']=='한국어 English'
    save=live.save_final
    def broken(*a,**k):raise RuntimeError('database unavailable')
    monkeypatch.setattr(live,'save_final',broken)
    with pytest.raises(ProviderError) as error:await c.consume(event(final=True))
    assert error.value.code=='source_storage_failed' and not c.finalized and c.unconfirmed
    monkeypatch.setattr(live,'save_final',save)
    c.asr_provider=SimpleNamespace(supports_final_revisions=False)
    await c.consume(event(final=True));await c.consume(event(final=True,text='conflict'))
    assert c.asr_metrics['final_conflicts']==1
    with factory() as db:assert db.query(SegmentRevision).one().text=='한국어 English'
    # An evicted identity must consult durable evidence before accepting a partial.
    c.reset_source_state();await c.consume(event(text='late partial'))
    assert not c.unconfirmed
    with factory() as db:db.get(Session,'lesson').active_stream_id=None;db.commit()
    await c.consume(event(sentence_id='2'))
    assert 'stream:2' not in c.unconfirmed


@pytest.mark.asyncio
@pytest.mark.parametrize('version',['baseline','current'])
async def test_partial_benchmark(factory,monkeypatch,version):
    """Identical temporary SQLite, queue, input, clock and disabled preview work."""
    import app.ws.live as current
    module=current
    if version=='baseline':
        source=subprocess.check_output(['git','show','62d269f1ecab297b2bed53ef6c383b7e895b7729:classbridge/backend/app/ws/live.py']).decode('utf-8')
        module=ModuleType('p4_baseline_live');exec(compile(source,'baseline_live.py','exec'),module.__dict__)
    with factory() as db:seed(db,mode='real')
    sessions=0;selects=0;times=[];metrics={}
    def counted_factory():
        nonlocal sessions
        sessions+=1;return factory()
    def counted_sql(_c,_cursor,statement,*args):
        nonlocal selects
        if statement.lstrip().upper().startswith('SELECT'):selects+=1
    monkeypatch.setattr(module,'SessionLocal',counted_factory)
    sql_event.listen(factory.kw['bind'],'before_cursor_execute',counted_sql)
    c=module.LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.started=time.monotonic();c.target_language='zh-CN'
    c.update_legacy=lambda *a:None
    queue=ASRResultQueue(metrics)
    async def produce():
        for i in range(100):await queue.put(event(text='한국어 English '+str(i),end_ms=2500+i))
    async def consume():
        for _ in range(100):
            stamp=time.perf_counter();await c.consume(await queue.get());times.append((time.perf_counter()-stamp)*1000)
    await asyncio.gather(produce(),consume())
    partial_sessions,partial_selects=sessions,selects
    await c.consume(event(text='한국어 English 99',final=True,end_ms=2599))
    await c.consume(event(text='한국어 English 99',final=True,end_ms=2599))
    with factory() as db:
        assert db.query(SegmentRevision).count()==1
        assert db.query(ProcessingTask).filter_by(kind='translate').count()==1
    assert c.current_revisions['stream:1']==101 and not c.unconfirmed
    assert partial_sessions==100
    assert partial_selects==(101 if version=='baseline' else 100)
    ordered=sorted(times)
    print('\nP4_BENCHMARK '+json.dumps(dict(version=version,partials=100,selects=partial_selects,
        sessions=partial_sessions,p50_ms=ordered[49],p95_ms=ordered[94],queue_peak=metrics['asr_result_queue_peak'],
        finals=1,duplicate_finals=0,translation_tasks=1,unconfirmed_after_final=len(c.unconfirmed))))
    sql_event.remove(factory.kw['bind'],'before_cursor_execute',counted_sql)


@pytest.mark.asyncio
async def test_equal_display_time_still_updates_confirmation_state(factory):
    with factory() as db:seed(db,mode='real')
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream'
    c.update_legacy=lambda *a:None
    await c.consume(event(end_ms=None))
    await c.consume(event(end_ms=1000))
    assert c.current_revisions['stream:1']==2
    assert c.unconfirmed['stream:1']['end_time_state']=='confirmed'


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['final','owner','stream','deleted'])
async def test_known_partial_revalidates_external_database_changes(factory,change):
    from app.services.events import save_final
    with factory() as db:seed(db,mode='real')
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.update_legacy=lambda *a:None
    await c.consume(event())
    sent=c.ws.send_json.await_count
    with factory() as db:
        row=db.get(Session,'lesson')
        if change=='final':save_final(db,'lesson','stream','stream:1',10,'external final',1000,2500)
        elif change=='owner':row.user_id='bob'
        elif change=='stream':row.active_stream_id=None
        else:db.delete(row)
        db.commit()
    await c.consume(event(text='late partial'))
    assert c.ws.send_json.await_count==sent
