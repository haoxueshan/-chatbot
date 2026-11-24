import asyncio
import copy
import pytest
from unittest.mock import AsyncMock
from test_core import factory,client,seed
from app.config import settings
from app.models import ASRProfile,Session,RecognitionStream,SegmentRevision,Translation
from app.services import asr_profiles
from app.providers.asr.factory import create_asr_provider
from app.providers.aliyun import ProviderError
from app.ws.live import LiveCapture


def payload(**changes):
    return {'provider':'soniox','model_id':'stt-rt-v6','display_name':'韩英课堂',
        'language_hints':['ko','en'],'credential_ref':'SONIOX_API_KEY','provider_options':{},**changes}


def test_crud_default_private_validation_and_deletion_history(client,factory,monkeypatch):
    monkeypatch.setattr(settings,'soniox_api_key','mock-only')
    original=client.get('/api/asr/profiles').json()
    assert len(original)==1 and original[0]['provider']=='aliyun' and original[0]['is_default']
    assert client.get('/api/asr/profiles').json()==original
    providers=client.get('/api/asr/providers').json()
    assert {p['id'] for p in providers if p['implemented']}=={'aliyun','soniox'}
    assert all(p['status']=='尚未接入' for p in providers if not p['implemented'])
    response=client.post('/api/asr/profiles',json=payload(is_default=True));assert response.status_code==201,response.text
    profile=response.json();pid=profile['id'];assert profile['validation']['valid']
    assert 'mock-only' not in response.text
    assert sum(p['is_default'] for p in client.get('/api/asr/profiles').json())==1
    assert client.get('/api/settings').json()['default_asr_profile_id']==pid
    assert client.get('/api/settings').json()['aliyun_services_error']['code']=='missing_api_key'
    checked=client.post(f'/api/asr/profiles/{pid}/validate').json()
    assert checked['valid'] and not checked['paid_request']
    changed=client.patch(f'/api/asr/profiles/{pid}',json={'display_name':'新名字','provider_options':{'max_endpoint_delay_ms':1500}})
    assert changed.status_code==200 and changed.json()['display_name']=='新名字'
    session=client.post('/api/sessions',json={'mode':'real','asr_profile_id':pid}).json()
    assert session['asr_snapshot']['provider']=='soniox'
    with factory() as db:
        row=db.get(Session,session['id']);row.status='recording'
        db.add(RecognitionStream(id='history',session_id=row.id,mode='real',asr_snapshot=copy.deepcopy(row.asr_snapshot)))
        db.flush()
        db.add(SegmentRevision(id='historical-source',session_id=row.id,stream_id='history',sentence_id='history:1',source_revision=1,text='보존',start_ms=0,end_ms=100,mode='real'))
        db.flush();db.add(Translation(segment_id='historical-source',source_revision=1,translation_revision=1,text='保留',mode='real'))
        db.commit()
    for method,body in [('PATCH',{'enabled':False,'is_default':False}),('DELETE',None)]:
        assert client.request(method,f'/api/asr/profiles/{pid}',json=body).status_code==409
    assert client.patch(f"/api/sessions/{session['id']}/asr-profile",json={'asr_profile_id':original[0]['id']}).status_code==409
    with factory() as db:db.get(Session,session['id']).status='stopped';db.commit()
    assert client.patch(f'/api/asr/profiles/{pid}',json={'enabled':False,'is_default':False}).status_code==200
    assert client.post('/api/sessions',json={'mode':'real','asr_profile_id':pid}).json()['detail']['code']=='asr_profile_disabled'
    assert client.delete(f'/api/asr/profiles/{pid}').status_code==200
    history=client.get(f"/api/sessions/{session['id']}").json()
    assert history['asr_snapshot']['model_id']=='stt-rt-v6'
    assert history['asr_streams'][0]['snapshot']['model_id']=='stt-rt-v6'
    assert history['segments'][0]['text']=='보존' and history['segments'][0]['translation']=='保留'
    assert len(client.get('/api/asr/profiles').json())==1 # No silent recreation of deleted default.
    with factory() as db:
        other=ASRProfile(user_id='bob',**asr_profiles.validate_data(payload()));db.add(other);db.commit();other_id=other.id
    for method,suffix,body in [('PATCH','',{'display_name':'stolen'}),('DELETE','',None),('POST','/validate',None)]:
        assert client.request(method,f'/api/asr/profiles/{other_id}{suffix}',json=body).status_code==404
    assert client.post('/api/sessions',json={'mode':'real','asr_profile_id':other_id}).status_code==404


@pytest.mark.parametrize('changes',[
    {'credential_ref':'SECRET_KEY'},{'provider_options':{'url':'http://127.0.0.1'}},
    {'provider_options':{'api_key':'must-not-echo'}},{'provider_options':{'max_endpoint_delay_ms':0}},
    {'language_hints':['ko','ko']},{'language_hints':['made-up']},{'capabilities':{'realtime':True}},
    {'provider':'unknown'},{'provider_options':{'terms':['x'*129]}},
    {'api_key':'must-not-echo'},
])
def test_profile_field_whitelist(client,changes):
    response=client.post('/api/asr/profiles',json=payload(**changes))
    assert response.status_code==422
    assert 'must-not-echo' not in response.text


def test_unimplemented_and_missing_credentials_are_not_selectable(client,monkeypatch):
    monkeypatch.setattr(settings,'soniox_api_key','')
    missing=client.post('/api/asr/profiles',json=payload()).json()
    assert missing['validation']['code']=='missing_api_key'
    future=client.post('/api/asr/profiles',json=payload(provider='elevenlabs',credential_ref='ELEVENLABS_API_KEY',model_id='scribe-v3-live')).json()
    assert future['validation']['code']=='unsupported_asr_provider'
    for profile in (missing,future):
        result=client.post('/api/sessions',json={'mode':'real','asr_profile_id':profile['id']})
        assert result.status_code==503 and result.json()['detail']['code']==profile['validation']['code']


def test_validation_paid_requires_confirmation_and_local_never_connects(client,monkeypatch):
    import app.api.asr as api
    monkeypatch.setattr(settings,'soniox_api_key','mock-only')
    pid=client.post('/api/asr/profiles',json=payload()).json()['id']
    calls=[]
    class Provider:
        async def stream_asr(self,audio):
            calls.append(True);frames=[f async for f in audio]
            assert len(frames)==10 and all(len(f)==640 for f in frames)
            if False:yield {}
    monkeypatch.setattr(api,'create_asr_provider',lambda **kwargs:Provider())
    assert not client.post(f'/api/asr/profiles/{pid}/validate').json()['paid_request'] and not calls
    assert client.post(f'/api/asr/profiles/{pid}/validate',json={'live':True}).status_code==422 and not calls
    result=client.post(f'/api/asr/profiles/{pid}/validate',json={'live':True,'confirm_paid':True})
    assert result.json()['code']=='connection_verified' and calls==[True] and not api.paid_checks


def test_factory_profiles_isolate_models_hosts_and_secrets(factory,monkeypatch):
    monkeypatch.setattr(settings,'soniox_api_key','mock-soniox')
    monkeypatch.setattr(settings,'dashscope_api_key','mock-aliyun')
    monkeypatch.setattr(settings,'dashscope_workspace_id','mock-workspace')
    with factory() as db:
        from app.models import User
        user=db.get(User,'alice');p1=ASRProfile(user_id=user.id,**asr_profiles.validate_data(payload()))
        p2=ASRProfile(user_id=user.id,**asr_profiles.validate_data(payload(provider='aliyun',credential_ref='DASHSCOPE_API_KEY',model_id='qwen-model-custom')))
        db.add_all([p1,p2]);db.flush()
        one,two=(asr_profiles.snapshot(p,user) for p in (p1,p2))
        a,b=create_asr_provider(snapshot=one),create_asr_provider(snapshot=two)
        assert a.config.asr_model=='stt-rt-v6' and b.config.asr_model=='qwen-model-custom'
        assert 'mock-soniox' not in str(one) and 'mock-aliyun' not in str(two)
        a.ensure_configured();b.ensure_configured()
        two['runtime']['asr_ws_url']='wss://localhost/api-ws/v1/inference'
        with pytest.raises(ProviderError) as exc:create_asr_provider(snapshot=two).ensure_configured()
        assert exc.value.code=='invalid_endpoint'


@pytest.mark.asyncio
async def test_recording_freezes_profile_and_allows_switch_only_after_stop(factory,monkeypatch):
    from app.models import User
    monkeypatch.setattr(settings,'soniox_api_key','mock-only')
    async def fake_run(self):
        self.dispatch_started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(LiveCapture,'run',fake_run)
    with factory() as db:
        user=db.get(User,'alice');asr_profiles.bootstrap(db,user)
        profile=ASRProfile(user_id=user.id,**asr_profiles.validate_data(payload()))
        db.add(profile);db.flush();pid=profile.id
        row=seed(db,mode='real');row.asr_profile_id=pid;db.commit()
    capture=LiveCapture(AsyncMock(),'lesson','alice')
    try:
        await capture.start('capture-1')
        assert capture.asr_snapshot['model_id']=='stt-rt-v6'
        with factory() as db:
            assert db.get(RecognitionStream,capture.stream_id).asr_snapshot['profile_id']==pid
            with pytest.raises(Exception) as exc:asr_profiles.prevent_in_use(db,'alice',pid)
            assert exc.value.status_code==409
            # Simulated out-of-band DB edit still cannot mutate the captured instance.
            db.get(ASRProfile,pid).model_id='future-model';db.commit()
        assert capture.asr_provider.config.asr_model=='stt-rt-v6'
    finally:
        if capture.task:capture.task.cancel();await asyncio.gather(capture.task,return_exceptions=True)


@pytest.mark.asyncio
async def test_aliyun_adapter_preserves_options_and_closes_inner_generator(monkeypatch):
    from types import SimpleNamespace
    from app.providers.aliyun import AliyunProvider
    from app.providers.asr.aliyun import AliyunASRAdapter
    seen=[];closed=[]
    async def upstream(self,audio,**options):
        seen.append(options)
        try:
            yield {'text':'기존 ASR','final':False}
            await asyncio.Event().wait()
        finally:closed.append(True)
    monkeypatch.setattr(AliyunProvider,'stream_asr',upstream)
    monkeypatch.setattr(AliyunASRAdapter,'ensure_configured',lambda self:None)
    config=SimpleNamespace(asr_options={'context':'교실','vad_model':'far_field_meeting_16k'},asr_language_hints=['ko','en'])
    stream=AliyunASRAdapter(config).stream_asr(None,vocabulary={'RAG':2},context='old',language_hints=['ko'])
    assert (await anext(stream))['text']=='기존 ASR'
    await stream.aclose()
    assert closed==[True] and seen==[{'vocabulary':{'RAG':2},'context':'교실','language_hints':['ko','en'],'vad_model':'far_field_meeting_16k'}]


@pytest.mark.parametrize('status',['preparing','recording','processing'])
def test_busy_model_mutations_and_selection_are_rejected(client,factory,monkeypatch,status):
    monkeypatch.setattr(settings,'soniox_api_key','mock-only')
    profiles=[client.post('/api/asr/profiles',json=payload(model_id=model)).json() for model in ('stt-rt-v6','future-version')]
    session=client.post('/api/sessions',json={'mode':'real','asr_profile_id':profiles[0]['id']}).json()
    with factory() as db:db.get(Session,session['id']).status=status;db.commit()
    assert client.patch(f"/api/sessions/{session['id']}/asr-profile",json={'asr_profile_id':profiles[1]['id']}).status_code==409
    assert client.patch(f"/api/asr/profiles/{profiles[0]['id']}",json={'model_id':'replacement'}).status_code==409
    with factory() as db:db.get(Session,session['id']).status='stopped';db.commit()
    assert client.patch(f"/api/sessions/{session['id']}/asr-profile",json={'asr_profile_id':profiles[1]['id']}).status_code==200


@pytest.mark.asyncio
async def test_two_live_sessions_keep_providers_models_and_sentence_namespaces_separate(factory,monkeypatch):
    from app.providers.aliyun import AliyunProvider
    from app.providers.asr.soniox import SonioxASRAdapter
    monkeypatch.setattr(settings,'soniox_api_key','mock-soniox')
    monkeypatch.setattr(settings,'dashscope_api_key','mock-aliyun')
    monkeypatch.setattr(settings,'dashscope_workspace_id','mock-workspace')
    seen=[]
    async def recognize(self,audio,**kwargs):
        await kwargs['on_ready']()
        count=sum([len(frame) async for frame in audio])
        seen.append((self.config.asr_provider,self.config.asr_model,count))
        yield {'sentence_id':'1','text':self.config.asr_provider+' 교수님 question','start_ms':0,'end_ms':count//32,'final':True}
    monkeypatch.setattr(AliyunProvider,'stream_asr',recognize)
    monkeypatch.setattr(SonioxASRAdapter,'stream_asr',recognize)
    with factory() as db:
        for name,key,model in [('aliyun','DASHSCOPE_API_KEY','qwen-test'),('soniox','SONIOX_API_KEY','stt-rt-v6')]:
            p=ASRProfile(user_id='alice',**asr_profiles.validate_data(payload(provider=name,credential_ref=key,model_id=model)))
            db.add(p);db.flush()
            row=seed(db,mode='real',session_id=name,stream_id=name+'-previous');row.asr_profile_id=p.id;db.commit()
    captures=[LiveCapture(AsyncMock(),name,'alice') for name in ('aliyun','soniox')]
    try:
        for c in captures:
            await c.start(c.session_id)
            async with asyncio.timeout(1):
                while not c.ready:await asyncio.sleep(0)
            await c.audio(bytes(640))
        await asyncio.gather(*(c.stop() for c in captures))
        assert sorted(seen)==[('aliyun','qwen-test',640),('soniox','stt-rt-v6',640)]
        with factory() as db:
            rows=db.query(SegmentRevision).order_by(SegmentRevision.session_id).all()
            assert len(rows)==2 and len({r.sentence_id for r in rows})==2
            for row in rows:
                assert row.text.startswith(row.session_id)
                assert db.get(RecognitionStream,row.stream_id).asr_snapshot['provider']==row.session_id
    finally:
        for c in captures:
            if c.task and not c.task.done():c.task.cancel()
        await asyncio.gather(*(c.task for c in captures if c.task),return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('problem,code',[('disabled','asr_profile_disabled'),('missing','missing_api_key'),('unimplemented','unsupported_asr_provider'),('deleted','asr_profile_not_found')])
async def test_start_revalidates_profile_before_creating_stream(factory,monkeypatch,problem,code):
    monkeypatch.setattr(settings,'soniox_api_key','' if problem=='missing' else 'mock-only')
    with factory() as db:
        p=ASRProfile(user_id='alice',**asr_profiles.validate_data(payload(enabled=problem!='disabled',
            **({'provider':'deepgram','credential_ref':'DEEPGRAM_API_KEY','model_id':'nova-3'} if problem=='unimplemented' else {}))))
        db.add(p);db.flush();row=seed(db,mode='real');row.asr_profile_id=p.id
        if problem=='deleted':db.delete(p)
        db.commit()
    capture=LiveCapture(AsyncMock(),'lesson','alice');await capture.start('attempt')
    assert capture.task is None and not capture.ready
    assert capture.ws.send_json.call_args.args[0]['code']==code
    with factory() as db:
        assert db.query(RecognitionStream).count()==1 # Only the pre-existing fixture stream.
        assert db.get(Session,'lesson').status=='idle'


def test_asr_management_requires_login(client):
    client.post('/api/auth/logout')
    assert client.get('/api/asr/providers').status_code==401
    assert client.get('/api/asr/profiles').status_code==401
    assert client.post('/api/asr/profiles',json=payload()).status_code==401
