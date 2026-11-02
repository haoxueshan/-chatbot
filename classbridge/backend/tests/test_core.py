import asyncio
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,event,select
from sqlalchemy.orm import sessionmaker
from app.db import Base,get_db
from app.config import settings
from app.models import User,Session,RecognitionStream,SegmentRevision,Translation,Event,Outbox,ProcessingTask,Document,Chunk,AudioAsset,Chat,Citation
from app.api.auth import hasher
from app.services.events import save_final,save_translation,enqueue
from app.main import app,windows
import app.main as main_module
import app.ws.live as live_module
import app.workers.tasks as task_module

PASSWORD='test-classbridge-2026'
PASSWORD_HASH=hasher.hash(PASSWORD)


@pytest.fixture
def factory(tmp_path,monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'test.db'),connect_args={'check_same_thread':False})
    @event.listens_for(engine,'connect')
    def pragmas(conn,_):conn.execute('PRAGMA foreign_keys=ON');conn.execute('PRAGMA journal_mode=WAL')
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine,expire_on_commit=False)
    with factory() as db:
        db.add_all([User(id='alice',username='alice',password_hash=PASSWORD_HASH),User(id='bob',username='bob',password_hash=PASSWORD_HASH)]);db.commit()
    for module in (main_module,live_module,task_module):monkeypatch.setattr(module,'SessionLocal',factory)
    monkeypatch.setattr(main_module,'init_db',lambda:None)
    monkeypatch.setattr(settings,'task_mode','disabled')
    monkeypatch.setattr(settings,'data_dir',str(tmp_path))
    monkeypatch.setattr(settings,'dashscope_api_key','')
    monkeypatch.setattr(settings,'dashscope_workspace_id','')
    monkeypatch.setattr(settings,'environment','development')
    monkeypatch.setattr(settings,'cookie_secure',False)
    def db_dependency():
        with factory() as db:yield db
    app.dependency_overrides[get_db]=db_dependency
    windows.clear()
    yield factory
    app.dependency_overrides.clear();live_module.connections.clear();engine.dispose()


@pytest.fixture
def client(factory):
    with TestClient(app,headers={'Origin':'http://localhost:5173'}) as client:
        response=client.post('/api/auth/login',json={'username':'alice','password':PASSWORD})
        assert response.status_code==200,response.text
        yield client


def seed(db,mode='demo',owner='alice',session_id='lesson',stream_id='stream'):
    row=Session(id=session_id,user_id=owner,title='课堂',mode=mode,active_stream_id=stream_id)
    db.add(row);db.flush();db.add(RecognitionStream(id=stream_id,session_id=session_id,mode=mode));db.commit();return row


@pytest.mark.parametrize('origin', ['http://localhost', 'http://127.0.0.1'])
def test_port80_login_and_websocket_origin(client, factory, origin):
    response=client.post('/api/auth/login',json={'username':'alice','password':PASSWORD},headers={'Origin':origin})
    assert response.status_code==200
    with factory() as db:seed(db)
    with client.websocket_connect('/ws/sessions/lesson',headers={'Origin':origin}) as ws:
        assert ws.receive_json()['type']=='session.state'


def test_auth_origin_private_and_real_no_fallback(client,factory):
    assert client.get('/api/auth/me').json()['username']=='alice'
    assert 'HttpOnly' in client.post('/api/auth/login',json={'username':'alice','password':PASSWORD}).headers['set-cookie']
    assert client.post('/api/sessions',json={'title':'bad'},headers={'Origin':'https://evil.example'}).status_code==403
    denied=client.post('/api/sessions',json={'mode':'real'})
    assert denied.status_code==503 and denied.json()['detail']['code']=='missing_api_key'
    assert client.get('/api/sessions').json()==[]
    with factory() as db:seed(db,owner='bob',session_id='private')
    assert client.get('/api/sessions/private').status_code==404
    assert client.delete('/api/sessions/private').status_code==404
    assert client.post('/api/auth/logout').status_code==200
    assert client.get('/api/sessions').status_code==401
    assert client.post('/api/auth/register',json={}).status_code==404


def test_websocket_heartbeat_does_not_change_session_or_create_events(client,factory):
    with factory() as db:
        row=seed(db)
        original_status=row.status
    with client.websocket_connect('/ws/sessions/lesson',headers={'Origin':'http://localhost:5173'}) as ws:
        assert ws.receive_json()['recovered'] is True
        ws.send_json({'type':'ping'})
        pong=ws.receive_json()
        assert pong['type']=='connection.pong'
        assert pong['event_seq']==0 and pong['queue_size']==0
        assert 'state' not in pong
        with factory() as db:
            assert db.get(Session,'lesson').status==original_status
            assert db.query(Event).count()==0
            assert db.query(ProcessingTask).count()==0


def test_final_outbox_atomic_rollback_and_idempotence(factory,monkeypatch):
    import app.services.events as events_module
    with factory() as db:
        seed(db)
        original=events_module.enqueue
        def failure(*args,**kwargs):raise RuntimeError('injected database task failure')
        monkeypatch.setattr(events_module,'enqueue',failure)
        with pytest.raises(RuntimeError):save_final(db,'lesson','stream','s1',1,'Evidence',0,1000)
        db.rollback()
        assert db.query(SegmentRevision).count()==db.query(Event).count()==0
        monkeypatch.setattr(events_module,'enqueue',original)
        saved=save_final(db,'lesson','stream','s1',2,'Evidence stable',0,1000,translation='稳定证据')
        assert saved['event_seq']==1
        assert db.query(SegmentRevision).count()==1
        assert db.query(Translation).count()==1
        assert db.query(ProcessingTask).count()==db.query(Outbox).count()==1
        assert save_final(db,'lesson','stream','s1',1,'Late partial',0,1000) is None
        assert save_final(db,'lesson','stream','s1',2,'duplicate',0,1000) is None
        assert db.query(Event).count()==2


def test_new_stream_identity_and_stale_translation(factory):
    with factory() as db:
        row=seed(db)
        save_final(db,'lesson','stream','stream:0',1,'old',0,1000)
        old=db.query(SegmentRevision).one()
        save_final(db,'lesson','stream','stream:0',2,'corrected',0,1000)
        assert save_translation(db,old.id,'late wrong translation') is None
        db.add(RecognitionStream(id='next',session_id='lesson',mode='demo'));row.active_stream_id='next';db.commit()
        assert save_final(db,'lesson','stream','stream:1',1,'old connection',1000,2000) is None
        save_final(db,'lesson','next','next:0',1,'new stream same index',1000,2000,translation='新连接')
        assert len({r.sentence_id for r in db.query(SegmentRevision)})==2


def test_demo_stop_replay_refresh_and_gap(client,factory):
    created=client.post('/api/sessions',json={'title':'模拟课堂','mode':'demo'}).json();sid=created['id']
    final=None;last_seq=0
    with client.websocket_connect(f'/ws/sessions/{sid}',headers={'Origin':'http://localhost:5173'}) as ws:
        ws.send_json({'type':'start'})
        while final is None:
            payload=ws.receive_json()
            if payload['type']=='transcript.final':final=payload;last_seq=payload['event_seq']
        ws.send_json({'type':'stop'})
        while True:
            payload=ws.receive_json()
            if payload['type']=='session.state' and payload.get('state')=='stopped':break
    detail=client.get(f'/api/sessions/{sid}').json()
    assert detail['status']=='stopped' and len(detail['segments'])==1
    assert detail['segments'][0]['translation'] and detail['segments'][0]['mode']=='demo'
    with client.websocket_connect(f'/ws/sessions/{sid}?after_seq={last_seq}',headers={'Origin':'http://localhost:5173'}) as ws:
        seq=[]
        while True:
            payload=ws.receive_json()
            if payload['event_seq']:seq.append(payload['event_seq'])
            if payload['type']=='session.state' and payload['event_seq'] and payload.get('state')=='stopped':break
        assert seq==sorted(set(seq)) and all(x>last_seq for x in seq)
        ws.send_json({'type':'capture.gap','reason':'test disconnected audio'})
        while ws.receive_json()['type']!='capture.gap':pass
    assert client.get(f'/api/sessions/{sid}').json()['gaps']
    assert client.get(f'/api/sessions/{sid}/export?format=md').status_code==200
    assert '模拟演示' in client.get(f'/api/sessions/{sid}/export?format=txt').text
    assert client.get(f'/api/sessions/{sid}/export?format=pdf').content.startswith(b'%PDF')


def test_websocket_origin_and_anonymous_rejected(client,caplog):
    sid=client.post('/api/sessions',json={}).json()['id']
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(f'/ws/sessions/{sid}',headers={'Origin':'https://evil.example'}):pass
    assert error.value.code==4403
    assert 'code=origin_forbidden' in caplog.text
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect('/ws/sessions/missing',headers={'Origin':'http://localhost:5173'}):pass
    assert error.value.code==4404
    assert 'code=session_not_accessible' in caplog.text
    client.post('/api/auth/logout')
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(f'/ws/sessions/{sid}',headers={'Origin':'http://localhost:5173'}):pass
    assert error.value.code==4401
    assert 'code=authentication_required' in caplog.text


def test_vpn_websocket_requires_exact_origin(client,factory,monkeypatch):
    from starlette.websockets import WebSocketDisconnect
    with factory() as db:seed(db)
    allowed=settings.allowed_origins
    monkeypatch.setattr(settings,'allowed_origins',allowed+',http://100.64.0.10:*')
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect('/ws/sessions/lesson',headers={'Origin':'http://100.64.0.10'}):pass
    assert error.value.code==4403
    monkeypatch.setattr(settings,'allowed_origins',allowed+',http://100.64.0.10')
    with client.websocket_connect('/ws/sessions/lesson',headers={'Origin':'http://100.64.0.10'}) as ws:
        assert ws.receive_json()['type']=='session.state'


def test_clear_keeps_document_chunks_and_deletes_derived(client,factory):
    with factory() as db:
        row=seed(db)
        save_final(db,'lesson','stream','s1',1,'Caption',0,1000,translation='字幕')
        document=Document(id='doc',user_id='alice',session_id=row.id,name='ref.pdf',content_type='application/pdf',storage_key='docs/ref.pdf',status='ready');db.add(document);db.flush()
        db.add(Chunk(id='docchunk',user_id='alice',session_id=row.id,document_id=document.id,text='document evidence'))
        db.add(Chunk(user_id='alice',session_id=row.id,sentence_id='s1',text='caption evidence'))
        chat=Chat(id='historychat',user_id='alice',question='?',answer='caption derived',mode='demo',scope='history');db.add(chat);db.flush()
        db.add(Citation(chat_id=chat.id,session_id=row.id,sentence_id='s1',source_revision=1,kind='sentence',quote='Caption'))
        row.status='recording';db.commit()
    assert client.delete('/api/sessions/lesson/segments').status_code==409
    with factory() as db:db.get(Session,'lesson').status='stopped';db.commit()
    assert client.delete('/api/sessions/lesson/segments').status_code==200
    with factory() as db:
        assert db.query(SegmentRevision).count()==db.query(ProcessingTask).count()==db.query(Outbox).count()==0
        assert db.get(Chunk,'docchunk') and db.get(Document,'doc')
        assert db.get(Chat,'historychat') is None


@pytest.mark.asyncio
async def test_worker_idempotent_local_embedding(factory):
    with factory() as db:
        seed(db);save_final(db,'lesson','stream','s1',1,'Evidence retrieval',0,1000,translation='证据检索')
        task=db.query(ProcessingTask).one();tid=task.id
    await task_module.execute_task(tid);await task_module.execute_task(tid)
    with factory() as db:
        assert db.get(ProcessingTask,tid).status=='completed'
        assert db.get(ProcessingTask,tid).attempts==1
        assert db.query(Chunk).count()==1


@pytest.mark.asyncio
async def test_filetrans_split_merge_retirement_and_retry_idempotency(factory,monkeypatch):
    from app.providers.aliyun import AliyunProvider
    from app.services.events import latest_segments
    from app.services.knowledge import latest_segments as rag_latest
    monkeypatch.setattr(AliyunProvider,'submit_filetrans',AsyncMock(return_value='split-merge'))
    monkeypatch.setattr(AliyunProvider,'poll_filetrans',AsyncMock(return_value={'transcripts':[{'sentences':[
        {'begin_time':0,'end_time':500,'text':'split A'},
        {'begin_time':500,'end_time':1000,'text':'split B'},
        {'begin_time':1000,'end_time':3000,'text':'merged C'}]}]}))
    with factory() as db:
        seed(db,mode='real')
        for i in range(3):save_final(db,'lesson','stream',f's{i}',1,f'old {i}',i*1000,(i+1)*1000)
        db.add(AudioAsset(id='audio',session_id='lesson',stream_id='stream',storage_key='audio/test.wav',offset_ms=0,duration_ms=3000,status='ready',expires_at=datetime.now(timezone.utc)+timedelta(days=1)))
        task=enqueue(db,'alice','reprocess','split-merge-test',{'audio_ids':['audio']},session_id='lesson');db.commit();tid=task.id
    await task_module.execute_task(tid)
    await task_module.execute_task(tid)
    with factory() as db:
        assert [r.text for r in latest_segments(db,'lesson')]==['split A','split B','merged C']
        assert [r.text for r in rag_latest(db,'lesson')]==['split A','split B','merged C']
        assert db.query(SegmentRevision).filter_by(status='retired').count()==1
        assert db.query(SegmentRevision).filter_by(source_revision=1,provenance='realtime').count()==3
        assert db.get(ProcessingTask,tid).attempts==1


@pytest.mark.asyncio
async def test_final_translation_streams_before_completion_and_tracks_latency(factory,monkeypatch):
    from app.providers.aliyun import AliyunProvider
    async def translate(*args,**kwargs):
        yield '实时'
        await asyncio.sleep(.16)
        yield '中文'
    monkeypatch.setattr(AliyunProvider,'translate_stream',translate)
    with factory() as db:
        seed(db,mode='real');save_final(db,'lesson','stream','s1',1,'Evidence',0,1000,latency={'source_final_ms':120})
        tid=db.query(ProcessingTask).filter_by(kind='translate').one().id
    await task_module.execute_task(tid)
    with factory() as db:
        partials=db.query(Event).filter_by(type='translation.partial').all()
        final=db.query(Event).filter_by(type='translation.final').one().payload
        assert partials[0].payload['translation']=='实时'
        assert partials[0].payload['source_status']=='final'
        assert final['translation']=='实时中文'
        assert final['latency']['translation_final_ms']>=final['latency']['translation_first_ms']>=120


@pytest.mark.asyncio
async def test_saved_audio_is_valid_pcm_wave(factory,monkeypatch):
    import io,wave
    from app.providers.aliyun import AliyunProvider
    from app.services.storage import get_storage
    monkeypatch.setattr(settings,'dashscope_api_key','unit-test-mocked-provider')
    async def mock_asr(self,audio,**kwargs):
        assert kwargs['vocabulary']=={'working memory':4}
        assert kwargs['context']=='인지심리학 수업. 작업기억.'
        assert kwargs['language_hints']==['ko','en']
        assert kwargs['vad_model']=='near_meeting_16k'
        await kwargs['on_ready']()
        count=0
        async for frame in audio:count+=len(frame)
        if count:yield {'sentence_id':'0','text':'실제 테스트','start_ms':0,'end_ms':count//32,'final':True}
    monkeypatch.setattr(AliyunProvider,'stream_asr',mock_asr)
    class Socket:
        async def send_json(self,payload):pass
    with factory() as db:
        db.get(User,'alice').settings={'terms':[{'source':'working memory','target':'工作记忆'}],'asr_language_mode':'ko_en',
            'asr_hotword_weight':4,'asr_context':'인지심리학 수업. 작업기억.', 'asr_acoustic_profile':'near'}
        db.get(User,'bob').settings={'terms':['private-other-owner'],'asr_language_mode':'ko','asr_context':'private-context'}
        row=seed(db,mode='real');row.retain_audio=True;db.commit()
    capture=live_module.LiveCapture(Socket(),'lesson','alice')
    await capture.start()
    for _ in range(5):await capture.audio(bytes(640))
    await capture.stop()
    with factory() as db:
        audio=db.query(AudioAsset).one()
        assert audio.status=='ready' and audio.duration_ms==100
        ready_event=next(e for e in db.query(Event).filter_by(type='session.state') if e.payload.get('ready'))
        assert ready_event.payload['asr_language_mode']=='ko_en'
        assert ready_event.payload['asr_acoustic_profile']=='near'
        assert ready_event.payload['asr_enhancement']=={'hotword_count':1,'weight':4,'context_chars':len('인지심리학 수업. 작업기억.')}
        assert '인지심리학' not in str(ready_event.payload)  # Events expose counts, not private context.
        with wave.open(io.BytesIO(get_storage().read(audio.storage_key)),'rb') as wav:
            assert (wav.getnchannels(),wav.getsampwidth(),wav.getframerate(),wav.getnframes())==(1,2,16000,1600)


@pytest.mark.asyncio
async def test_slow_asr_preparation_has_no_audio_queue_or_capture_time(factory,monkeypatch):
    from app.providers.aliyun import AliyunProvider
    release=asyncio.Event();ready=asyncio.Event();received=[]
    monkeypatch.setattr(settings,'dashscope_api_key','mock-only')
    async def delayed(self,audio,**kwargs):
        await release.wait()
        await kwargs['on_ready']();ready.set()
        async for frame in audio:received.append(frame)
        if False:yield {}
    monkeypatch.setattr(AliyunProvider,'stream_asr',delayed)
    class Socket:
        async def send_json(self,payload):pass
    with factory() as db:
        row=seed(db,mode='real');row.retain_audio=True;db.commit()
    capture=live_module.LiveCapture(Socket(),'lesson','alice')
    await capture.start('request-slow')
    # Exceed the previous two-second audio-queue ceiling while still preparing.
    await asyncio.sleep(2.05)
    assert capture.queue.empty() and capture.started==0 and not capture.ready
    with factory() as db:
        assert db.get(Session,'lesson').status=='preparing'
        assert db.query(AudioAsset).count()==0
        assert not db.query(Event).filter_by(type='processing.failed').first()
    release.set();await asyncio.wait_for(ready.wait(),1)
    with factory() as db:
        event=db.query(Event).filter_by(type='session.state').order_by(Event.event_seq.desc()).first().payload
        assert event['ready'] and event['request_id']=='request-slow' and event['captured_ms']==0
    await capture.audio(bytes(640));await capture.stop()
    assert len(received)==1
    with factory() as db:
        assert db.get(Session,'lesson').duration_ms<1000
        assert db.query(AudioAsset).one().duration_ms==20


@pytest.mark.asyncio
async def test_cancel_preparing_releases_task_without_audio_or_summary(factory,monkeypatch):
    from app.providers.aliyun import AliyunProvider
    monkeypatch.setattr(settings,'dashscope_api_key','mock-only')
    cancelled=asyncio.Event();readiness=[]
    async def preparing(self,audio,**kwargs):
        try:
            await asyncio.Event().wait()
            readiness.append(True);await kwargs['on_ready']()
        finally:cancelled.set()
        if False:yield {}
    monkeypatch.setattr(AliyunProvider,'stream_asr',preparing)
    class Socket:
        async def send_json(self,payload):pass
    with factory() as db:seed(db,mode='real')
    capture=live_module.LiveCapture(Socket(),'lesson','alice')
    await capture.start('cancelled-request');await capture.stop()
    assert cancelled.is_set() and not readiness and capture.task.done()
    with factory() as db:
        assert db.get(Session,'lesson').status=='stopped'
        assert db.get(Session,'lesson').duration_ms==0
        assert db.query(AudioAsset).count()==db.query(ProcessingTask).count()==0


@pytest.mark.asyncio
async def test_long_pause_preserves_evidence_offsets_without_spending_capture_limit(factory,monkeypatch):
    from app.providers.aliyun import AliyunProvider
    from app.api.sessions import session_dict
    monkeypatch.setattr(settings,'dashscope_api_key','mock-only')
    received=[]
    async def provider(self,audio,**kwargs):
        await kwargs['on_ready']()
        async for frame in audio:received.append(frame)
        if False:yield {}
    monkeypatch.setattr(AliyunProvider,'stream_asr',provider)
    class Socket:
        async def send_json(self,payload):pass
    with factory() as db:
        row=seed(db,mode='real');row.duration_ms=1000
        stream=db.get(RecognitionStream,'stream');stream.ended_ms=1000;stream.status='stopped'
        stream.created_at=datetime.now(timezone.utc)-timedelta(hours=2);db.commit()
    capture=live_module.LiveCapture(Socket(),'lesson','alice')
    await capture.start('after-pause')
    assert capture.ready and capture.offset>7_000_000 and capture.captured_before==1000
    await capture.audio(bytes(640));await capture.stop()
    assert len(received)==1
    with factory() as db:
        result=session_dict(db,db.get(Session,'lesson'))
        assert result['duration_ms']>7_000_000 and 1000<=result['captured_ms']<2000
        assert db.query(Event).filter_by(type='capture.gap').one().payload['duration_ms']>7_000_000
        assert not db.query(Event).filter_by(type='processing.failed').first()


@pytest.mark.asyncio
async def test_packet_burst_does_not_starve_healthy_upstream_sender(factory,monkeypatch):
    from app.providers.aliyun import AliyunProvider
    monkeypatch.setattr(settings,'dashscope_api_key','mock-only')
    sent=[]
    async def provider(self,audio,**kwargs):
        await kwargs['on_ready']()
        async for frame in audio:
            sent.append(frame)
            await asyncio.sleep(0)
        if False:yield {}
    monkeypatch.setattr(AliyunProvider,'stream_asr',provider)
    class Socket:
        async def send_json(self,payload):pass
    with factory() as db:seed(db,mode='real')
    capture=live_module.LiveCapture(Socket(),'lesson','alice')
    await capture.start('packet-burst')
    for _ in range(500):await capture.audio(bytes(640))
    await capture.stop()
    assert len(sent)==500
    with factory() as db:assert not db.query(Event).filter_by(type='processing.failed').first()


@pytest.mark.asyncio
async def test_cleanup_failure_cannot_overwrite_original_backlog_and_logs_no_audio(factory,caplog):
    class Socket:
        async def send_json(self,payload):pass
    with factory() as db:seed(db,mode='real')
    capture=live_module.LiveCapture(Socket(),'lesson','alice')
    capture.stream_id='stream';capture.asr_metrics={'sent_audio_ms':2000,'send_wait_ms':12}
    await capture.fail('audio_backlog','音频转发积压超过2秒')
    await capture.fail('upstream_disconnected','late cleanup failure')
    with factory() as db:
        error=db.query(Event).filter_by(type='processing.failed').one().payload
        assert error['code']=='audio_backlog' and error['diagnostics']['sent_audio_ms']==2000
    assert 'capture_failed' in caplog.text and 'late cleanup failure' not in caplog.text


def test_background_export_is_private_downloadable_and_deleted_with_session(client,factory):
    from app.services.storage import get_storage
    with factory() as db:
        seed(db);save_final(db,'lesson','stream','s1',1,'Export evidence',0,1000,translation='导出证据')
    response=client.post('/api/sessions/lesson/exports',json={'format':'pdf'})
    assert response.status_code==202
    tid=response.json()['task_id'];asyncio.run(task_module.execute_task(tid))
    state=client.get(f'/api/sessions/lesson/exports/{tid}').json()
    assert state['status']=='completed'
    assert client.get(state['download_url']).content.startswith(b'%PDF')
    with factory() as db:key=db.get(ProcessingTask,tid).result['storage_key']
    assert client.delete('/api/sessions/lesson').status_code==200
    with pytest.raises(FileNotFoundError):get_storage().read(key)
    assert client.get(state['download_url']).status_code==404


def test_preferences_preserve_manual_speaker_names(client,factory):
    with factory() as db:seed(db)
    assert client.patch('/api/sessions/lesson/speakers',json={'mapping':{'0':'Professor'}}).status_code==200
    assert client.patch('/api/settings',json={'theme':'dark'}).status_code==200
    assert client.get('/api/sessions/lesson').json()['speaker_names']=={'0':'Professor'}


def test_asr_language_settings_validate_and_partial_updates_preserve_other_preferences(client,factory):
    assert client.get('/api/settings').json()['asr_language_mode']=='auto'
    with factory() as db:
        db.get(User,'alice').settings={'theme':'dark','terms':['인지 부하'],'show_original':True}
        db.get(User,'bob').settings={'asr_language_mode':'ko'}
        db.commit()
    result=client.patch('/api/settings',json={'asr_language_mode':'ko_en'})
    assert result.status_code==200
    assert result.json()['asr_language_mode']=='ko_en'
    assert result.json()['theme']=='dark' and result.json()['terms']==['인지 부하']
    assert client.patch('/api/settings',json={'theme':'light'}).json()['asr_language_mode']=='ko_en'
    assert client.patch('/api/settings',json={'asr_language_mode':'made-up-language'}).status_code==422
    assert client.patch('/api/settings',json={'asr_acoustic_profile':'unknown'}).status_code==422
    assert client.patch('/api/settings',json={'audio_processing_mode':'enhance'}).status_code==422
    assert client.patch('/api/settings',json={'asr_acoustic_profile':'near','audio_processing_mode':'natural'}).json()['asr_acoustic_profile']=='near'
    with factory() as db:assert db.get(User,'bob').settings['asr_language_mode']=='ko'
    assert client.patch('/api/settings',json={'asr_language_mode':'auto'}).json()['asr_language_mode']=='auto'


def test_asr_context_and_weights_validate_and_report_ignored_terms(client):
    defaults=client.get('/api/settings').json()
    assert defaults['asr_context']=='' and defaults['asr_hotword_weight']==2
    assert defaults['asr_terms_status']=={'enabled_count':0,'skipped':[]}
    result=client.patch('/api/settings',json={'asr_context':'인지심리학. 작업기억.', 'asr_hotword_weight':4,
        'terms':['작업기억','가'*16]}).json()
    assert result['asr_terms_status']['enabled_count']==1
    assert result['asr_terms_status']['skipped'][0]['index']==1
    assert result['terms']==['작업기억','가'*16]  # Preserve original glossary for translation/editing.
    assert client.patch('/api/settings',json={'asr_context':'가'*401}).status_code==422
    assert client.patch('/api/settings',json={'asr_hotword_weight':50}).status_code==422
    saved=client.get('/api/settings').json()
    assert saved['asr_context']=='인지심리학. 작업기억.' and saved['asr_hotword_weight']==4


@pytest.mark.asyncio
async def test_finite_paid_retries(factory,monkeypatch):
    from app.providers.aliyun import AliyunProvider,ProviderError
    calls=[]
    async def failed_translate(*args,**kwargs):
        calls.append(1);raise ProviderError('timeout','timed out',True)
        yield ''
    monkeypatch.setattr(AliyunProvider,'translate_stream',failed_translate)
    with factory() as db:
        seed(db,mode='real');save_final(db,'lesson','stream','s1',1,'Real evidence',0,1000)
        tid=db.query(ProcessingTask).filter_by(kind='translate').one().id
    for _ in range(5):await task_module.execute_task(tid)
    with factory() as db:
        assert db.get(ProcessingTask,tid).status=='failed' and db.get(ProcessingTask,tid).attempts==3
        assert db.query(Translation).count()==0
    assert len(calls)==3


@pytest.mark.asyncio
async def test_filetrans_keeps_old_version_and_offset(factory,monkeypatch):
    from app.providers.aliyun import AliyunProvider
    from app.services.storage import get_storage
    monkeypatch.setattr(AliyunProvider,'submit_filetrans',AsyncMock(return_value='cloud-task'))
    monkeypatch.setattr(AliyunProvider,'poll_filetrans',AsyncMock(return_value={'transcripts':[{'sentences':[{'begin_time':0,'end_time':1000,'text':'Corrected evidence','speaker_id':0}]}]}))
    with factory() as db:
        row=seed(db,mode='real');row.active_stream_id=None;db.commit()
        save_final(db,'lesson','stream','s1',1,'Original evidence',5000,6000,force=True)
        asset=AudioAsset(id='audio',session_id='lesson',stream_id='stream',storage_key='audio/test.wav',offset_ms=5000,duration_ms=1000,status='ready',expires_at=datetime.now(timezone.utc)+timedelta(days=1));db.add(asset);db.commit()
        get_storage().put(asset.storage_key,b'RIFF-test')
        task=enqueue(db,'alice','reprocess','test-reprocess',{'session_id':'lesson','user_id':'alice','audio_ids':['audio']},session_id='lesson');db.commit();tid=task.id
    await task_module.execute_task(tid)
    with factory() as db:
        rows=db.query(SegmentRevision).order_by(SegmentRevision.source_revision).all()
        assert len(rows)==2 and rows[0].text=='Original evidence'
        assert rows[1].source_revision==2 and rows[1].start_ms==5000 and rows[1].speaker=='0'
        assert db.get(ProcessingTask,tid).payload['remote_jobs']['audio']=='cloud-task'
        assert db.get(ProcessingTask,tid).status=='completed'


@pytest.mark.asyncio
async def test_capture_health_reports_actual_audio_and_does_not_store_content(factory,monkeypatch):
    import math,struct,time
    monkeypatch.setattr(settings,'dashscope_api_key','mock-only')
    capture=live_module.LiveCapture(AsyncMock(),'lesson','alice')
    capture.mode='real';capture.ready=True;capture.started=time.monotonic()
    capture.task=asyncio.create_task(asyncio.sleep(30))
    try:
        frame=struct.pack('<320h',*[int(3000*math.sin(i*.2)) for i in range(320)])
        await capture.audio(frame)
        capture.asr_metrics.update(sent_audio_ms=20,last_transcript_monotonic=time.monotonic(),transcript_events=1)
        health=capture.diagnostics()
        assert health['received_audio_ms']==20
        assert health['sent_audio_ms']==20
        assert health['last_audio_age_ms']<1000
        assert -30<health['input_dbfs']<-20
        assert health['transcript_events']==1
        assert all(v is None or isinstance(v,(int,float)) for v in health.values())
        capture.last_audio_at=None
        assert capture.diagnostics()['last_audio_age_ms'] is None
    finally:
        capture.task.cancel()
        await asyncio.gather(capture.task,return_exceptions=True)
