"""Deterministic synthetic ASR replay, NOT recorded classroom audio.

From backend: python tests/benchmark_incremental_replay.py
Uses baseline/current consume code with virtual time and a 450ms Mock MT. No API.
"""
import ast
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace,MethodType
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.services.incremental_translation import IncrementalTranslator,PreviewBudget,translation_spec
import app.ws.live as live
import app.providers.aliyun as aliyun

TRACES={
    'korean':[(.1,'오늘은 인공지능을 배'),(.5,'오늘은 인공지능을 배웁'),
        (.9,'오늘은 인공지능을 배우고'),(1.3,'오늘은 인공지능을 배우고 RAG를'),
        (1.7,'오늘은 인공지능을 배우고 RAG를 공부'),(2.1,'오늘은 인공지능을 배우고 RAG를 공부합니다.')],
    'english':[(.1,'We study neural net'),(.5,'We study neural networks'),
        (.9,'We study neural networks and'),(1.3,'We study neural networks and retrieval'),
        (1.7,'We study neural networks and retrieval today.')],
    'rewrite_mixed':[(.1,'오늘은 RAG retrieval 방법'),(.5,'오늘은 RAG retrieval 방법을'),
        (.9,'오늘은 RAG retrieval 방법을 설명'),(1.3,'오늘은 RAG retrieval 방법을 설명합니다.'),
        (1.8,'어제는 AI retrieval 방법을 설명했습니다.'),(2.2,'어제는 AI retrieval 방법을 설명했습니다. 다음은')],
}


async def replay(trace,enabled,baseline_consume):
    clock=[10.];sleepers=[];calls=[];sent=[];saved=[];cancelled=[]
    async def sleep(seconds):
        future=asyncio.get_running_loop().create_future()
        sleepers.append((clock[0]+seconds,future));await future
    class MockMT:
        async def translate_stream(self,text,**kwargs):
            calls.append(clock[0])
            try:await sleep(.45)
            except asyncio.CancelledError:cancelled.append(1);raise
            yield 'Mock Chinese preview'
    class DB:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,*args):return SimpleNamespace(settings={})
    class WS:
        async def send_json(self,event):sent.append((round(clock[0]-10,3),event))
    c=Settings(_env_file=None,incremental_translation_enabled=enabled)
    old_settings,old_time,old_db,old_save,old_provider=live.settings,live.time,live.SessionLocal,live.save_final,aliyun.AliyunProvider
    try:
        live.settings=c;live.time=SimpleNamespace(monotonic=lambda:clock[0]);live.SessionLocal=DB
        live.save_final=lambda *args,**kwargs:saved.append(kwargs)
        provider=MockMT();aliyun.AliyunProvider=lambda:provider
        capture=live.LiveCapture(WS(),'fixture','fixture');capture.mode='real';capture.stream_id='stream';capture.started=10
        if enabled:
            capture.preview=IncrementalTranslator(c,'stream',translation_spec(c,[]),provider,capture.publish_preview,
                clock=lambda:clock[0],budget=PreviewBudget())
        else:
            scope=dict(live.__dict__)
            exec(compile(ast.Module(body=[baseline_consume],type_ignores=[]),'baseline_consume','exec'),scope)
            capture.consume=MethodType(scope['consume'],capture)
        events=[(at,{'sentence_id':'1','text':text,'start_ms':0,'end_ms':int(at*1000),'final':False}) for at,text in trace]
        final_at=trace[-1][0]+.6
        events.append((final_at,{**events[-1][1],'final':True}))
        for step in range(101):
            clock[0]=10+step*.05
            while events and events[0][0]<=step*.05+1e-8:
                _,event=events.pop(0);await capture.consume(event)
            if enabled:capture.preview.tick()
            for until,future in list(sleepers):
                if until<=clock[0]+1e-8 and not future.done():future.set_result(None)
            for _ in range(4):await asyncio.sleep(0)
        if enabled:await capture.preview.close()
        for task in capture.translation_tasks.values():task.cancel()
        await asyncio.gather(*capture.translation_tasks.values(),return_exceptions=True)
        first=next((round(at*1000) for at,event in sent if event['type']=='translation.partial'),None)
        return {'source_first_ms':round(trace[0][0]*1000),
            'source_final_from_audio_start_ms':round(final_at*1000),
            'preview_first_from_audio_start_ms':first,'preview_requests':len(calls),
            'cancelled_requests':len(cancelled),
            'stable_preview_rollbacks':capture.preview.prefix.rollbacks if enabled else None,
            'formal_mt_latency':'not simulated; see separate queue benchmark'}
    finally:
        live.settings,live.time,live.SessionLocal,live.save_final,aliyun.AliyunProvider=old_settings,old_time,old_db,old_save,old_provider


async def main():
    original=subprocess.check_output(['git','show','79dd0e2:classbridge/backend/app/ws/live.py'],encoding='utf-8')
    cls=next(n for n in ast.parse(original).body if isinstance(n,ast.ClassDef) and n.name=='LiveCapture')
    consume=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='consume')
    results={}
    for name,trace in TRACES.items():
        results[name]={'baseline':await replay(trace,False,consume),'experiment':await replay(trace,True,consume)}
    print(json.dumps({'fixture':'synthetic hypothesis replay; virtual clock; 450ms Mock MT; zero paid calls',
        'accuracy':'CER/WER/term accuracy unavailable: no labelled audio','results':results},indent=2))


if __name__=='__main__':asyncio.run(main())
