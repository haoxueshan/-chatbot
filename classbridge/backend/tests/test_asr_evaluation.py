import json
import subprocess
import sys
import unicodedata
import wave

import pytest

from app.providers.asr.evaluation import evaluate_wav, evaluation_config, score
from app.providers.aliyun import ProviderError


def test_reference_metrics_and_terms_are_explicit():
    assert score(None,'synthetic output') is None
    result=score('인공지능 RAG is useful','인공지능 RAG is powerful',['RAG','Machine Learning'])
    assert result['english_wer']==pytest.approx(1/3)
    assert result['korean_cer']==0 and result['mixed_token_error_rate']==pytest.approx(1/7)
    assert result['term_retention']==1
    assert score('네','아니요')['korean_cer']==3
    assert score('네','中文')['mixed_token_error_rate']==2
    assert score(unicodedata.normalize('NFD','자연어 처리'),'자연어 처리')['korean_cer']==0
    assert score('RAG','storage',['RAG'])['term_retention']==0
    assert score('네','네')['english_wer'] is None


@pytest.mark.asyncio
async def test_same_wav_replay_has_exact_frames_final_versions_and_metrics(tmp_path):
    path=tmp_path/'synthetic.wav';pcm=b'\x01\0'*801
    with wave.open(str(path),'wb') as wav:
        wav.setparams((1,2,16000,0,'NONE','not compressed'));wav.writeframes(pcm)
    clock=[0.]
    async def sleep(delay):clock[0]+=delay
    class Provider:
        def __init__(self):self.frames=[]
        async def stream_asr(self,audio,*,on_ready,metrics,language_hints):
            assert language_hints==['ko','en']
            await on_ready()
            async for frame in audio:
                self.frames.append(frame)
                yield {'sentence_id':'1','text':'임시','start_ms':0,'end_ms':None,'final':False}
            clock[0]+=.1
            for text in ('네 RAG','네 RAG'):
                yield {'sentence_id':'1','text':text,'start_ms':0,'end_ms':50,'final':True}
    for _ in range(2):
        provider=Provider()
        report=await evaluate_wav(provider,path,reference='네 RAG',terms=['RAG'],
            language_hints=['ko','en'],clock=lambda:clock[0],sleep=sleep)
        assert b''.join(provider.frames)==pcm and [len(f) for f in provider.frames]==[640,640,322]
        assert report['forwarded_bytes']==1602 and report['audio_ms']==50.0625
        assert report['first_partial_ms']==0 and report['final_after_audio_ms']==pytest.approx(100)
        assert report['final_segments']==1 and report['accuracy']['mixed_token_error_rate']==0
        assert report['hourly_cost'] is None
        assert '네' not in json.dumps(report,ensure_ascii=False)


@pytest.mark.asyncio
async def test_wav_validation_and_stream_failure_do_not_claim_success(tmp_path):
    path=tmp_path/'synthetic.wav'
    class Provider:
        async def stream_asr(self,audio,**kwargs):
            await kwargs['on_ready']()
            async for _ in audio:pass
            yield {'sentence_id':'1','text':'partial only','start_ms':0,'end_ms':None,'final':False}
            raise RuntimeError('mock broken connection')
    with wave.open(str(path),'wb') as wav:
        wav.setparams((2,2,16000,0,'NONE','not compressed'));wav.writeframes(bytes(640))
    with pytest.raises(ValueError,match='mono PCM16LE'):await evaluate_wav(Provider(),path)
    with wave.open(str(path),'wb') as wav:
        wav.setparams((1,2,16000,0,'NONE','not compressed'));wav.writeframes(bytes(640))
    with pytest.raises(RuntimeError,match='broken connection'):await evaluate_wav(Provider(),path,realtime=False)


def test_evaluation_model_resolution_is_provider_specific(monkeypatch):
    monkeypatch.setenv('ASR_MODEL', 'qwen-test-model')
    assert evaluation_config('aliyun').asr_model == 'qwen-test-model'
    soniox = evaluation_config('soniox')
    assert soniox.asr_provider == 'soniox'
    assert soniox.asr_model == 'stt-rt-v6'
    assert evaluation_config('soniox', 'explicit-model').asr_model == 'explicit-model'
    assert evaluation_config('aliyun', 'explicit-model').asr_model == 'explicit-model'
    assert evaluation_config('soniox').asr_model == 'stt-rt-v6'


@pytest.mark.parametrize('model', ['', 'bad model', '../model', 'x' * 121])
def test_evaluation_rejects_invalid_model(model):
    with pytest.raises(ProviderError):
        evaluation_config('soniox', model)


@pytest.mark.parametrize('provider', ['unknown', 'deepgram', 'elevenlabs'])
def test_evaluation_rejects_unavailable_provider(provider):
    with pytest.raises(ProviderError):
        evaluation_config(provider)


def test_cli_refuses_real_api_without_explicit_authorization():
    result=subprocess.run([sys.executable,'-m','app.providers.asr.evaluation','not-read.wav'],capture_output=True,text=True)
    assert result.returncode==2 and 'No API called' in result.stderr
