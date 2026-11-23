from app.config import settings
from app.providers.aliyun import AliyunProvider, ProviderError
from .base import ASRProvider


def create_asr_provider(config=None) -> ASRProvider:
    config = settings if config is None else config
    name = getattr(config,'asr_provider','aliyun')
    if name == 'aliyun':
        # Structural adapter: preserve the proven handshake, event mapper and
        # cancellation implementation rather than duplicating that transport.
        return AliyunProvider(config)
    raise ProviderError('unsupported_asr_provider','所选 ASR 服务尚未实现或不受支持；请配置 ASR_PROVIDER=aliyun。')
