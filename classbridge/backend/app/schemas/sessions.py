from typing import Literal
from pydantic import BaseModel, Field
from app.services.translation_languages import SupportedTargetLanguage


class CreateSession(BaseModel):
    title: str = Field(default='未命名课堂', min_length=1, max_length=250)
    kind: Literal['classroom', 'meeting', 'interview'] = 'classroom'
    mode: Literal['demo', 'real'] = 'demo'
    retain_audio: bool = False
    target_language: SupportedTargetLanguage = 'zh-CN'
    asr_profile_id: str | None = Field(default=None,max_length=36)
    folder_id: str | None = Field(default=None, min_length=1, max_length=36)


class ExportRequest(BaseModel):
    format: Literal['md', 'txt', 'pdf'] = 'pdf'
