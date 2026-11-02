"""Small explicit paid protocol smoke test, not an accuracy benchmark.

Without --run, only validates local configuration. With --run, each check is
attempted once. No user recordings, private documents, or API keys are logged.
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
os.chdir(ROOT / 'backend')


async def verify(run, output):
    from app.config import settings
    from app.providers.aliyun import AliyunProvider, ProviderError
    provider = AliyunProvider()
    try:
        provider.ensure_configured()
    except ProviderError as exc:
        print(json.dumps({'configured':False,'code':exc.code},ensure_ascii=True))
        return 1
    if not run:
        print('Configuration accepted locally. No API call. Use --run for six small paid checks.')
        return 0
    results=[]
    async def check(name, model, callback):
        try:
            assert await callback(), 'Unexpected response shape'
            item={'check':name,'model':model,'passed':True}
        except Exception as exc:
            item={'check':name,'model':model,'passed':False,'code':getattr(exc,'code',type(exc).__name__)}
        results.append(item)
        print(json.dumps(item,ensure_ascii=True))
    async def asr():
        ready=[]
        async def on_ready():ready.append(True)
        async def audio():
            for _ in range(10):
                yield bytes(640)
                await asyncio.sleep(.02)
        events=[e async for e in provider.stream_asr(audio(),language_hints=['ko','en'],on_ready=on_ready)]
        return ready==[True] and all(isinstance(e.get('text'),str) for e in events)
    async def translation():return bool((await provider.translate('Hello.')).strip())
    async def summary():
        return isinstance(json.loads(await provider.generate('只输出JSON对象：{"topic":"测试"}',model=settings.summary_model,json_mode=True)),dict)
    async def answer():
        data=json.loads(await provider.generate('证据[E1]：水在此例中温度为20摄氏度。问：此例温度多少？只输出JSON {"answer":"20摄氏度 [E1]"}。',json_mode=True))
        return isinstance(data.get('answer'),str) and 'E1' in data['answer']
    async def embedding():
        vectors=await provider.embeddings(['test'])
        return len(vectors)==1 and len(vectors[0])==1024
    async def rerank():return bool(await provider.rerank('water',['water temperature','mountain'],top_n=1))
    for args in [('asr_200ms_silence',settings.asr_model,asr),('translation',settings.translation_model,translation),
                 ('summary_json',settings.summary_model,summary),('answer_json',settings.answer_model,answer),
                 ('embedding',settings.embedding_model,embedding),('rerank',settings.rerank_model,rerank)]:
        await check(*args)
    report={'date_utc':datetime.now(timezone.utc).isoformat(),'attempted_checks':6,'results':results,
            'filetrans':'not_tested_requires_cloud_reachable_private_signed_audio_url',
            'audio_accuracy_verified':False,'note':'Single attempts; real billed endpoints; ASR silence is not speech accuracy.'}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if all(r['passed'] for r in results) else 1


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true',help='Authorize six small real API checks (billable, no automatic retries)')
    parser.add_argument('--output',type=Path,default=ROOT/'test-results'/'model-smoke.json')
    args=parser.parse_args()
    sys.exit(asyncio.run(verify(args.run,args.output.resolve())))
