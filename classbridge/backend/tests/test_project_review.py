import asyncio
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from test_core import factory, client, seed
from app.config import settings
from app.models import AudioAsset, Document, ProcessingTask, Session, SegmentRevision, Chat, Event, now
from app.providers.aliyun import AliyunProvider
from app.services.events import enqueue, save_final, latest_segments
from app.workers.tasks import execute_task
from app.ws.live import LiveCapture


def test_explicit_endpoints_work_without_workspace_and_invalid_config_rejects(client, monkeypatch):
    monkeypatch.setattr(settings, 'dashscope_api_key', 'mock-test-only')
    monkeypatch.setattr(settings, 'dashscope_workspace_id', '')
    for name, value in [('asr_ws_url', 'wss://dashscope.aliyuncs.com/api-ws/v1/inference'),
                        ('openai_base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
                        ('dashscope_base_url', 'https://dashscope.aliyuncs.com/api/v1')]:
        monkeypatch.setattr(settings, name, value)
    assert client.get('/api/settings').json()['real_ready']
    assert client.post('/api/sessions', json={'mode': 'real'}).status_code == 201
    monkeypatch.setattr(settings, 'asr_ws_url', '')
    assert not client.get('/api/settings').json()['real_ready']
    assert client.post('/api/sessions', json={'mode': 'real'}).json()['detail']['code'] == 'missing_workspace'
    monkeypatch.setattr(settings, 'asr_ws_url', 'ws://unsafe.example/asr')
    assert client.post('/api/sessions', json={'mode': 'real'}).json()['detail']['code'] == 'invalid_endpoint'


def test_docker_context_excludes_nested_private_data():
    rules=set((Path(__file__).parents[2]/'.dockerignore').read_text().splitlines())
    assert {'**/data', '**/.env', '**/.env.*', '**/.local', '**/backups', '**/*.db', '**/*.db-*'} <= rules


@pytest.mark.asyncio
@pytest.mark.parametrize('result', [
    {'transcripts': []},
    {'transcripts': [{'sentences': [{'text':'', 'begin_time':0, 'end_time':100}]}]},
    {'transcripts': [{'sentences': [{'text':'new', 'begin_time':100, 'end_time':50}]}]},
])
async def test_invalid_filetrans_never_retires_stable_subtitles(factory, monkeypatch, result):
    monkeypatch.setattr(AliyunProvider, 'submit_filetrans', AsyncMock(return_value='job'))
    monkeypatch.setattr(AliyunProvider, 'poll_filetrans', AsyncMock(return_value=result))
    with factory() as db:
        seed(db, mode='real')
        save_final(db,'lesson','stream','s1',1,'원래 자막',0,1000)
        db.add(AudioAsset(id='audio',session_id='lesson',stream_id='stream',storage_key='audio/test.wav',
            duration_ms=1000,status='ready',expires_at=now()+timedelta(days=1)))
        task=enqueue(db,'alice','reprocess','reprocess-test',{'audio_ids':['audio']},session_id='lesson')
        db.commit();tid=task.id
    await execute_task(tid)
    with factory() as db:
        assert db.get(ProcessingTask,tid).status=='failed'
        assert len(latest_segments(db,'lesson'))==1
        assert latest_segments(db,'lesson')[0].text=='원래 자막'
        assert db.query(SegmentRevision).count()==1


@pytest.mark.asyncio
async def test_filetrans_cannot_overwrite_source_changed_during_cloud_call(factory, monkeypatch):
    monkeypatch.setattr(AliyunProvider, 'submit_filetrans', AsyncMock(return_value='job'))
    async def result(self, job):
        with factory() as other:
            save_final(other,'lesson','stream','s1',2,'人工校正',0,1000,force=True)
        return {'transcripts':[{'sentences':[{'text':'late', 'begin_time':0,'end_time':1000}]}]}
    monkeypatch.setattr(AliyunProvider,'poll_filetrans',result)
    with factory() as db:
        seed(db,mode='real');save_final(db,'lesson','stream','s1',1,'original',0,1000)
        db.add(AudioAsset(id='audio',session_id='lesson',stream_id='stream',storage_key='audio/test.wav',duration_ms=1000,status='ready',expires_at=now()+timedelta(days=1)))
        task=enqueue(db,'alice','reprocess','reprocess-test',{'audio_ids':['audio']},session_id='lesson');db.commit();tid=task.id
    await execute_task(tid)
    with factory() as db:
        assert db.get(ProcessingTask,tid).status=='failed'
        assert latest_segments(db,'lesson')[0].text=='人工校正'
        assert db.query(SegmentRevision).count()==2


@pytest.mark.asyncio
async def test_pending_reprocess_prevents_new_capture(factory):
    with factory() as db:
        seed(db)
        enqueue(db,'alice','reprocess','pending-job',{'audio_ids':[]},session_id='lesson');db.commit()
    socket=AsyncMock();capture=LiveCapture(socket,'lesson','alice')
    await capture.start('new-recording')
    assert capture.task is None
    assert socket.send_json.call_args.args[0]['code']=='post_processing_active'
    assert socket.send_json.call_args.args[0]['request_id']=='new-recording'


def test_attached_document_cannot_be_deleted_while_capture_is_preparing(client, factory):
    with factory() as db:
        row=seed(db);row.status='preparing'
        db.add(Document(id='doc',user_id='alice',session_id='lesson',name='test.pdf',content_type='application/pdf',storage_key='docs/test.pdf'))
        db.commit()
    assert client.delete('/api/documents/doc').status_code==409


@pytest.mark.asyncio
async def test_rag_checks_current_revision_again_after_generation(factory, monkeypatch):
    from app.services.knowledge import answer_question, demo_vector, validate_candidate
    from app.providers.aliyun import ProviderError
    async def embedding(self,texts):return [demo_vector(t) for t in texts]
    async def rerank(self,question,documents,top_n=8):return [(i,1.0) for i in range(len(documents))]
    async def generate(self,*args,**kwargs):
        with factory() as other:save_final(other,'lesson','stream','s1',2,'new evidence',0,1000,force=True)
        return '{"answer":"Old claim [E1]", "evidence_ids":["E1"]}'
    monkeypatch.setattr(AliyunProvider,'embeddings',embedding)
    monkeypatch.setattr(AliyunProvider,'rerank',rerank)
    monkeypatch.setattr(AliyunProvider,'generate',generate)
    with factory() as db:
        seed(db,mode='real');save_final(db,'lesson','stream','s1',1,'original evidence',0,1000)
        with pytest.raises(ProviderError,match='证据已更新'):
            await answer_question(db,'alice','evidence','session','lesson',[],'real')
        assert db.query(Chat).count()==0
        old={'kind':'sentence','session_id':'lesson','sentence_id':'s1','source_revision':1,'quote':'original evidence'}
        assert validate_candidate(db,'alice',old)  # Saved historical citations remain traceable.
        assert not validate_candidate(db,'alice',old,require_current=True)


@pytest.mark.asyncio
async def test_slow_document_parse_does_not_block_audio_event_loop(factory, monkeypatch):
    import threading
    import app.services.knowledge as knowledge
    from app.services.documents import ParsedDocument
    from langchain_core.documents import Document as LangDocument
    from app.services.storage import get_storage
    entered=threading.Event();release=threading.Event()
    def parse(*args):
        entered.set()
        assert release.wait(2), 'Parser blocked the event loop; test coroutine could not release it'
        return ParsedDocument([LangDocument(page_content='evidence',metadata={'page':1,'position':0,'location':'page 1'})],1,[])
    monkeypatch.setattr(knowledge,'parse_document',parse)
    get_storage().put('docs/test.pdf',b'%PDF-test')
    with factory() as db:
        db.add(Document(id='doc',user_id='alice',name='test.pdf',content_type='application/pdf',storage_key='docs/test.pdf'));db.commit()
        running=asyncio.create_task(knowledge.process_document(db,'doc','demo'))
        try:
            for _ in range(100):
                if entered.is_set():break
                await asyncio.sleep(.01)
            assert entered.is_set() and not running.done()
        finally:release.set()
        result=await running
        assert result['status']=='ready'


@pytest.mark.asyncio
async def test_audio_save_failure_still_finishes_session_and_preserves_text(factory, monkeypatch):
    from app.services.storage import LocalStorage
    monkeypatch.setattr(settings,'dashscope_api_key','mock-only')
    async def provider(self,audio,**kwargs):
        await kwargs['on_ready']()
        async for _ in audio:pass
        yield {'sentence_id':'1','text':'보존되는 자막','start_ms':0,'end_ms':20,'final':True}
    monkeypatch.setattr(AliyunProvider,'stream_asr',provider)
    def broken(*args):raise OSError('storage full')
    monkeypatch.setattr(LocalStorage,'put',broken)
    with factory() as db:
        row=seed(db,mode='real');row.retain_audio=True;db.commit()
    capture=LiveCapture(AsyncMock(),'lesson','alice')
    await capture.start('record');await capture.audio(bytes(640));await capture.stop()
    with factory() as db:
        row=db.get(Session,'lesson')
        assert row.status=='stopped' and row.active_stream_id is None
        assert latest_segments(db,row.id)[0].text=='보존되는 자막'
        assert db.query(AudioAsset).one().status=='failed'
        assert db.query(Event).filter_by(type='processing.failed').one().payload['code']=='audio_storage_failed'
        assert capture.audio_path.exists()  # Retained privately until deletion/expiry for recovery.


@pytest.mark.asyncio
async def test_updated_source_marks_old_summary_without_erasing_it(client, factory):
    from app.services.knowledge import summarize
    with factory() as db:
        seed(db);save_final(db,'lesson','stream','s1',1,'old source',0,1000,translation='旧版')
        await summarize(db,'lesson','alice');db.commit()
        save_final(db,'lesson','stream','s1',2,'new source',0,1000,translation='新版')
    detail=client.get('/api/sessions/lesson').json()
    assert detail['stages'][0]['superseded'] is True
    assert '历史阶段' in client.get('/api/sessions/lesson/export?format=txt').text
