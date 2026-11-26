from fastapi import APIRouter, Depends, HTTPException
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session as DBSession
from app.api.auth import current_user
from app.db import get_db
from app.config import settings
from app.models import User, ASRProfile
from app.services.asr_options import ASRLanguageMode, asr_vocabulary_report

from app.services.translation_languages import SupportedTargetLanguage, target_code

router = APIRouter(prefix='/api/settings', tags=['Settings'])


class Preferences(BaseModel):
    theme: str = 'light'
    subtitle_size: int = Field(default=24, ge=18, le=44)
    show_original: bool = True
    target_language: SupportedTargetLanguage = 'zh-CN'
    asr_language_mode: ASRLanguageMode = 'auto'
    asr_hotword_weight: Literal[2,3,4] = 2
    asr_context: str = Field(default='',max_length=400)
    asr_acoustic_profile: Literal['far','near'] = 'far'
    audio_processing_mode: Literal['standard','natural'] = 'standard'
    terms: list[dict | str] = Field(default_factory=list, max_length=200)
    retain_audio: bool = False

    @field_validator('terms')
    @classmethod
    def validate_term_languages(cls,terms):
        for term in terms:
            if isinstance(term,dict) and 'target_language' in term:target_code(term['target_language'])
        return terms


def translation_runtime_status():
    # Explicit allowlist: never serialize Settings wholesale (it contains secrets).
    fields = (
        'incremental_translation_enabled', 'preview_min_stable_seconds',
        'preview_interval_seconds', 'preview_max_wait_seconds', 'preview_min_words',
        'preview_min_change_chars', 'preview_concurrency', 'preview_calls_per_minute',
        'translation_poll_seconds', 'translation_emit_seconds',
    )
    return {
        **{name: getattr(settings, name) for name in fields},
        'model': settings.translation_model,
        'mode': 'incremental' if settings.incremental_translation_enabled else 'legacy',
        'budget_scope': 'process',
    }


@router.get('')
def read_settings(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    # Ignore retired/unknown JSON fields without validating old unrelated data.
    preferences={**Preferences().model_dump(), **{k:v for k,v in (user.settings or {}).items() if k in Preferences.model_fields}}
    try:target_code(preferences['target_language'])
    except ValueError as exc:raise HTTPException(422,detail=str(exc))
    report=asr_vocabulary_report(preferences.get('terms',[]),preferences['asr_hotword_weight'])
    from app.providers.aliyun import AliyunProvider, ProviderError
    from app.services.asr_profiles import bootstrap,configuration_status
    bootstrap(db,user);db.commit()
    profile=db.query(ASRProfile).filter_by(user_id=user.id,is_default=True).first()
    status=configuration_status(profile,user) if profile else {'valid':False,'code':'asr_default_missing','message':'尚未选择默认 ASR 模型。'}
    config_error=None if status['valid'] else {'code':status['code'],'message':status['message']}
    aliyun_error=None
    try:AliyunProvider().ensure_configured(protocols=('openai','native'))
    except ProviderError as exc:aliyun_error={'code':exc.code,'message':exc.message}
    return {**preferences, 'asr_terms_status':{'enabled_count':len(report['vocabulary']),'skipped':report['skipped']},
      'translation_runtime': translation_runtime_status(),
      'audio_runtime': settings.audio_runtime(),
      'real_ready': config_error is None, 'configuration_error':config_error,
      'default_asr_profile_id':profile.id if profile else None,'aliyun_services_error':aliyun_error,
      'model_status': config_error['code'] if config_error else 'configured_unverified',
      'api_key_configured': bool(settings.dashscope_api_key), 'workspace_configured': bool(settings.dashscope_workspace_id),
      'models': {'asr':profile.model_id if profile else settings.asr_model,'translation':settings.translation_model,'summary':settings.summary_model,'answer':settings.answer_model,'embedding':settings.embedding_model,'rerank':settings.rerank_model},
      'capture_max_minutes':105,'audio_retention_days':settings.audio_retention_days,'region':settings.dashscope_region}


@router.patch('')
def update_settings(body: Preferences, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    # Old clients may still submit the removed key: Pydantic ignores it, and a
    # normal save drops only that retired value, preserving speaker maps etc.
    user.settings = {**{k:v for k,v in (user.settings or {}).items() if k!='asr_assist_enabled'}, **body.model_dump(exclude_unset=True)}
    db.add(user); db.commit()
    return read_settings(user,db)
