import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from test_core import factory, seed
from app.models import SegmentRevision, ProcessingTask
from app.providers.asr.registry import REGISTRY, ProviderDefinition, NoOptions
from app.providers.asr.factory import create_asr_provider
from app.providers.asr.aliyun_protocol import build_run_task
from app.providers.errors import ProviderError
from app.services.audio_diagnostics import recognition_progress
from app.ws.live import LiveCapture


def test_dependency_boundaries():
    app=Path(__file__).resolve().parents[1]/'app'
    for path in (app/'providers').rglob('*.py'):
        tree=ast.parse(path.read_text(encoding='utf-8'))
        imports=[node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
        assert not any(x.startswith(('app.models','sqlalchemy','app.services.knowledge','app.services.incremental_translation')) for x in imports),path
    for path in [app/'providers/asr/aliyun_protocol.py',app/'services/transcript_state.py']:
        tree=ast.parse(path.read_text(encoding='utf-8'))
        imports=[node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
        assert not any(x.startswith(('app.models','sqlalchemy','websockets','httpx','app.ws')) for x in imports)
    for name in ('base.py','factory.py','soniox.py'):
        assert 'from app.providers.aliyun import' not in (app/'providers/asr'/name).read_text(encoding='utf-8')


@pytest.mark.asyncio
async def test_replacement_adapter_needs_only_normalized_events(factory,monkeypatch):
    class FixtureASR:
        def __init__(self,config):pass
        def ensure_configured(self):pass
        async def stream_asr(self,audio,**kwargs):
            async for _ in audio:pass
            yield dict(sentence_id='1',text='한국어 RAG',start_ms=0,end_ms=None,final=False)
            yield dict(sentence_id='1',text='한국어 RAG',start_ms=0,end_ms=100,final=True)
    monkeypatch.setitem(REGISTRY,'fixture',ProviderDefinition('fixture','fixture','fixture','FIXTURE',FixtureASR,NoOptions))
    adapter=create_asr_provider(SimpleNamespace(asr_provider='fixture'))
    with factory() as db:seed(db,mode='real')
    capture=LiveCapture(AsyncMock(),'lesson','alice');capture.stream_id='stream';capture.asr_provider=adapter
    capture.update_legacy=lambda *a:None
    async def audio():yield bytes(200)
    async for event in adapter.stream_asr(audio()):await capture.consume(event)
    with factory() as db:
        assert db.query(SegmentRevision).one().text=='한국어 RAG'
        assert db.query(ProcessingTask).filter_by(kind='index_segment').count()==1


@pytest.mark.parametrize('options', [{}, {'max_sentence_silence':200}, {'max_sentence_silence':6000},
    {'speech_noise_threshold':-1.0}, {'keep_dialect':False}, {'multi_threshold_mode_enabled':True}])
def test_optional_vad_only_explicit_parameters(options):
    params=build_run_task('t','qwen-audio-3.1-asr-flash-streaming',options=options)['payload']['parameters']
    for key,value in options.items():assert params[key]==value
    if not options:assert 'max_sentence_silence' not in params
    elif options:
        with pytest.raises(ProviderError):build_run_task('t','future-model',options=options)


@pytest.mark.parametrize('options', [{'max_sentence_silence':True},{'max_sentence_silence':199},
    {'speech_noise_threshold':float('nan')},{'speech_noise_threshold':True},{'keep_dialect':'false'}])
def test_invalid_vad(options):
    with pytest.raises(ProviderError):build_run_task('t','qwen-audio-3.1-asr-flash-streaming',options=options)


def test_progress_warning_requires_multiple_signals_and_never_claims_speech():
    metrics={'last_send_monotonic':99,'last_heartbeat_monotonic':99,'asr_result_queue_size':0}
    args=dict(started=50,last_audio=99,input_dbfs=-20,backlog_ms=0)
    assert recognition_progress(metrics,100,**args)['recognition_stall_suspected']
    for changes in ({'last_audio':None},{'input_dbfs':-60},{'backlog_ms':2000}):
        assert not recognition_progress(metrics,100,**{**args,**changes})['recognition_stall_suspected']
    assert recognition_progress({},100,**args)['last_provider_heartbeat_age_ms'] is None
    assert not recognition_progress({**metrics,'asr_result_queue_size':64},100,**args)['recognition_stall_suspected']
