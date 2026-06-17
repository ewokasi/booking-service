from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://booking:booking@localhost:5432/booking"
    alembic_database_url: str = "postgresql://booking:booking@localhost:5432/booking"

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    worker_failure_rate: float = Field(default=0.15, ge=0.0, le=1.0)
    worker_max_retries: int = Field(default=3, ge=0)
    worker_retry_backoff: int = Field(default=2, ge=1)

    rate_limit_create_booking: str = "10/minute"

    celery_task_always_eager: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
