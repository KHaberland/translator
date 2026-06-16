from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mock_ai_enabled: bool = False
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = ""
    openai_timeout_seconds: float = 60
    openai_max_retries: int = 2
    max_batch_chars: int = 8000
    max_batch_blocks: int = 30
    max_file_size_mb: int = 25
    upload_dir: Path = Field(default=Path("uploads"))
    output_dir: Path = Field(default=Path("outputs"))
    tmp_dir: Path = Field(default=Path("tmp"))

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


def ensure_storage_dirs(settings: Settings | None = None) -> None:
    current_settings = settings or get_settings()
    for directory in (
        current_settings.upload_dir,
        current_settings.output_dir,
        current_settings.tmp_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
