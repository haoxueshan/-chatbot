import asyncio
import json
from types import SimpleNamespace
import pytest
from app.providers.asr.soniox import TokenMapper,SonioxASRAdapter,ENDPOINT
from app.providers.aliyun import ProviderError
import app.providers.asr.soniox as module


def token(text,start=0,end=100,final=False):return {'text':text,'start_ms':start,'end_ms':end,'is_final':final}


@pytest.mark.parametrize('status,code',[(401,'authentication_failed'),(402,'quota_exhausted'),(403,'model_permission'),(429,'rate_limited')])
def test_soniox_errors_never_blame_aliyun_or_echo_upstream_secrets(status,code):
    with pytest.raises(ProviderError) as exc:module.check_error({'error_code':status,'error_message':'private payload'})
    assert exc.value.code==code and 'Soniox' in exc.value.message
    assert '阿里云' not in exc.value.message and 'private payload' not in exc.value.message


def test_redirect_is_not_followed_with_server_credentials():
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response
    from websockets.datastructures import Headers
    redirect=InvalidStatus(Response(302,'Found',Headers({'Location':'wss://127.0.0.1/private'})))
    connector=object.__new__(module.connect)
    assert connector.process_redirect(redirect) is redirect


def test_repeated_tokens_in_one_response_are_not_mistaken_for_replayed_events():
    message={'tokens':[token('네 ',0,100,True),token('네 ',0,100,True),{'text':'<end>','is_final':True}]}
    mapper=TokenMapper()
    assert mapper.update(message)[0]['text']=='네 네'
    assert mapper.update(message)==[]


def test_token_tails_final_boundaries_duplicates_and_late_tokens():
    mapper=TokenMapper()
    assert mapper.update({'tokens':[token('오늘은') ]})[0]['text']=='오늘은'
    assert mapper.update({'tokens':[token('오늘은 ',final=True),token('Machine',100,300)]})[0]['text']=='오늘은 Machine'
    assert mapper.update({'tokens':[token('Machine Learning',100,600)]})[0]['text']=='오늘은 Machine Learning'
    final={'tokens':[token('Machine Learning',100,600,True),{'text':'<end>','is_final':True}]}
    result=mapper.update(final)
    assert len(result)==1 and result[0]['final'] and result[0]['text']=='오늘은 Machine Learning'
    assert (result[0]['start_ms'],result[0]['end_ms'])==(0,600)
    assert mapper.update(final)==[]
    assert mapper.update({'tokens':[token('late text',0,500)]})==[]
    next_=mapper.update({'tokens':[token('네',800,1000)]})[0]
    assert next_['sentence_id']=='2' and not next_['final']
    mapper.update({'tokens':[token('네',800,1000,True)]})
    assert mapper.update({'tokens':[],'finished':True})[0]['final']


def test_incomplete_or_untimed_tokens_never_become_fake_final():
    mapper=TokenMapper();mapper.update({'tokens':[token('미확인')]})
    with pytest.raises(ProviderError) as exc:mapper.update({'tokens':[],'finished':True})
    assert exc.value.code=='asr_incomplete'
    with pytest.raises(ProviderError) as exc:TokenMapper().update({'tokens':[{'text':'untimed','is_final':True}]})
    assert exc.value.code=='asr_timestamp_missing'


def test_late_endpoint_cannot_finalize_next_sentence_and_bare_endpoint_cannot_drop_tail():
    mapper=TokenMapper()
    mapper.update({'tokens':[token('첫 문장',0,100,True),{'text':'<end>','is_final':True}]})
    mapper.update({'tokens':[token('두 번째',120,200)]})
    assert mapper.update({'tokens':[token('첫 문장',0,100,True),{'text':'<end>','is_final':True}], 'total_audio_proc_ms':220})==[]
    assert mapper.pending[0]['text']=='두 번째'
    with pytest.raises(ProviderError) as exc:mapper.update({'tokens':[{'text':'<end>','is_final':True}]})
    assert exc.value.code=='asr_incomplete'


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',[None,'send','disconnect','drain','drain_heartbeat','auth','cancel','transport_close','handshake_timeout','prepare_cancel','heartbeat'])
async def test_soniox_protocol_stop_errors_and_cleanup(monkeypatch,failure):
    before=set(asyncio.all_tasks());messages=asyncio.Queue();sent=[];closed=[];connections=[];ready=[];configured=asyncio.Event();ended=False
    async def tls():return True
    monkeypatch.setattr(module,'tls_context',tls)
    class Socket:
        async def send(self,value):
            nonlocal ended
            sent.append(value)
            if isinstance(value,bytes):
                if failure=='send':await asyncio.Event().wait()
                if failure=='transport_close':
                    from websockets.exceptions import ConnectionClosed
                    raise ConnectionClosed(None,None)
                if failure=='disconnect':
                    await messages.put({'error_code':503,'error_type':'service_unavailable'});return
                await messages.put({'tokens':[token('교수님 question',0,20)]})
            elif value=='':
                ended=True
                if failure in ('drain','drain_heartbeat'):return
                await messages.put({'tokens':[token('교수님 question',0,20,True),{'text':'<end>','is_final':True}]})
                await messages.put({'tokens':[],'finished':True})
            elif json.loads(value).get('type')=='ping':
                configured.set()
                if failure in ('handshake_timeout','prepare_cancel'):return
                await messages.put({'error_code':401} if failure=='auth' else {'type':'pong','id':json.loads(value)['id']})
        async def recv(self):
            if ended and failure=='drain_heartbeat' and messages.empty():
                await asyncio.sleep(.005);return json.dumps({'type':'pong','id':9})
            return json.dumps(await messages.get())
    class Context:
        async def __aenter__(self):return Socket()
        async def __aexit__(self,*args):closed.append(True)
    def connect(url,**kwargs):
        connections.append(url);assert url==ENDPOINT
        assert kwargs['additional_headers']=={'Authorization':'Bearer test-soniox-only'}
        return Context()
    monkeypatch.setattr(module,'connect',connect)
    config=SimpleNamespace(soniox_api_key='test-soniox-only',asr_model='stt-rt-v6',model_timeout_seconds=.3,
        asr_event_timeout_seconds=.09,asr_finish_timeout_seconds=.05,asr_send_timeout_seconds=.04,
        asr_options={'terms':['Retrieval-Augmented Generation']})
    async def audio():
        assert ready
        yield b'\1\0'*320
        if failure=='cancel':await asyncio.Event().wait()
        if failure=='heartbeat':
            async with asyncio.timeout(.3):
                while metrics.get('heartbeat_events',0)<2:await asyncio.sleep(.001)
    async def on_ready():ready.append(True)
    metrics={}
    stream=SonioxASRAdapter(config).stream_asr(audio(),on_ready=on_ready,language_hints=['ko','en'],context='课堂',metrics=metrics)
    if failure=='prepare_cancel':
        task=asyncio.create_task(anext(stream));await configured.wait();task.cancel()
        await asyncio.gather(task,return_exceptions=True);await stream.aclose()
        assert not ready and not any(isinstance(v,bytes) for v in sent)
    elif failure=='cancel':
        first=await anext(stream);assert not first['final'];await stream.aclose()
    elif failure and failure!='heartbeat':
        with pytest.raises(ProviderError) as exc:
            async for _ in stream:pass
        assert exc.value.code=={'send':'upstream_send_timeout','disconnect':'upstream_error','drain':'asr_finish_timeout','drain_heartbeat':'asr_finish_timeout','auth':'authentication_failed','transport_close':'upstream_disconnected','handshake_timeout':'timeout'}[failure]
    else:
        result=[e async for e in stream]
        assert [e['final'] for e in result]==[False,True]
        assert result[-1]['text']=='교수님 question' and result[-1]['sentence_id']=='1'
        assert metrics['sent_audio_ms']==20 and '' in sent
    request=json.loads(sent[0])
    assert request['model']=='stt-rt-v6' and request['language_hints']==['ko','en']
    assert request['audio_format']=='pcm_s16le' and request['sample_rate']==16000 and request['num_channels']==1
    assert request['context']=={'text':'课堂','terms':['Retrieval-Augmented Generation']}
    assert 'api_key' not in request and 'translation' not in request and 'task_id' not in request
    assert len(connections)==1 and closed==[True] and set(asyncio.all_tasks())==before
