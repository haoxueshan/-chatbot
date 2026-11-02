import pytest
from test_core import factory,client
from app.services.asr_options import asr_vocabulary_report
from app.providers.aliyun import AliyunProvider,ProviderError

def test_legacy_empty_source_falls_back_and_nfc_deduplicates():
    report=asr_vocabulary_report([{'source':'','term':'작업기억','target':'工作记忆'},'작업기억',{'source':'RAG','target':'检索增强生成'}],4)
    assert report['vocabulary']=={'작업기억':4,'RAG':4}
    assert report['skipped'][0]['reason']=='重复原词，已合并'

def test_old_preferences_defaults_and_saved_audio_modes(client):
    old=client.get('/api/settings').json()
    assert old['asr_acoustic_profile']=='far' and old['audio_processing_mode']=='standard'
    for field,value in [('asr_acoustic_profile','bad'),('audio_processing_mode','boost')]:
        assert client.patch('/api/settings',json={field:value}).status_code==422
    assert client.patch('/api/settings',json={'asr_acoustic_profile':'near','audio_processing_mode':'natural'}).status_code==200
    saved=client.get('/api/settings').json()
    assert saved['asr_acoustic_profile']=='near' and saved['audio_processing_mode']=='natural'

@pytest.mark.asyncio
async def test_invalid_vad_is_rejected_before_cloud_connection():
    async def audio():yield bytes(640)
    with pytest.raises(ProviderError,match='拾音场景'):
        async for _ in AliyunProvider().stream_asr(audio(),vad_model='invented'):pass
