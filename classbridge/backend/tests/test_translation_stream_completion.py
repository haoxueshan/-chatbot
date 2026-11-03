import httpx
import pytest
from app.providers.aliyun import AliyunProvider,ProviderError
from test_providers import install_http,config


@pytest.mark.asyncio
@pytest.mark.parametrize('ending', ['', 'data: {"choices":[{"finish_reason":"length","delta":{}}]}\n\ndata: [DONE]\n\n'])
async def test_incomplete_or_truncated_stream_cannot_be_reused(monkeypatch,ending):
    install_http(monkeypatch,lambda request:httpx.Response(200,text='data: {"choices":[{"delta":{"content":"半句"}}]}\n\n'+ending))
    with pytest.raises(ProviderError,match='未正常结束'):
        await AliyunProvider(config()).translate('source',require_complete=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('ending', ['data: [DONE]\n\n','data: {"choices":[{"finish_reason":"stop","delta":{}}]}\n\n'])
async def test_normal_stream_end_is_required_for_complete_result(monkeypatch,ending):
    install_http(monkeypatch,lambda request:httpx.Response(200,text='data: {"choices":[{"delta":{"content":"完整译文"}}]}\n\n'+ending))
    assert await AliyunProvider(config()).translate('source',require_complete=True)=='完整译文'
