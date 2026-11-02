from fastapi import APIRouter, Depends
from typing import Literal
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession
from app.api.auth import current_user
from app.db import get_db
from app.config import settings
from app.models import User
from app.services.asr_options import ASRLanguageMode, asr_vocabulary_report

router = APIRouter(prefix='/api/settings', tags=['Settings'])


class Preferences(BaseModel):
    theme: str = 'light'
    subtitle_size: int = Field(default=24, ge=18, le=44)
    show_original: bool = True
    target_language: str = 'zh-CN'
    asr_language_mode: ASRLanguageMode = 'auto'
    asr_hotword_weight: Literal[2,3,4] = 2
    asr_context: str = Field(default='',max_length=400)
    asr_assist_enabled: bool = False
    asr_acoustic_profile: Literal['far','near'] = 'far'
    audio_processing_mode: Literal['standard','natural'] = 'standard'
    terms: list[dict | str] = Field(default_factory=list, max_length=200)
    retain_audio: bool = False


@router.get('')
def read_settings(user: User = Depends(current_user)):
    preferences={**Preferences().model_dump(), **(user.settings or {})}
    report=asr_vocabulary_report(preferences.get('terms',[]),preferences['asr_hotword_weight'])
    from app.providers.aliyun import AliyunProvider, ProviderError
    config_error=None
    try:AliyunProvider().ensure_configured()
    except ProviderError as exc:config_error={'code':exc.code,'message':exc.message}
    return {**preferences, 'asr_terms_status':{'enabled_count':len(report['vocabulary']),'skipped':report['skipped']},
      'real_ready': config_error is None, 'configuration_error':config_error,
      'model_status': config_error['code'] if config_error else 'configured_unverified',
      'api_key_configured': bool(settings.dashscope_api_key), 'workspace_configured': bool(settings.dashscope_workspace_id),
      'models': {'asr':settings.asr_model,'translation':settings.translation_model,'summary':settings.summary_model,'correction':settings.correction_model,'answer':settings.answer_model,'embedding':settings.embedding_model,'rerank':settings.rerank_model},
      'capture_max_minutes':105,'audio_retention_days':settings.audio_retention_days,'region':settings.dashscope_region}


@router.patch('')
def update_settings(body: Preferences, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    user.settings = {**(user.settings or {}), **body.model_dump(exclude_unset=True)}
    db.add(user); db.commit()
    return read_settings(user)
