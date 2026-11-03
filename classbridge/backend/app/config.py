from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(Path(__file__).resolve().parents[2]/'.env'), extra='ignore', case_sensitive=False)
    app_name: str = 'ClassBridge · 语音理解工作台'
    environment: str = 'development'
    database_url: str = 'sqlite:///./data/classbridge.db'
    redis_url: str = 'redis://localhost:6379/0'
    task_mode: str = 'local'
    secret_key: str = 'development-only-change-before-deployment'
    cookie_secure: bool = False
    allowed_origins: str = 'http://localhost,http://127.0.0.1,http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000'
    data_dir: str = './data'
    public_base_url: str = 'http://localhost:8000'
    dashscope_api_key: str = Field(default='', repr=False)
    dashscope_workspace_id: str = ''
    dashscope_region: str = 'cn-beijing'
    openai_base_url: str = ''
    asr_ws_url: str = ''
    dashscope_base_url: str = ''
    asr_model: str = 'qwen-audio-3.1-asr-flash-streaming'
    filetrans_model: str = 'qwen-audio-3.1-asr-flash-filetrans'
    translation_model: str = 'qwen-mt-flash'
    summary_model: str = 'qwen3.7-flash'
    correction_model: str = 'qwen3.7-flash'
    answer_model: str = 'qwen3.7-plus'
    embedding_model: str = 'text-embedding-v4'
    rerank_model: str = 'qwen3-rerank'
    embedding_dimensions: int = 1024
    model_timeout_seconds: float = 30
    asr_send_timeout_seconds: float = 5
    # Opt-in experiment. False preserves the existing recognition/translation path.
    incremental_translation_enabled: bool = False
    preview_min_stable_seconds: float = Field(default=.35, ge=0, le=5)
    preview_interval_seconds: float = Field(default=1.2, ge=.2, le=10)
    preview_max_wait_seconds: float = Field(default=2.4, ge=.5, le=10)
    preview_min_words: int = Field(default=3, ge=1, le=20)
    preview_min_change_chars: int = Field(default=6, ge=1, le=100)
    preview_max_chars: int = Field(default=2048, ge=64, le=8192)
    preview_max_sentences: int = Field(default=64, ge=1, le=256)
    preview_ttl_seconds: float = Field(default=30, ge=5, le=120)
    preview_concurrency: int = Field(default=1, ge=1, le=2)
    preview_calls_per_minute: int = Field(default=20, ge=1, le=120)
    preview_reuse_ttl_seconds: float = Field(default=15, ge=1, le=60)
    translation_poll_seconds: float = Field(default=.1, ge=.05, le=.6)
    translation_emit_seconds: float = Field(default=.25, ge=.1, le=1)
    upload_max_mb: int = 40
    capture_max_seconds: int = 6300
    audio_retention_days: int = 7
    audio_max_queue_frames: int = 100
    summary_interval_seconds: int = 180
    storage_backend: str = 'local'
    s3_endpoint_url: str = ''
    s3_bucket: str = ''
    s3_region: str = 'us-east-1'
    s3_access_key_id: str = Field(default='', repr=False)
    s3_secret_access_key: str = Field(default='', repr=False)
    oss_endpoint: str = ''
    oss_bucket: str = ''
    oss_region: str = 'cn-beijing'
    oss_access_key_id: str = Field(default='', repr=False)
    oss_access_key_secret: str = Field(default='', repr=False)

    @property
    def origins(self):
        return {v.strip().rstrip('/') for v in self.allowed_origins.split(',') if v.strip()}


@lru_cache
def get_settings():
    return Settings()


settings = get_settings()
