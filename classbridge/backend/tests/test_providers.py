import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

import app.providers.aliyun as module
from app.providers.aliyun import AliyunProvider, ProviderError, classify_error, normalize_filetrans


def config(**kwargs):
    return SimpleNamespace(dashscope_api_key="test-key-only", dashscope_workspace_id="test-space", dashscope_region="cn-beijing", model_timeout_seconds=1, **kwargs)


def install_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def test_asr_factory_keeps_default_and_rejects_unimplemented_providers():
    from app.providers.asr.factory import create_asr_provider
    assert isinstance(create_asr_provider(config()),AliyunProvider)
    for name in ('daglo','naver','rtzr','typo'):
        with pytest.raises(ProviderError) as error:create_asr_provider(config(asr_provider=name))
        assert error.value.code=='unsupported_asr_provider'
    with pytest.raises(ProviderError) as error:
        create_asr_provider(SimpleNamespace(asr_provider='aliyun',dashscope_api_key='')).ensure_configured()
    assert error.value.code=='missing_api_key'


@pytest.mark.asyncio
async def test_asr_event_silence_is_bounded_and_releases_socket(monkeypatch):
    task='c'*32;closed=[];pending_before=set(asyncio.all_tasks())
    monkeypatch.setattr(module.uuid,'uuid4',lambda:SimpleNamespace(hex=task))
    class Socket:
        first=True
        async def send(self,data):pass
        async def recv(self):
            if self.first:
                self.first=False
                return json.dumps({'header':{'event':'task-started','task_id':task}})
            await asyncio.Event().wait()
    class Context:
        async def __aenter__(self):return Socket()
        async def __aexit__(self,*args):closed.append(True)
    monkeypatch.setattr(module,'connect',lambda *a,**k:Context())
    async def audio():
        yield bytes(640)
        await asyncio.Event().wait()
    with pytest.raises(ProviderError) as error:
        async for _ in AliyunProvider(config(asr_event_timeout_seconds=.02)).stream_asr(audio()):pass
    assert error.value.code=='asr_event_timeout' and closed==[True]
    assert set(asyncio.all_tasks())==pending_before


@pytest.mark.asyncio
@pytest.mark.parametrize('server_finished',[False,True])
async def test_finish_deadline_also_bounds_stalled_finish_send(monkeypatch,server_finished):
    task='f'*32;closed=[];finishing=asyncio.Event()
    monkeypatch.setattr(module.uuid,'uuid4',lambda:SimpleNamespace(hex=task))
    class Socket:
        first=True
        async def send(self,data):
            if isinstance(data,str) and json.loads(data)['header']['action']=='finish-task':
                finishing.set()
                await asyncio.Event().wait()
        async def recv(self):
            if self.first:
                self.first=False
                return json.dumps({'header':{'event':'task-started','task_id':task}})
            if server_finished:
                await finishing.wait()
                return json.dumps({'header':{'event':'task-finished','task_id':task}})
            await asyncio.Event().wait()
    class Context:
        async def __aenter__(self):return Socket()
        async def __aexit__(self,*args):closed.append(True)
    monkeypatch.setattr(module,'connect',lambda *a,**k:Context())
    async def audio():yield bytes(640)
    async def run():
        async for _ in AliyunProvider(config(asr_finish_timeout_seconds=.02)).stream_asr(audio()):pass
    with pytest.raises(ProviderError) as error:await asyncio.wait_for(run(),.5)
    assert error.value.code=='asr_finish_timeout' and closed==[True]


@pytest.mark.asyncio
@pytest.mark.parametrize("minutes,batch_ms",[(5,20),(30,40),(65,60),(105,100)])
async def test_long_pcm_clock_heartbeats_order_and_cleanup(monkeypatch,minutes,batch_ms):
    """Up to 315,000 actual PCM frames, accelerated clock; no network or DB."""
    import app.ws.live as live
    from unittest.mock import AsyncMock
    clock=[100.];task='e'*32;total=minutes*60*50;count=0;closed=[]
    started_tasks=set(asyncio.all_tasks());peak_tasks=0
    monotonic=SimpleNamespace(monotonic=lambda:clock[0])
    monkeypatch.setattr(module,'time',monotonic);monkeypatch.setattr(live,'time',monotonic)
    monkeypatch.setattr(module.uuid,'uuid4',lambda:SimpleNamespace(hex=task))
    messages=asyncio.Queue(maxsize=2);sent_batch=asyncio.Event()
    def event(kind,sentence=None):
        return json.dumps({'header':{'event':kind,'task_id':task},
            'payload':{'output':{'sentence':sentence or {}}}})
    class Socket:
        async def send(self,data):
            nonlocal count,peak_tasks
            if isinstance(data,bytes):
                assert len(data)%640==0
                for offset in range(0,len(data),640):
                    assert data[offset:offset+640]==(count%32768).to_bytes(2,'little')*320
                    count+=1;clock[0]=100+count*.02
                    if count%250==0:
                        await messages.put(event('result-generated',{'heartbeat':True}))
                if count%30==0:sent_batch.set()
                if count%3000==0:peak_tasks=max(peak_tasks,len(asyncio.all_tasks()-started_tasks))
            elif json.loads(data)['header']['action']=='run-task':
                await messages.put(event('task-started'))
            else:
                await messages.put(event('result-generated',{'sentence_id':1,'text':'mock final',
                    'begin_time':0,'end_time':total*20,'sentence_end':True}))
                await messages.put(event('task-finished'))
        async def recv(self):return await messages.get()
    class Context:
        async def __aenter__(self):return Socket()
        async def __aexit__(self,*args):closed.append(True)
    monkeypatch.setattr(module,'connect',lambda *a,**k:Context())
    capture=live.LiveCapture(AsyncMock(),'synthetic-only','mock-user')
    capture.mode='real';capture.ready=True;capture.started=clock[0];capture.target_language='zh-CN'
    # A second capture has isolated queue/metrics even when sentence IDs repeat.
    other=live.LiveCapture(AsyncMock(),'second-synthetic','mock-user')
    finals=[]
    async def consume():
        provider=AliyunProvider(config(asr_event_timeout_seconds=30,aliyun_asr_batch_enabled=True,aliyun_asr_batch_ms=batch_ms,aliyun_asr_batch_max_wait_ms=100))
        async for item in provider.stream_asr(capture.audio_iter(),metrics=capture.asr_metrics):finals.append(item)
    capture.task=asyncio.create_task(consume())
    try:
        for base in range(0,total,30):
            sent_batch.clear()
            for index in range(base,base+30):await capture.audio((index%32768).to_bytes(2,'little')*320)
            await asyncio.wait_for(sent_batch.wait(),2)
        capture.signal_stop();await asyncio.wait_for(capture.task,2)
    finally:
        capture.task.cancel();await asyncio.gather(capture.task,return_exceptions=True)
    assert count==total and capture.received_audio_ms==capture.asr_metrics['sent_audio_ms']==minutes*60000
    assert capture.queued_bytes==capture.queued_frames==0 and 0<capture.audio_queue_peak<=32000
    assert capture.asr_metrics['heartbeat_events']==minutes*12 and capture.asr_metrics['transcript_events']==1
    assert len(finals)==1 and finals[0]['final'] and finals[0]['end_ms']==minutes*60000
    assert not capture.failure_reported and closed==[True]
    assert other.queue.empty() and not other.asr_metrics and other.received_audio_ms==0
    assert peak_tasks<=10 and set(asyncio.all_tasks())==started_tasks
    print(json.dumps({'synthetic_minutes':minutes,'batch_ms':batch_ms,'frames':count,'queue_peak_ms':capture.audio_queue_peak/32,
        'peak_internal_tasks':peak_tasks,'remaining_tasks':len(asyncio.all_tasks()-started_tasks),
        'finals':len(finals),'gaps':0}))


@pytest.mark.asyncio
@pytest.mark.parametrize('phase',['finish','wrong_task'])
async def test_heartbeat_cannot_extend_finish_or_foreign_task_deadline(monkeypatch,phase):
    task='d'*32;clock=[0.];finished=asyncio.Event();closed=[];count=[0]
    monkeypatch.setattr(module.uuid,'uuid4',lambda:SimpleNamespace(hex=task))
    monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    class Socket:
        async def send(self,data):
            if isinstance(data,str) and json.loads(data)['header']['action']=='finish-task':finished.set()
        async def recv(self):
            count[0]+=1
            if count[0]==1:return json.dumps({'header':{'event':'task-started','task_id':task}})
            if phase=='finish':await finished.wait()
            clock[0]+=.25
            return json.dumps({'header':{'event':'task-finished' if count[0]>=20 else 'result-generated',
                'task_id':task if phase=='finish' or count[0]>=20 else 'foreign'},
                'payload':{'output':{'sentence':{'heartbeat':True}}}})
    class Context:
        async def __aenter__(self):return Socket()
        async def __aexit__(self,*args):closed.append(True)
    monkeypatch.setattr(module,'connect',lambda *a,**k:Context())
    async def audio():
        if phase=='wrong_task':await asyncio.Event().wait()
        yield b'\0'*640
    metrics={}
    with pytest.raises(ProviderError) as err:
        async for _ in AliyunProvider(config()).stream_asr(audio(),metrics=metrics):pass
    assert err.value.code==('asr_finish_timeout' if phase=='finish' else 'asr_event_timeout')
    assert count[0]<=7 and closed==[True]


@pytest.mark.asyncio
async def test_missing_key_refuses_every_paid_entry_without_fallback():
    provider = AliyunProvider(SimpleNamespace(dashscope_api_key=""))
    for call in (lambda: provider.translate("hello"), lambda: provider.embeddings(["hello"]), lambda: provider.generate("hello"), lambda: provider.submit_filetrans("https://example.com/audio.wav")):
        with pytest.raises(ProviderError) as error:
            await call()
        assert error.value.code == "missing_api_key"


@pytest.mark.asyncio
@pytest.mark.parametrize('final_count',[1,100])
async def test_slow_consumer_does_not_pause_upstream_read_or_pcm_send(monkeypatch,final_count):
    task='a'*32;sent=[];finished=asyncio.Event();final_read=asyncio.Event();bounded=asyncio.Event();closed=[]
    monkeypatch.setattr(module.uuid,'uuid4',lambda:SimpleNamespace(hex=task))
    class Socket:
        index=0
        async def send(self,value):
            sent.append(value)
            if isinstance(value,str) and json.loads(value)['header']['action']=='finish-task':finished.set()
        async def recv(self):
            self.index+=1
            if self.index==1:return json.dumps({'header':{'event':'task-started','task_id':task}})
            if self.index<=final_count+2:
                final=self.index>=3
                if final:final_read.set()
                if self.index==67:bounded.set()
                return json.dumps({'header':{'event':'result-generated','task_id':task},'payload':{'output':{'sentence':{'sentence_id':max(1,self.index-2),'text':'evidence','sentence_end':final,'begin_time':0,'end_time':40}}}})
            await finished.wait()
            return json.dumps({'header':{'event':'task-finished','task_id':task}})
    class Context:
        async def __aenter__(self):return Socket()
        async def __aexit__(self,*args):closed.append(True)
    monkeypatch.setattr(module,'connect',lambda *a,**k:Context())
    frames=[i.to_bytes(2,'little')*320 for i in range(10)]
    async def audio():
        for frame in frames:yield frame
    metrics={};stream=AliyunProvider(config()).stream_asr(audio(),metrics=metrics)
    first=await anext(stream)
    assert not first['final']
    # Deliberately do not request the next yield until socket read/send finished.
    await asyncio.wait_for(final_read.wait(),1)
    await asyncio.wait_for(finished.wait(),1)
    if final_count==100:
        await asyncio.wait_for(bounded.wait(),1)
        # 64 queued finals + one fetched/being decoded in the reader + partial.
        assert 65<=metrics['transcript_events']<=66
    rest=[e async for e in stream]
    assert len(rest)==final_count and all(e['final'] for e in rest)
    assert [e['sentence_id'] for e in rest]==[str(i) for i in range(1,final_count+1)]
    assert [v for v in sent if isinstance(v,bytes)]==frames
    assert metrics['sent_audio_ms']==200 and closed==[True]


@pytest.mark.parametrize("status,code,expected", [(401,"InvalidApiKey","authentication_failed"),(403,"AccessDenied","model_permission"),(402,"","quota_exhausted"),(429,"Throttling","rate_limited"),(504,"","timeout"),(400,"InvalidParameter","format_error"),(400,"InvalidWorkspace","region_mismatch"),(404,"ModelNotFound","model_unavailable")])
def test_error_categories_are_safe(status, code, expected):
    error = classify_error(status, code)
    assert error.code == expected
    assert "test-key" not in str(error)


def test_workspace_urls_and_explicit_overrides():
    provider = AliyunProvider(config())
    assert provider.base("ws") == "wss://test-space.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"
    assert provider.base("native").endswith("/api/v1")
    assert AliyunProvider(config(openai_base_url="https://custom.example/v1/")).base() == "https://custom.example/v1"
    with pytest.raises(ProviderError, match="WORKSPACE"):
        AliyunProvider(SimpleNamespace(dashscope_workspace_id="")).base()


@pytest.mark.asyncio
async def test_illegal_workspace_handshake_is_not_audio_format_error(monkeypatch):
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response
    from websockets.datastructures import Headers
    class Context:
        async def __aenter__(self):
            raise InvalidStatus(Response(400, 'Bad Request', Headers(),
                body=b'{"code":"BadRequest.IllegalEndpoint","message":"Workspace endpoint is invalid."}'))
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(module, 'connect', lambda *args, **kwargs: Context())
    submitted=[]
    async def audio():
        submitted.append(True)
        yield b'\0\0'*320
    with pytest.raises(ProviderError) as error:
        async for _ in AliyunProvider(config()).stream_asr(audio()): pass
    assert error.value.code=='region_mismatch'
    assert 'API Host' in error.value.message
    assert not submitted


@pytest.mark.asyncio
async def test_mt_uses_single_user_message_supported_options_and_stream(monkeypatch):
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, headers={"Content-Type":"text/event-stream"}, text='data: {"choices":[{"delta":{"content":"你好"}}]}\n\ndata: {"choices":[{"delta":{"content":"世界"}}]}\n\ndata: [DONE]\n\n')
    install_http(monkeypatch, handler)
    result = await AliyunProvider(config()).translate("hello world", terms=[{"source":"gradient", "target":"梯度"}], context="Computer science", memory=[{"source":"loss", "target":"损失"}])
    assert result == "你好世界"
    request = captured[0]
    assert request["messages"] == [{"role":"user", "content":"hello world"}]
    assert request["translation_options"]["source_lang"] == "auto"
    assert request["translation_options"]["target_lang"] == "Chinese"
    assert request["translation_options"]["terms"][0]["target"] == "梯度"
    assert "tm_list" in request["translation_options"]
    assert request["stream"] is True


@pytest.mark.asyncio
async def test_paid_request_is_not_automatically_retried(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"error":{"code":"Throttling", "message":"raw unsafe diagnostic"}})
    install_http(monkeypatch, handler)
    with pytest.raises(ProviderError) as error:
        await AliyunProvider(config()).generate("question")
    assert len(calls) == 1
    assert error.value.code == "rate_limited"
    assert "raw unsafe" not in str(error.value)


@pytest.mark.asyncio
async def test_embedding_batches_respects_v4_limit(monkeypatch):
    sizes = []
    def handler(request):
        payload = json.loads(request.content)
        sizes.append(len(payload["input"]))
        return httpx.Response(200, json={"data":[{"index":i,"embedding":[0.0]*1024} for i in reversed(range(len(payload["input"]))) ]})
    install_http(monkeypatch, handler)
    vectors = await AliyunProvider(config()).embeddings(["one"]*23)
    assert sizes == [10, 10, 3]
    assert len(vectors) == 23


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,expected_hints',[('auto',None),('ko_en',['ko','en']),('ko',['ko'])])
@pytest.mark.parametrize('vad_model',['far_field_meeting_16k','near_meeting_16k'])
async def test_streaming_asr_waits_started_sends_pcm_and_finishes(monkeypatch,mode,expected_hints,vad_model):
    from app.services.asr_options import asr_language_hints
    task = "a"*32
    monkeypatch.setattr(module.uuid, "uuid4", lambda: SimpleNamespace(hex=task))
    sent = []
    started = False
    ready = []
    finished = asyncio.Event()
    class Socket:
        def __init__(self): self.index = 0
        async def send(self, value):
            if isinstance(value, bytes):
                assert started, "No audio before task-started"
            else:
                obj = json.loads(value)
                if obj["header"]["action"] == "finish-task": finished.set()
            sent.append(value)
        async def recv(self):
            nonlocal started
            self.index += 1
            if self.index == 1:
                started = True
                return json.dumps({"header":{"event":"task-started","task_id":task},"payload":{}})
            await asyncio.sleep(0)
            if self.index == 2:
                sentence = {"sentence_id":1,"begin_time":10,"end_time":None,"text":"hello","sentence_end":False}
            elif self.index == 3:
                sentence = {"sentence_id":1,"begin_time":10,"end_time":400,"text":"hello world","sentence_end":True}
            else:
                await finished.wait()
                return json.dumps({"header":{"event":"task-finished","task_id":task},"payload":{}})
            return json.dumps({"header":{"event":"result-generated","task_id":task},"payload":{"output":{"sentence":sentence}}})
    class Context:
        async def __aenter__(self): return Socket()
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(module, "connect", lambda *args, **kwargs: Context())
    async def audio():
        assert ready == [True], 'Browser readiness precedes audio consumption'
        yield b"\x00\x00"*320
        yield b"\x01\x00"*320
    async def on_ready():
        assert started
        ready.append(True)
    metrics={}
    context=('작업기억 '+ '인지부하 '*90) if mode=='ko_en' else None
    result = [event async for event in AliyunProvider(config()).stream_asr(audio(),on_ready=on_ready,metrics=metrics,
        vocabulary={'RAG':2},context=context,language_hints=asr_language_hints(mode),vad_model=vad_model)]
    assert result[0]["final"] is False and result[1]["final"] is True
    assert result[1]["end_ms"] == 400
    start = json.loads(sent[0])
    assert start["payload"]["parameters"]["format"] == "pcm"
    assert start["payload"]["parameters"]["sample_rate"] == 16000
    assert start["payload"]["parameters"]["vad_model"] == vad_model
    if expected_hints is None:assert 'language_hints' not in start['payload']['parameters']
    else:assert start['payload']['parameters']['language_hints']==expected_hints
    assert result[1]['text']=='hello world'  # ASR output is never rewritten into the translation language.
    assert 'target_language' not in start['payload']['parameters']
    assert 'target_lang' not in start['payload']['parameters']
    if context:
        assert start['payload']['input']['context']==[{'role':'user','content':[{'type':'input_text','text':context.strip()[:400]}]}]
    else:assert start['payload']['input']=={}
    assert start['payload']['parameters']['vocabulary']=={'RAG':2}
    assert metrics['transcript_events']==2
    assert metrics['sent_audio_ms']==40
    assert metrics['last_transcript_monotonic']<=metrics['last_event_monotonic']
    assert json.loads(sent[-1])["header"]["action"] == "finish-task"


@pytest.mark.asyncio
async def test_wrong_task_started_never_releases_microphone_audio(monkeypatch):
    sent = []
    class Socket:
        async def send(self, value): sent.append(value)
        async def recv(self):
            return json.dumps({'header': {'event': 'task-started', 'task_id': 'unrelated-task'}, 'payload': {}})
    class Context:
        async def __aenter__(self): return Socket()
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(module, 'connect', lambda *args, **kwargs: Context())
    async def ready(): pytest.fail('Mismatched task must not mark the capture ready')
    async def audio():
        pytest.fail('Audio must not be consumed before a matching task-started')
        yield bytes(640)
    with pytest.raises(ProviderError) as error:
        async for _ in AliyunProvider(config()).stream_asr(audio(), on_ready=ready): pass
    assert error.value.code == 'protocol_error'
    assert len(sent) == 1 and json.loads(sent[0])['header']['action'] == 'run-task'


@pytest.mark.asyncio
async def test_filetrans_sends_async_and_validates_download_origin(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["parameters"]["diarization_enabled"] is True
            assert "language_hints" not in body["parameters"]
            assert request.headers["X-DashScope-Async"] == "enable"
            return httpx.Response(200,json={"output":{"task_id":"task-one","task_status":"PENDING"}})
        return httpx.Response(200,json={"output":{"task_status":"SUCCEEDED","results":[{"subtask_status":"SUCCEEDED","transcription_url":"https://evil.example/internal"}]}})
    install_http(monkeypatch, handler)
    provider = AliyunProvider(config())
    assert await provider.submit_filetrans("https://private.example/signed.wav") == "task-one"
    with pytest.raises(ProviderError, match="不受信任"):
        await provider.poll_filetrans("task-one")
    assert len(requests) == 2


def test_filetrans_normalizes_timestamp_speaker_not_identity():
    rows = normalize_filetrans({"transcripts":[{"sentences":[{"text":"안녕하세요", "begin_time":10, "end_time":1000, "speaker_id":1}]}]})
    assert rows == [{"text":"안녕하세요", "start_ms":10, "end_ms":1000, "speaker":"1"}]
    with pytest.raises(ProviderError):
        normalize_filetrans({"transcripts":[{"sentences":[{"text":"bad", "begin_time":100, "end_time":10}]}]})


@pytest.mark.asyncio
async def test_audio_sender_failure_wakes_receiver_immediately(monkeypatch):
    task='b'*32
    monkeypatch.setattr(module.uuid,'uuid4',lambda:SimpleNamespace(hex=task))
    class Socket:
        calls=0
        async def send(self,data):pass
        async def recv(self):
            self.calls+=1
            if self.calls==1:return json.dumps({'header':{'event':'task-started','task_id':task}})
            await asyncio.Event().wait()
    class Context:
        async def __aenter__(self):return Socket()
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(module,'connect',lambda *args,**kwargs:Context())
    async def audio():yield b'odd'
    async def run():return [e async for e in AliyunProvider(config()).stream_asr(audio())]
    with pytest.raises(ProviderError) as err:await asyncio.wait_for(run(),.2)
    assert err.value.code=='format_error'  # Not the receiver's one-second timeout.


@pytest.mark.asyncio
async def test_cancel_keeps_original_cancellation_when_sender_raises_during_cleanup(monkeypatch):
    from websockets.exceptions import ConnectionClosedOK
    from websockets.frames import Close
    task='c'*32;entered=asyncio.Event();sender_done=asyncio.Event()
    monkeypatch.setattr(module.uuid,'uuid4',lambda:SimpleNamespace(hex=task))
    class Socket:
        calls=0
        async def send(self,data):
            if isinstance(data,bytes):
                entered.set()
                try:await asyncio.Event().wait()
                except asyncio.CancelledError:
                    sender_done.set()
                    raise ConnectionClosedOK(Close(1000,''),Close(1000,''),True)
        async def recv(self):
            self.calls+=1
            if self.calls==1:return json.dumps({'header':{'event':'task-started','task_id':task}})
            await asyncio.Event().wait()
    class Context:
        async def __aenter__(self):return Socket()
        async def __aexit__(self,*args):assert sender_done.is_set()
    monkeypatch.setattr(module,'connect',lambda *args,**kwargs:Context())
    async def audio():yield bytes(640)
    async def run():return [e async for e in AliyunProvider(config()).stream_asr(audio())]
    worker=asyncio.create_task(run());await entered.wait();worker.cancel()
    with pytest.raises(asyncio.CancelledError):await worker


@pytest.mark.asyncio
async def test_upstream_close_has_specific_safe_diagnostics(monkeypatch):
    from websockets.exceptions import ConnectionClosedOK
    from websockets.frames import Close
    task='d'*32
    monkeypatch.setattr(module.uuid,'uuid4',lambda:SimpleNamespace(hex=task))
    class Socket:
        calls=0
        async def send(self,data):pass
        async def recv(self):
            self.calls+=1
            if self.calls==1:return json.dumps({'header':{'event':'task-started','task_id':task}})
            raise ConnectionClosedOK(Close(1000,'unsafe response text'),Close(1000,''),True)
    class Context:
        async def __aenter__(self):return Socket()
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(module,'connect',lambda *args,**kwargs:Context())
    async def audio():
        await asyncio.Event().wait()
        yield bytes(640)
    with pytest.raises(ProviderError) as err:
        async for _ in AliyunProvider(config()).stream_asr(audio()):pass
    assert err.value.code=='upstream_disconnected'
    assert err.value.diagnostics=={'upstream_close_code':1000,'provider_task_id':task,'exception_type':'ConnectionClosedOK'}
    assert 'unsafe' not in err.value.message


@pytest.mark.asyncio
async def test_blocked_upstream_send_has_bounded_timeout(monkeypatch):
    task='e'*32
    monkeypatch.setattr(module.uuid,'uuid4',lambda:SimpleNamespace(hex=task))
    class Socket:
        calls=0
        async def send(self,data):
            if isinstance(data,bytes):await asyncio.Event().wait()
        async def recv(self):
            self.calls+=1
            if self.calls==1:return json.dumps({'header':{'event':'task-started','task_id':task}})
            await asyncio.Event().wait()
    class Context:
        async def __aenter__(self):return Socket()
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(module,'connect',lambda *args,**kwargs:Context())
    async def audio():yield bytes(640)
    metrics={};before=set(asyncio.all_tasks())
    async def run():return [e async for e in AliyunProvider(config(asr_send_timeout_seconds=.02)).stream_asr(audio(),metrics=metrics)]
    with pytest.raises(ProviderError) as err:await asyncio.wait_for(run(),.2)
    assert err.value.code=='upstream_send_timeout'
    assert err.value.diagnostics['timeout_phase']=='audio_send'
    assert metrics['uncertain_delivery_pcm_bytes']==640 and metrics['sent_audio_ms']==0
    assert metrics['upstream_inflight_pcm_bytes']==0 and 'send_started_monotonic' not in metrics
    assert set(asyncio.all_tasks())==before


@pytest.mark.asyncio
async def test_invalid_handshake_reports_only_safe_metadata(monkeypatch):
    from websockets.exceptions import InvalidMessage
    class Context:
        async def __aenter__(self):raise InvalidMessage('private proxy body must not appear')
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(module,'connect',lambda *args,**kwargs:Context())
    async def audio():yield bytes(640)
    with pytest.raises(ProviderError) as err:
        async for _ in AliyunProvider(config()).stream_asr(audio()):pass
    assert err.value.code=='upstream_handshake_invalid'
    assert err.value.diagnostics['timeout_phase']=='handshake'
    assert 'private' not in str(err.value.diagnostics)+err.value.message
