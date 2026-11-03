"""Negative upgrade tests: legacy data must never re-enable a removed model path."""
from unittest.mock import AsyncMock
import pytest
from test_core import factory,client,seed
from app.api.settings import Preferences
from app.config import Settings
from app.models import User,Session,SegmentRevision,ProcessingTask,Event,Outbox,Translation
from app.services.events import save_final,enqueue,serialize_segment
from app.services.retired_tasks import cancel_retired_tasks
from app.workers import tasks


def test_new_and_old_settings_ignore_removed_field_without_losing_asr_inputs(client,factory):
    assert 'asr_assist_enabled' not in Preferences.model_fields
    assert 'correction_model' not in Settings.model_fields
    assert 'asr_assist_enabled' not in client.get('/api/settings').json()
    old={'asr_assist_enabled':True,'asr_context':'작업기억 수업','asr_language_mode':'ko_en',
         'terms':['작업기억'],'asr_hotword_weight':4,'speaker_maps':{'lesson':{'0':'Professor'}}}
    with factory() as db:db.get(User,'alice').settings=old;db.commit()
    response=client.get('/api/settings');assert response.status_code==200
    data=response.json()
    assert 'asr_assist_enabled' not in data and 'correction' not in data['models']
    for field in ('asr_context','asr_language_mode','terms','asr_hotword_weight'):assert data[field]==old[field]
    response=client.patch('/api/settings',json={'asr_assist_enabled':True,'theme':'dark'})
    assert response.status_code==200 and 'asr_assist_enabled' not in response.json()
    with factory() as db:
        prefs=db.get(User,'alice').settings
        assert 'asr_assist_enabled' not in prefs
        assert prefs['speaker_maps']==old['speaker_maps'] and prefs['asr_context']==old['asr_context']
        assert prefs['theme']=='dark'


@pytest.mark.parametrize('mode',['real','demo'])
def test_final_never_queues_text_guessing_even_for_legacy_enabled_user(factory,mode):
    with factory() as db:
        seed(db,mode=mode)
        db.get(User,'alice').settings={'asr_assist_enabled':True};db.commit()
        save_final(db,'lesson','stream','sentence',1,'작업 기역을 배웁니다.',0,1000,
                   translation='模拟中文' if mode=='demo' else None)
        assert {t.kind for t in db.query(ProcessingTask)}==({'index_segment'} if mode=='demo' else {'index_segment','translate'})
        assert db.query(Outbox).count()==db.query(ProcessingTask).count()
        assert db.query(SegmentRevision).one().text=='작업 기역을 배웁니다.'
        assert 'suggestion' not in serialize_segment(db,db.query(SegmentRevision).one())


@pytest.mark.asyncio
@pytest.mark.parametrize('status',['pending','retry','running','completed','failed','cancelled'])
async def test_legacy_outbox_delivery_cannot_call_any_model(factory,monkeypatch,status):
    forbidden=AsyncMock(side_effect=AssertionError('removed task must not call models'))
    monkeypatch.setattr('app.providers.aliyun.AliyunProvider.generate',forbidden)
    monkeypatch.setattr('app.providers.aliyun.AliyunProvider.translate_stream',forbidden)
    monkeypatch.setattr('app.services.knowledge.handle_task',forbidden)
    with factory() as db:
        seed(db)
        task=enqueue(db,'alice','suggest_correction','legacy',{'segment_id':'old'},session_id='lesson')
        task.status=status;task.result={'status':'accepted','accepted_revision':2};db.commit();tid=task.id
    await tasks.execute_task(tid);await tasks.execute_task(tid)
    forbidden.assert_not_called()
    with factory() as db:
        t=db.get(ProcessingTask,tid)
        assert t.status==('cancelled' if status in ('pending','retry','running') else status)
        assert t.attempts==0 and t.result=={'status':'accepted','accepted_revision':2}
        assert db.query(Outbox).filter_by(task_id=tid).count()==1
        assert db.query(Event).count()==0


def test_sweep_preserves_other_tasks_and_audit_results(factory):
    with factory() as db:
        seed(db)
        ids=[]
        for kind in ('translate','index_segment','summarize','document','export','reprocess','suggest_correction'):
            ids.append(enqueue(db,'alice',kind,kind,{},session_id='lesson').id)
        db.commit()
        assert cancel_retired_tasks(db)==1;db.commit()
        assert cancel_retired_tasks(db)==0
        assert tasks.pending_task_ids(db)==ids[:-1]
        assert db.query(ProcessingTask).count()==7 and db.query(Outbox).count()==7


def test_removed_routes_and_preserved_versions_audio_route(client,factory):
    with factory() as db:
        seed(db)
        save_final(db,'lesson','stream','sentence',1,'原来版本',0,1000,translation='old')
        save_final(db,'lesson','stream','sentence',2,'已人工确认的历史内容',0,1000,
                   provenance='user_correction',translation='new')
        t=enqueue(db,'alice','suggest_correction','historic',{},session_id='lesson')
        t.status='completed';t.result={'status':'accepted','accepted_revision':2};db.commit();tid=t.id
    for action in ('accept','dismiss'):
        assert client.post(f'/api/sessions/lesson/corrections/{tid}/{action}').status_code==404
    versions=client.get('/api/sessions/lesson/versions/sentence').json()
    assert [s['source_revision'] for s in versions]==[1,2]
    assert versions[1]['provenance']=='user_correction'
    assert versions[1]['text']=='已人工确认的历史内容'
    assert all('suggestion' not in s for s in versions)
    detail=client.get('/api/sessions/lesson').json()
    assert all(t['kind']!='suggest_correction' for t in detail['tasks'])
    # Demo mode still has a real reprocess route, explicitly refusing absent audio.
    assert client.post('/api/sessions/lesson/reprocess').status_code==409
    paths=client.get('/api/openapi.json').json()['paths']
    assert '/api/sessions/{session_id}/reprocess' in paths
    assert not any('/corrections/' in p for p in paths)
