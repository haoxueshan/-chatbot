"""Run explicitly from backend: python tests/benchmark_translation_scheduler.py.

Extracts the actual old/new local_worker_loop functions; replaces only storage
and task execution with a fixed in-memory fixture. No DB, microphone or API.
This measures idle scheduler admission, NOT classroom latency or cloud quality.
"""
import ast
import asyncio
import contextlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services import translation_dispatch

BASELINE='79dd0e2'


async def trial(source,enabled,wake):
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='local_worker_loop')
    pending=[];future=asyncio.get_running_loop().create_future();started=0
    class DB:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,*args):return SimpleNamespace(kind='translate')
    async def execute(tid):
        pending.clear()
        if not future.done():future.set_result((time.monotonic()-started)*1000)
    scope={'asyncio':asyncio,'contextlib':contextlib,'SessionLocal':DB,
        'pending_task_ids':lambda db:list(pending),'execute_task':execute,
        'expire_audio':lambda:None,'recover_abandoned':lambda:None,'ProcessingTask':object,
        'settings':SimpleNamespace(incremental_translation_enabled=enabled,translation_poll_seconds=.1)}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'scheduler_benchmark','exec'),scope)
    worker=asyncio.create_task(scope['local_worker_loop']())
    try:
        await asyncio.sleep(.025)
        started=time.monotonic();pending.append('translation')
        if wake:translation_dispatch.worker_loop.call_soon_threadsafe(translation_dispatch.worker_wakeup.set)
        return round(await asyncio.wait_for(future,2),3)
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):await worker


async def main():
    original=subprocess.check_output(['git','show',BASELINE+':classbridge/backend/app/workers/tasks.py'],encoding='utf-8')
    current=Path('app/workers/tasks.py').read_text(encoding='utf-8')
    report={'fixture':'idle worker; task arrives 25ms after scan; six runs; mock execution; no paid API',
        'baseline':BASELINE,'percentile':'P50 median; P95 nearest-rank (max for n=6)','results':{}}
    for name,source,enabled,wake in [('baseline',original,False,False),('experiment_poll_fallback',current,True,False),('experiment_commit_wakeup',current,True,True)]:
        values=[await trial(source,enabled,wake) for _ in range(6)]
        report['results'][name]={'queue_ms':values,'p50_ms':round(statistics.median(values),3),'p95_ms':max(values)}
    print(json.dumps(report,indent=2))


if __name__=='__main__':asyncio.run(main())
