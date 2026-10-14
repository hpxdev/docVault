"""Application settings, loaded from environment variables (and `.env` when present)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # AI
    ai_provider: Literal["openai", "fake"] = "openai"
    openai_api_key: SecretStr | None = None
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    ai_spend_limit_usd: float = 0.50
    ai_max_retries: int = Field(default=3, ge=0, le=10)

    # Infra
    database_url: str = "postgresql+psycopg://vault:vault@db:5432/vault"
    redis_url: str = "redis://redis:6379/0"
    cache_redis_url: str = "redis://redis:6379/1"
    storage_dir: str = "/data/storage"
    worker_concurrency: int = 2
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"

    # Limits & RAG tuning
    max_upload_mb: int = 25
    max_pages: int = 300
    max_files_per_upload: int = 10
    chunk_tokens: int = 800
    chunk_overlap_tokens: int = 100
    retrieval_top_k: int = 8
    insights_single_pass_max_tokens: int = 60000

    # Dev / tests
    run_live_ai_tests: bool = False
    debug_prompts: bool = False

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def _blank_key_is_none(cls, v: object) -> object:
        # An empty value followed by an inline comment reaches us as "# ..." via Compose.
        if isinstance(v, str) and (not v.strip() or v.strip().startswith("#")):
            return None
        return v

    @field_validator("embedding_dimensions")
    @classmethod
    def _dims_match_schema(cls, v: int) -> int:
        # The chunks.embedding column is vector(1536); changing it needs a migration.
        if v != 1536:
            raise ValueError("EMBEDDING_DIMENSIONS must be 1536 (matches the database column)")
        return v

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ai_mode(self) -> str:
        return self.ai_provider

    @property
    def ai_configured(self) -> bool:
        return self.ai_provider == "fake" or self.openai_api_key is not None

    @property
    def chat_model_name(self) -> str:
        return "fake" if self.ai_provider == "fake" else self.openai_chat_model

    @property
    def embedding_model_name(self) -> str:
        return "fake" if self.ai_provider == "fake" else self.openai_embedding_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
