from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator
from typing import Literal


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
    answer_model: str = 'qwen3.7-plus'
    embedding_model: str = 'text-embedding-v4'
    rerank_model: str = 'qwen3-rerank'
    embedding_dimensions: int = 1024
    model_timeout_seconds: float = 30
    asr_send_timeout_seconds: float = Field(default=5, gt=0, le=60)
    aliyun_asr_batch_enabled: bool = True
    aliyun_asr_batch_ms: Literal[20,40,60,80,100,200] = 100
    aliyun_asr_batch_max_wait_ms: int = Field(default=100, ge=1, le=200)
    audio_queue_warning_ms: int = Field(default=1500, ge=20, le=30000)
    audio_queue_high_water_ms: int = Field(default=3000, ge=40, le=30000)
    audio_queue_max_ms: int = Field(default=8000, ge=60, le=30000)
    browser_audio_buffer_warning_ms: int = Field(default=1500, ge=20, le=30000)
    browser_audio_buffer_max_ms: int = Field(default=8000, ge=40, le=30000)
    audio_archive_queue_max_ms: int = Field(default=8000, ge=20, le=30000)
    audio_max_total_buffer_bytes: int = Field(default=4194304, ge=65536, le=16777216)
    audio_process_max_buffer_bytes: int = Field(default=16777216, ge=65536, le=134217728)
    processing_backlog_warning: int = Field(default=100, ge=1, le=10000)
    processing_backlog_degraded: int = Field(default=200, ge=2, le=20000)
    processing_backlog_hard_limit: int = Field(default=5000, ge=3, le=50000)
    asr_diagnostics_enabled: bool = True
    event_loop_lag_sample_ms: int = Field(default=500, ge=100, le=5000)
    asr_recovery_enabled: bool = False
    asr_recovery_buffer_ms: int = Field(default=30000, ge=1000, le=60000)
    asr_recovery_max_attempts: int = Field(default=3, ge=0, le=3)
    asr_recovery_max_duration_seconds: int = Field(default=30, ge=1, le=60)
    asr_recovery_backoff_initial_ms: int = Field(default=1000, ge=100, le=5000)
    asr_recovery_backoff_max_ms: int = Field(default=4000, ge=100, le=10000)
    asr_recovery_auto_replay_uncertain: bool = False
    asr_provider: str = 'aliyun'
    soniox_api_key: str = Field(default='', repr=False)
    asr_event_timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    asr_finish_timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    # INCREMENTAL_TRANSLATION_ENABLED=false restores the legacy preview path.
    incremental_translation_enabled: bool = True
    preview_min_stable_seconds: float = Field(default=.25, ge=0, le=5)
    preview_interval_seconds: float = Field(default=.5, ge=.2, le=10)
    # Unconfirmed, continuously rewritten text needs a conservative fallback.
    preview_max_wait_seconds: float = Field(default=2.4, ge=.5, le=10)
    preview_min_words: int = Field(default=2, ge=1, le=20)
    preview_min_change_chars: int = Field(default=4, ge=1, le=100)
    preview_max_chars: int = Field(default=2048, ge=64, le=8192)
    preview_max_sentences: int = Field(default=64, ge=1, le=256)
    preview_ttl_seconds: float = Field(default=30, ge=5, le=120)
    preview_concurrency: int = Field(default=1, ge=1, le=2)
    preview_calls_per_minute: int = Field(default=40, ge=1, le=120)
    preview_reuse_ttl_seconds: float = Field(default=15, ge=1, le=60)
    translation_poll_seconds: float = Field(default=.1, ge=.05, le=.6)
    translation_emit_seconds: float = Field(default=.1, ge=.1, le=1)
    upload_max_mb: int = 40
    capture_max_seconds: int = 6300
    audio_retention_days: int = 7
    audio_max_queue_frames: int = 100  # Deprecated compatibility input; byte + node budgets govern admission.
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

    @model_validator(mode='after')
    def validate_audio_limits(self):
        if not self.audio_queue_warning_ms < self.audio_queue_high_water_ms < self.audio_queue_max_ms:
            raise ValueError('AUDIO_QUEUE_WARNING_MS < AUDIO_QUEUE_HIGH_WATER_MS < AUDIO_QUEUE_MAX_MS required')
        if self.browser_audio_buffer_warning_ms >= self.browser_audio_buffer_max_ms:
            raise ValueError('BROWSER_AUDIO_BUFFER_WARNING_MS must be below MAX_MS')
        if not self.processing_backlog_warning < self.processing_backlog_degraded < self.processing_backlog_hard_limit:
            raise ValueError('PROCESSING_BACKLOG_WARNING < DEGRADED < HARD_LIMIT required')
        if self.audio_process_max_buffer_bytes < self.audio_max_total_buffer_bytes:
            raise ValueError('Process PCM budget must cover one session budget')
        if self.asr_recovery_backoff_initial_ms > self.asr_recovery_backoff_max_ms:
            raise ValueError('Recovery initial backoff exceeds maximum')
        if self.asr_recovery_enabled or self.asr_recovery_auto_replay_uncertain:
            raise ValueError('ASR recovery is not verified: keep ASR_RECOVERY_ENABLED and AUTO_REPLAY_UNCERTAIN=false')
        return self

    def audio_runtime(self):
        # Public allowlist; credentials / endpoints / filesystem paths never leave the server.
        return dict(browser_buffer_warning_ms=self.browser_audio_buffer_warning_ms,
            browser_buffer_max_ms=self.browser_audio_buffer_max_ms,
            server_queue_warning_ms=self.audio_queue_warning_ms,
            server_queue_high_water_ms=self.audio_queue_high_water_ms,server_queue_max_ms=self.audio_queue_max_ms,
            archive_queue_max_ms=self.audio_archive_queue_max_ms,aliyun_batch_ms=self.aliyun_asr_batch_ms,
            aliyun_batch_enabled=self.aliyun_asr_batch_enabled,recovery_enabled=False,
            recovery_buffer_ms=self.asr_recovery_buffer_ms)

    @property
    def origins(self):
        return {v.strip().rstrip('/') for v in self.allowed_origins.split(',') if v.strip()}


@lru_cache
def get_settings():
    return Settings()


settings = get_settings()
