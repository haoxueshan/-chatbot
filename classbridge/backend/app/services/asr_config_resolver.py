"""One immutable, credential-free interpretation of capture preferences."""
from dataclasses import dataclass
from app.services.asr_options import asr_language_hints, asr_vocabulary


@dataclass(frozen=True)
class EffectiveASRConfig:
    provider: str
    model_id: str
    language_hints: tuple[str, ...]
    language_hints_source: str
    context: str
    vad_model: str | None
    vad_model_source: str
    vocabulary: tuple[tuple[str, int], ...]
    vocabulary_weight: int
    pcm_batch_enabled: bool
    pcm_batch_ms: int
    send_timeout_seconds: float
    event_timeout_seconds: float
    finish_timeout_seconds: float
    vad_options: tuple[tuple[str, int | float | bool], ...]

    def arguments(self):
        return dict(vocabulary=dict(self.vocabulary), context=self.context,
                    language_hints=list(self.language_hints), vad_model=self.vad_model)

    def public_snapshot(self):
        # Counts only: no credentials, endpoints, context text or vocabulary text.
        return dict(provider=self.provider, model_id=self.model_id,
            language_hints=list(self.language_hints), language_hints_source=self.language_hints_source,
            vad_model=self.vad_model, vad_model_source=self.vad_model_source,
            context_chars=len(self.context), vocabulary_count=len(self.vocabulary), vocabulary_weight=self.vocabulary_weight,
            sample_rate=16000, channels=1, audio_format='pcm_s16le',
            pcm_batch_enabled=self.pcm_batch_enabled, pcm_batch_ms=self.pcm_batch_ms,
            send_timeout_seconds=self.send_timeout_seconds, event_timeout_seconds=self.event_timeout_seconds,
            finish_timeout_seconds=self.finish_timeout_seconds, **dict(self.vad_options))


def resolve_effective_asr_config(config, snapshot=None, preferences=None):
    snapshot = snapshot or {}
    preferences = preferences or {}
    provider = snapshot.get('provider', getattr(config, 'asr_provider', 'aliyun'))
    options = snapshot.get('provider_options', getattr(config, 'asr_options', {}))
    hints = snapshot.get('language_hints', getattr(config, 'asr_language_hints', None))
    source = snapshot.get('language_hints_source', 'model' if hints is not None else 'user')
    if hints is None:
        hints = asr_language_hints(preferences.get('asr_language_mode', 'auto')) or []
    context = options.get('context')
    if context is None:
        context = str(preferences.get('asr_context', '')).strip()[:400]
    context = context.strip()[:400 if provider == 'aliyun' else 4000]
    vad = options.get('vad_model')
    vad_source = 'model' if vad is not None else 'user'
    if vad is None:
        vad = 'near_meeting_16k' if preferences.get('asr_acoustic_profile') == 'near' else 'far_field_meeting_16k'
    if provider != 'aliyun':
        vad, vad_source = None, 'not_applicable'
    weight = preferences.get('asr_hotword_weight', 2)
    if type(weight) is not int or not 2 <= weight <= 4:
        weight = 2
    vocabulary = asr_vocabulary(preferences.get('terms', []), weight)
    if provider == 'soniox':
        vocabulary = {term: vocabulary.get(term, weight) for term in
                      list(dict.fromkeys([*vocabulary, *options.get('terms', [])]))[:200]}
    timeout = float(getattr(config, 'model_timeout_seconds', 30))
    return EffectiveASRConfig(provider, snapshot.get('model_id', getattr(config, 'asr_model', '')),
        tuple(hints), source, context, vad, vad_source, tuple(vocabulary.items()), weight,
        provider == 'aliyun' and getattr(config, 'aliyun_asr_batch_enabled', False),
        getattr(config, 'aliyun_asr_batch_ms', 100) if provider == 'aliyun' else 20,
        float(getattr(config, 'asr_send_timeout_seconds', 5)),
        float(getattr(config, 'asr_event_timeout_seconds', None) or timeout),
        float(getattr(config, 'asr_finish_timeout_seconds', None) or timeout),
        tuple((key,options[key]) for key in ('max_sentence_silence','multi_threshold_mode_enabled','speech_noise_threshold','keep_dialect')
              if provider=='aliyun' and options.get(key) is not None))
