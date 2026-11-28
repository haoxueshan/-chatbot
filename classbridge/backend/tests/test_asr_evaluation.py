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


@pytest.mark.asyncio
@pytest.mark.parametrize('change',[False,True])
async def test_comparison_uses_same_pcm_and_stops_before_next_task_on_change(tmp_path,change):
    from app.providers.asr.evaluation import compare_languages
    path=tmp_path/'compare.wav'
    def write(value):
        with wave.open(str(path),'wb') as wav:
            wav.setparams((1,2,16000,0,'NONE','not compressed'));wav.writeframes(value*801)
    write(b'\x01\0');calls=[];frames=[]
    class Provider:
        async def stream_asr(self,audio,*,on_ready,metrics,language_hints):
            calls.append(language_hints);await on_ready()
            frames.append(b''.join([frame async for frame in audio]))
            if False:yield {}
    def factory():
        if change and calls:pytest.fail('Changed input must prevent the next task')
        return Provider()
    async def sleep(delay):pass
    # Modify between evaluations, after the first file handle has closed.
    import app.providers.asr.evaluation as module
    original=module.evaluate_wav
    async def evaluate(*args,**kwargs):
        result=await original(*args,**kwargs)
        if change:write(b'\x02\0')
        return result
    from unittest.mock import patch
    with patch.object(module,'evaluate_wav',evaluate):
        if change:
            with pytest.raises(RuntimeError,match='changed'):await compare_languages(factory,path,realtime=False)
            assert calls==[[]]
        else:
            reports=await compare_languages(factory,path,realtime=False)
            assert calls==[[],['ko','en'],['ko']]
            assert len(set(frames))==1 and len({r['pcm_sha256'] for r in reports.values()})==1


@pytest.mark.asyncio
async def test_evaluation_conflict_does_not_replace_final_or_fake_completion(tmp_path):
    path=tmp_path/'conflict.wav'
    with wave.open(str(path),'wb') as wav:
        wav.setparams((1,2,16000,0,'NONE','not compressed'));wav.writeframes(bytes(640))
    class Provider:
        async def stream_asr(self,audio,**kwargs):
            await kwargs['on_ready']()
            async for _ in audio:pass
            for text in ('RAG','RAG','wrong'):
                yield dict(sentence_id='1',text=text,final=True,start_ms=0,end_ms=20)
            yield dict(sentence_id='2',text='unconfirmed',final=False,start_ms=20,end_ms=None)
            yield dict(sentence_id='2',text='',final=True,start_ms=20,end_ms=20)
    report=await evaluate_wav(Provider(),path,reference='RAG',realtime=False)
    assert report['accuracy']['english_wer']==0
    assert report['duplicate_finals']==1 and report['conflicting_finals']==1
    assert report['final_segments']==1 and report['unconfirmed_sentences']==1
