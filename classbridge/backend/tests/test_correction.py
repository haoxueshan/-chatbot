import json
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from test_core import factory,client,seed
from app.models import User,Session,SegmentRevision,ProcessingTask,Event,Outbox,Chunk
from app.services.events import save_final,latest_segments
from app.services.correction import validate_edits
from app.providers.aliyun import AliyunProvider,ProviderError
from app.workers.tasks import execute_task

ORIGINAL='오늘은 작업 기역을 배웁니다.'
CORRECTED='오늘은 작업기억을 배웁니다.'


def edit(**kw):
    return {'before':'작업 기역','after':'작업기억','kind':'term','reason':'课程术语与近音形式相符，需核对音频。',
        'evidence_ids':['source','term:0'],**kw}


def prepare(factory):
    with factory() as db:
        seed(db,mode='real')
        save_final(db,'lesson','stream','previous',1,'작업기억은 정보를 잠시 유지합니다.',0,1000)
        db.get(User,'alice').settings={'asr_assist_enabled':True,'terms':['작업기억'],'asr_context':'인지심리학'}
        db.get(User,'bob').settings={'terms':['PRIVATE_OTHER'],'asr_context':'PRIVATE_OTHER'}
        db.commit()
        save_final(db,'lesson','stream','target',1,ORIGINAL,1500,3000)
        task=db.query(ProcessingTask).filter_by(kind='suggest_correction').one()
        assert db.query(Outbox).filter_by(task_id=task.id).count()==1
        assert task.max_attempts==1
        return task.id,task.payload['segment_id']


def install(monkeypatch):
    async def generate(self,prompt,**kwargs):
        assert kwargs['json_mode'] and '没有听到音频' in kwargs['system']
        assert 'PRIVATE_OTHER' not in prompt
        assert json.loads(prompt)['evidence'][1]['sentence_id']=='previous'
        return json.dumps({'edits':[edit(evidence_ids=['source','previous:0','term:0'])]})
    monkeypatch.setattr(AliyunProvider,'generate',generate)


@pytest.mark.asyncio
async def test_suggestion_is_durable_but_never_replaces_source_or_enters_rag(factory,client,monkeypatch):
    tid,sid=prepare(factory);install(monkeypatch)
    await execute_task(tid)
    with factory() as db:
        task=db.get(ProcessingTask,tid)
        assert task.result['suggested_text']==CORRECTED and task.status=='completed'
        assert db.get(SegmentRevision,sid).text==ORIGINAL
        assert db.query(SegmentRevision).filter_by(sentence_id='target').count()==1
        assert not db.query(Chunk).filter(Chunk.text==CORRECTED).first()
        event=db.query(Event).filter_by(type='segment.suggestion').one().payload
        assert event['suggestion']['audio_verified'] is False
        assert event['source_revision']==1
    row=next(s for s in client.get('/api/sessions/lesson').json()['segments'] if s['sentence_id']=='target')
    assert row['text']==ORIGINAL and row['suggestion']['task_id']==tid


@pytest.mark.asyncio
async def test_accept_creates_new_version_and_rebuilds_with_old_sources_preserved(factory,client,monkeypatch):
    tid,sid=prepare(factory);install(monkeypatch);await execute_task(tid)
    url=f'/api/sessions/lesson/corrections/{tid}/accept'
    with factory() as db:db.get(Session,'lesson').status='recording';db.commit()
    assert client.post(url).status_code==409
    with factory() as db:db.get(Session,'lesson').status='stopped';db.commit()
    assert client.post(url).json()=={'status':'accepted','source_revision':2}
    assert client.post(url).status_code==200
    with factory() as db:
        rows=db.query(SegmentRevision).filter_by(sentence_id='target').order_by(SegmentRevision.source_revision).all()
        assert [r.text for r in rows]==[ORIGINAL,CORRECTED]
        assert rows[-1].provenance=='user_correction'
        assert db.query(ProcessingTask).filter_by(kind='suggest_correction').count()==1
        assert db.query(ProcessingTask).filter_by(idempotency_key=f'translate:{rows[-1].id}').count()==1
        assert db.query(ProcessingTask).filter_by(idempotency_key=f'index:{rows[-1].id}').count()==1
        assert db.query(ProcessingTask).filter_by(idempotency_key=f'summary:correction:{rows[-1].id}').count()==1


@pytest.mark.asyncio
async def test_permission_stale_version_and_dismissal(factory,client,monkeypatch):
    tid,sid=prepare(factory);install(monkeypatch);await execute_task(tid)
    with factory() as db:seed(db,owner='bob',session_id='other',stream_id='other-stream')
    assert client.post(f'/api/sessions/other/corrections/{tid}/accept').status_code==404
    assert client.post(f'/api/sessions/lesson/corrections/{tid}/dismiss').status_code==200
    assert client.post(f'/api/sessions/lesson/corrections/{tid}/accept').status_code==409
    with factory() as db:
        assert db.get(SegmentRevision,sid).text==ORIGINAL
        task=db.get(ProcessingTask,tid);task.result={**task.result,'status':'suggested'};db.commit()
        save_final(db,'lesson','stream','target',2,'새 원문입니다.',1500,3000)
    assert client.post(f'/api/sessions/lesson/corrections/{tid}/accept').status_code==409


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['revision','delete','disable'])
async def test_late_model_response_cannot_restore_old_or_deleted_data(factory,monkeypatch,change):
    tid,sid=prepare(factory)
    async def generate(*args,**kwargs):
        with factory() as db:
            if change=='revision':save_final(db,'lesson','stream','target',2,'새 원문입니다.',1500,3000)
            elif change=='delete':db.delete(db.get(Session,'lesson'));db.commit()
            else:db.get(User,'alice').settings={'asr_assist_enabled':False};db.commit()
        return json.dumps({'edits':[edit()]})
    monkeypatch.setattr(AliyunProvider,'generate',generate)
    await execute_task(tid)
    with factory() as db:
        assert db.query(Event).filter_by(type='segment.suggestion').count()==0
        if change=='delete':assert db.get(ProcessingTask,tid) is None


def test_rate_limit_demo_isolation_and_source_bound_outbox(factory):
    tid,sid=prepare(factory)
    with factory() as db:
        save_final(db,'lesson','stream','another',1,'추가 문장입니다.',3100,4000)
        assert db.query(ProcessingTask).filter_by(kind='suggest_correction').count()==1
        task=db.get(ProcessingTask,tid);task.created_at-=timedelta(seconds=16);db.commit()
        save_final(db,'lesson','stream','later',1,'다음 문장입니다.',4200,5000)
        assert db.query(ProcessingTask).filter_by(kind='suggest_correction').count()==2
        seed(db,session_id='demo',stream_id='demo-stream')
        save_final(db,'demo','demo-stream','demo:1',1,'모의 예제입니다.',0,1000)
        assert not db.query(ProcessingTask).filter_by(session_id='demo',kind='suggest_correction').first()


@pytest.mark.asyncio
async def test_paid_suggestion_is_single_attempt_on_timeout(factory,monkeypatch):
    tid,_=prepare(factory)
    mock=AsyncMock(side_effect=ProviderError('timeout','超时',True))
    monkeypatch.setattr(AliyunProvider,'generate',mock)
    await execute_task(tid);await execute_task(tid)
    assert mock.await_count==1
    with factory() as db:
        assert db.get(ProcessingTask,tid).status=='failed'
        assert db.query(Event).filter_by(type='processing.failed').one().payload['task_kind']=='suggest_correction'


def test_validator_rejects_invented_evidence_numbers_wholesale_changes_and_ambiguous_spans():
    evidence=[{'id':'source','kind':'source','quote':ORIGINAL},{'id':'term:0','kind':'term','quote':'작업기억'}]
    assert validate_edits(ORIGINAL,{'edits':[edit()]},evidence)['suggested_text']==CORRECTED
    assert validate_edits(ORIGINAL,{'edits':[edit(evidence_ids=['missing'])]},evidence) is None
    assert validate_edits(ORIGINAL,{'edits':[edit(after='인공지능')]},evidence) is None
    assert validate_edits(ORIGINAL+ORIGINAL,{'edits':[edit()]},evidence) is None
    assert validate_edits('수량은 10개',{'edits':[edit(before='10개',after='20개',kind='grammar',evidence_ids=['source'])]},evidence) is None
    assert validate_edits('저는 안 합니다.',{'edits':[edit(before='안 합니다',after='합니다',kind='grammar',evidence_ids=['source'])]},evidence) is None
    assert validate_edits(ORIGINAL,{'edits':[]},evidence) is None
