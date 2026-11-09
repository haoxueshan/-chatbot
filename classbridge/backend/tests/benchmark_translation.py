"""Opt-in Mock replay; needs the reviewed baseline Git object, no paid requests.

Run from backend: python tests/benchmark_translation.py
"""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['DASHSCOPE_API_KEY']=''
import pytest
from test_core import factory,seed
from app.config import settings
from app.providers.aliyun import AliyunProvider
from app.services.incremental_translation import PreviewBudget
import app.ws.live as current

BASELINE='b6429189ceb32cfb50239b15b7af7661815cf62c'


@pytest.mark.asyncio
async def test_replay(factory,monkeypatch):
    source=subprocess.check_output(['git','show',f'{BASELINE}:classbridge/backend/app/ws/live.py'],encoding='utf8')
    baseline=types.ModuleType('baseline_live');exec(compile(source,'baseline_live','exec'),baseline.__dict__)
    monkeypatch.setattr(settings,'incremental_translation_enabled',False)
    with factory() as db:seed(db,mode='real')
    results={}
    for name,module in [('before',baseline),('after',current)]:
        monkeypatch.setattr('app.services.incremental_translation.preview_budget',PreviewBudget())
        clock=[100.];calls=[];cancelled=[]
        monkeypatch.setattr(module,'time',types.SimpleNamespace(monotonic=lambda:clock[0]))
        monkeypatch.setattr(module,'SessionLocal',factory)
        async def direct(fn,*args):return fn(*args)
        monkeypatch.setattr(module,'blocking_call',direct)
        async def mt(self,text,**kwargs):
            calls.append(text)
            try:yield 'Mock preview';await asyncio.Event().wait()
            except asyncio.CancelledError:cancelled.append(True);raise
        monkeypatch.setattr(AliyunProvider,'translate_stream',mt)
        c=module.LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode='real';c.started=100
        try:
            for i in range(20):
                clock[0]=100+i*1.3
                await c.consume({'sentence_id':'1','text':'오늘은 인공지능을 공부합니다','start_ms':0,'end_ms':1200+i*100})
                for _ in range(4):await asyncio.sleep(0)
            results[name]={'asr_partials':20,'effective_source_changes':1,'mt_requests':len(calls),
                'redundant_mt_requests':len(calls)-len(set(calls)),'mt_cancellations':len(cancelled),
                'translation_partials':sum(call.args[0]['type']=='translation.partial' for call in c.ws.send_json.call_args_list)}
        finally:
            for task in c.translation_tasks.values():task.cancel()
            await asyncio.gather(*c.translation_tasks.values(),return_exceptions=True)
    print(json.dumps({'baseline':BASELINE,**results},indent=2))
    assert results['after']['mt_requests']==1 and results['after']['mt_cancellations']==0


if __name__=='__main__':raise SystemExit(pytest.main([__file__,'-q','-s']))
