from types import SimpleNamespace
from app.config import settings
from app.providers.aliyun import ProviderError
from .base import ASRProvider
from .registry import get_provider


def create_asr_provider(config=None, *, snapshot=None) -> ASRProvider:
    config = settings if config is None else config
    if snapshot is not None:
        values=config.model_dump() if hasattr(config,'model_dump') else vars(config).copy()
        definition=get_provider(snapshot['provider'])
        if snapshot['credential_ref']!=definition.credential_ref:
            raise ProviderError('invalid_credential_ref','密钥引用不属于该供应商。')
        values.update(snapshot.get('runtime',{}))
        values.update(asr_provider=snapshot['provider'],asr_model=snapshot['model_id'],
            asr_options=snapshot['provider_options'],asr_language_hints=snapshot['language_hints'])
        config=SimpleNamespace(**values)
    definition=get_provider(getattr(config,'asr_provider','aliyun'))
    if definition.adapter is None:raise ProviderError('unsupported_asr_provider','该 ASR 供应商尚未接入。')
    return definition.adapter(config)
