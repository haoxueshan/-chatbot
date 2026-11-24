from dataclasses import dataclass
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.providers.aliyun import ProviderError
from .aliyun import AliyunASRAdapter


class AliyunOptions(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    context: str | None=Field(default=None,max_length=400)
    vad_model: Literal['near_meeting_16k','far_field_meeting_16k'] | None=None


class SonioxOptions(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    context: str | None=Field(default=None,max_length=4000)
    terms: list[str]=Field(default_factory=list,max_length=200)
    language_hints_strict: bool=False
    max_endpoint_delay_ms: int=Field(default=2000,ge=500,le=3000)


class NoOptions(BaseModel):
    model_config=ConfigDict(extra='forbid')


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    name: str
    default_model: str
    credential_ref: str
    adapter: type | None
    options: type[BaseModel]
    languages: tuple[str,...]=('ko','en')

    def public(self):
        return {'id':self.id,'name':self.name,'default_model':self.default_model,
            'credential_ref':self.credential_ref,'implemented':self.adapter is not None,
            'status':'已接入 · 账号权限需实际验证' if self.adapter else '尚未接入',
            'capabilities':{'realtime':self.adapter is not None,'language_hints':list(self.languages),
                'timestamps':'provider_tokens' if self.id=='soniox' else ('provider_sentence' if self.adapter else None),
                'pcm':'pcm_s16le/16000/mono' if self.adapter else None},
            'options_schema':self.options.model_json_schema()}


REGISTRY={}


def register(definition):
    if definition.id in REGISTRY:raise ValueError('ASR provider already registered')
    REGISTRY[definition.id]=definition


def get_provider(name):
    if name not in REGISTRY:raise ProviderError('unsupported_asr_provider','未注册的 ASR 供应商。')
    return REGISTRY[name]


register(ProviderDefinition('aliyun','阿里云 Qwen','qwen-audio-3.1-asr-flash-streaming','DASHSCOPE_API_KEY',AliyunASRAdapter,AliyunOptions))
from .soniox import SonioxASRAdapter
register(ProviderDefinition('soniox','Soniox','stt-rt-v6','SONIOX_API_KEY',SonioxASRAdapter,SonioxOptions))
register(ProviderDefinition('elevenlabs','ElevenLabs Scribe v3 Live','scribe-v3-live','ELEVENLABS_API_KEY',None,NoOptions))
register(ProviderDefinition('deepgram','Deepgram Nova-3','nova-3','DEEPGRAM_API_KEY',None,NoOptions))
