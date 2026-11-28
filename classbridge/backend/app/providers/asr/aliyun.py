import re
from contextlib import aclosing
from urllib.parse import urlparse
from app.providers.aliyun import AliyunProvider, ProviderError


class AliyunASRAdapter(AliyunProvider):
    supports_final_revisions = False
    """ASR-only boundary; keep the proven transport unchanged."""
    def ensure_configured(self):
        super().ensure_configured(protocols=('ws',))
        url=urlparse(self.base('ws'))
        try:port=url.port
        except ValueError as exc:raise ProviderError('invalid_endpoint','ASR 接入地址端口无效。') from exc
        allowed=url.hostname=='dashscope.aliyuncs.com' or re.fullmatch(
            r'[a-zA-Z0-9-]+\.[a-zA-Z0-9-]+\.maas\.aliyuncs\.com',url.hostname or '')
        if not allowed or port not in (None,443) or url.path!='/api-ws/v1/inference':
            raise ProviderError('invalid_endpoint','ASR 接入地址必须使用受信任的阿里云官方 WebSocket Host 和路径。')

    async def stream_asr(self,audio,**kwargs):
        self.ensure_configured()
        options=self.value('asr_options',{})
        if not self.value('asr_effective_resolved',False):
            # Legacy entry point uses the same precedence as live capture.
            from app.services.asr_config_resolver import resolve_effective_asr_config
            effective=resolve_effective_asr_config(self.config, preferences={
                'asr_context':kwargs.get('context') or '',
                'asr_acoustic_profile':'near' if kwargs.get('vad_model')=='near_meeting_16k' else 'far'})
            if options.get('context') is not None:kwargs['context']=effective.context
            if options.get('vad_model') is not None:kwargs['vad_model']=effective.vad_model
            if self.value('asr_language_hints',None) is not None:kwargs['language_hints']=list(effective.language_hints)
        async with aclosing(super().stream_asr(audio,**kwargs)) as stream:
            async for event in stream:yield event
