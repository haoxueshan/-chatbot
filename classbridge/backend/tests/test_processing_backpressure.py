import asyncio
import threading
import time
from unittest.mock import AsyncMock
import pytest
from app.config import settings
from app.models import ProcessingTask,Session
from app.services.events import enqueue
from app.workers import tasks
from app.ws.live import LiveCapture
from test_core import factory,seed


@pytest.mark.asyncio
@pytest.mark.parametrize('pending',[100,200,500,5000])
async def test_backlog_stops_only_at_resource_hard_limit(factory,monkeypatch,pending):
    with factory() as db:
        seed(db,mode='real');row=db.get(Session,'lesson');row.status='recording'
        for i in range(pending):enqueue(db,'alice','index_segment',f'fixture:{i}',{},session_id='lesson')
        db.commit()
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.ready=True
    check=asyncio.create_task(c.maintain_capture())
    try:
        if pending==5000:
            from app.providers.aliyun import ProviderError
            with pytest.raises(ProviderError,match='硬容量'):await asyncio.wait_for(check,3)
            assert c.stopping
        else:
            # Wait on the actual maintenance result, bounded, not arbitrary extra delay.
            async with asyncio.timeout(3):
                while c.pending_processing_tasks!=pending:await asyncio.sleep(.01)
            assert not c.stopping and not check.done()
            with factory() as db:assert db.query(ProcessingTask).count()==pending
    finally:check.cancel();await asyncio.gather(check,return_exceptions=True)


@pytest.mark.parametrize('incremental',[False,True])
def test_deferred_index_resumes_and_formal_translation_stays_eligible(factory,monkeypatch,incremental):
    monkeypatch.setattr(settings,'incremental_translation_enabled',incremental)
    with factory() as db:
        seed(db,mode='real');row=db.get(Session,'lesson');row.status='recording'
        for i in range(200):enqueue(db,'alice','index_segment',f'index:{i}',{},session_id='lesson')
        formal=enqueue(db,'alice','translate','final',{},session_id='lesson');db.commit()
        assert tasks.pending_task_ids(db)==[formal.id]
        row.status='stopped';db.commit()
        ids=tasks.pending_task_ids(db)
        assert ids[0]==formal.id and len(ids)==50


@pytest.mark.asyncio
async def test_owned_worker_thread_keeps_api_loop_responsive_and_joins(monkeypatch):
    entered=threading.Event();finished=threading.Event();threads=[]
    async def worker():
        threads.append(threading.get_ident());entered.set()
        try:
            time.sleep(.15)  # Deliberately block worker SQL / parsing, not the API loop.
            await asyncio.Event().wait()
        finally:finished.set()
    monkeypatch.setattr(tasks,'local_worker_loop',worker)
    task=asyncio.create_task(tasks.isolated_local_worker_loop())
    while not entered.is_set():await asyncio.sleep(.001)
    tick=time.monotonic();await asyncio.sleep(.01)
    assert time.monotonic()-tick<.1 and threads[0]!=threading.get_ident()
    task.cancel();await asyncio.gather(task,return_exceptions=True)
    assert finished.is_set()


@pytest.mark.asyncio
async def test_periodic_summary_database_failure_does_not_end_capture(monkeypatch):
    monkeypatch.setattr(settings,'summary_interval_seconds',.01)
    c=LiveCapture(AsyncMock(),'fixture','owner');c.ready=True
    attempted=asyncio.Event()
    async def unavailable(_):
        attempted.set();raise RuntimeError('mock summary storage unavailable')
    c.write_database=unavailable
    task=asyncio.create_task(c.periodic_summary())
    try:
        await asyncio.wait_for(attempted.wait(),1);await asyncio.sleep(0)
        assert not task.done() and not c.stopping and not c.failure_reported
    finally:task.cancel();await asyncio.gather(task,return_exceptions=True)
