import json
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
import pytest
from app.services.asr_config_resolver import resolve_effective_asr_config
from app.providers.asr.factory import create_asr_provider


def config():
    return SimpleNamespace(asr_provider='aliyun',asr_model='qwen-audio-3.1-asr-flash-streaming',
        dashscope_api_key='DO-NOT-PERSIST',aliyun_asr_batch_enabled=True,aliyun_asr_batch_ms=100,
        asr_send_timeout_seconds=5,model_timeout_seconds=30)


@pytest.mark.parametrize('mode,hints,expected', [('ko_en',None,['ko','en']),('ko_en',[],[]),
    ('ko_en',['ko'],['ko']),('auto',['ko','en'],['ko','en'])])
def test_language_precedence(mode,hints,expected):
    value=resolve_effective_asr_config(config(),{'language_hints':hints},{'asr_language_mode':mode})
    assert value.arguments()['language_hints']==expected
    assert value.public_snapshot()['language_hints']==expected
    assert value.language_hints_source==('user' if hints is None else 'model')


@pytest.mark.parametrize('context', ['', 'model context'])
def test_explicit_options_and_immutable_snapshot(context):
    server=config();preferences={'asr_context':'global','asr_acoustic_profile':'near','terms':['RAG','RAG']}
    snapshot={'provider':'aliyun','model_id':server.asr_model,'credential_ref':'DASHSCOPE_API_KEY',
        'language_hints':['ko'],'provider_options':{'context':context,'vad_model':'far_field_meeting_16k'}}
    value=resolve_effective_asr_config(server,snapshot,preferences)
    adapter=create_asr_provider(server,snapshot=snapshot,effective=value)
    preferences['asr_context']='changed';snapshot['language_hints'].append('en');server.asr_send_timeout_seconds=99
    assert value.context==context and value.language_hints==('ko',)
    assert value.vad_model=='far_field_meeting_16k' and value.vad_model_source=='model'
    assert value.public_snapshot()['context_chars']==len(context)
    assert value.public_snapshot()['vocabulary_count']==1
    assert adapter.config.asr_send_timeout_seconds==value.send_timeout_seconds==5
    assert adapter.config.asr_language_hints==['ko']
    assert 'DO-NOT-PERSIST' not in json.dumps(value.public_snapshot())
    with pytest.raises(FrozenInstanceError):value.context='change'


def test_soniox_terms_and_no_qwen_vad():
    value=resolve_effective_asr_config(config(),{'provider':'soniox','model_id':'stt-rt-v6',
        'provider_options':{'terms':['RAG','Soniox'],'context':''}}, {'terms':['RAG','영어']})
    assert list(value.arguments()['vocabulary'])==['RAG','영어','Soniox']
    assert value.context=='' and value.vad_model is None and not value.pcm_batch_enabled


def test_profile_runtime_cannot_override_resolved_server_limits():
    value=resolve_effective_asr_config(config(),{'runtime':{'asr_send_timeout_seconds':999999}})
    assert value.send_timeout_seconds==5


@pytest.mark.asyncio
@pytest.mark.parametrize('provider',['aliyun','soniox'])
@pytest.mark.parametrize('hints',[[],['ko','en']])
async def test_wire_parameters_match_frozen_effective_snapshot(monkeypatch,provider,hints):
    import asyncio
    import app.providers.aliyun as aliyun
    import app.providers.asr.soniox as soniox
    from app.providers.asr.aliyun import AliyunASRAdapter
    server=config();server.soniox_api_key='MOCK-ONLY';server.asr_ws_url='wss://dashscope.aliyuncs.com/api-ws/v1/inference'
    server.dashscope_workspace_id='';server.dashscope_region='cn-beijing'
    snapshot={'provider':provider,'model_id':server.asr_model if provider=='aliyun' else 'stt-rt-v6',
        'credential_ref':'DASHSCOPE_API_KEY' if provider=='aliyun' else 'SONIOX_API_KEY',
        'language_hints':hints.copy(),'provider_options':{'context':''}}
    preferences={'terms':['RAG'],'asr_context':'must be overridden','asr_language_mode':'ko'}
    effective=resolve_effective_asr_config(server,snapshot,preferences)
    adapter=create_asr_provider(server,snapshot=snapshot,effective=effective)
    snapshot['provider_options']['context']='late change';snapshot['language_hints'].append('late')
    preferences['terms'].append('late');server.asr_send_timeout_seconds=99
    inbox=asyncio.Queue();requests=[];pcm=[]
    class Socket:
        async def send(self,value):
            if isinstance(value,bytes):pcm.append(value);return
            if value=='':await inbox.put(json.dumps({'finished':True}));return
            data=json.loads(value)
            if provider=='soniox':
                if data.get('type')=='ping':await inbox.put(json.dumps({'type':'pong','id':data['id']}))
                else:requests.append(data)
            else:
                header=data['header']
                if header['action']=='run-task':requests.append(data['payload'])
                await inbox.put(json.dumps({'header':{'task_id':header['task_id'],
                    'event':'task-started' if header['action']=='run-task' else 'task-finished'}}))
        async def recv(self):return await inbox.get()
    class Connection:
        async def __aenter__(self):return Socket()
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(aliyun if provider=='aliyun' else soniox,'connect',lambda *a,**k:Connection())
    monkeypatch.setattr(AliyunASRAdapter,'ensure_configured',lambda self:None)
    async def audio():yield bytes(200)
    assert [e async for e in adapter.stream_asr(audio(),**effective.arguments())]==[]
    wire=requests[0];public=effective.public_snapshot()
    params=wire['parameters'] if provider=='aliyun' else wire
    assert wire['model']==public['model_id']
    assert params.get('language_hints',[])==public['language_hints']
    assert params['sample_rate']==public['sample_rate']
    assert b''.join(pcm)==bytes(200) and adapter.config.asr_send_timeout_seconds==public['send_timeout_seconds']==5
    if provider=='aliyun':
        assert params['vad_model']==public['vad_model'] and wire['input']=={}
        assert len(params['vocabulary'])==public['vocabulary_count']
    else:
        assert wire['context']['text']=='' and wire['context']['terms']==['RAG']
    assert public['context_chars']==0 and 'MOCK-ONLY' not in json.dumps(public)
