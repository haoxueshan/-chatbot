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


@pytest.mark.asyncio
async def test_missing_key_refuses_every_paid_entry_without_fallback():
    provider = AliyunProvider(SimpleNamespace(dashscope_api_key=""))
    for call in (lambda: provider.translate("hello"), lambda: provider.embeddings(["hello"]), lambda: provider.generate("hello"), lambda: provider.submit_filetrans("https://example.com/audio.wav")):
        with pytest.raises(ProviderError) as error:
            await call()
        assert error.value.code == "missing_api_key"


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
    assert err.value.diagnostics=={'upstream_close_code':1000}
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
    async def run():return [e async for e in AliyunProvider(config(asr_send_timeout_seconds=.02)).stream_asr(audio())]
    with pytest.raises(ProviderError) as err:await asyncio.wait_for(run(),.2)
    assert err.value.code=='upstream_send_timeout'
