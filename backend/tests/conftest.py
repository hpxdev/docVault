"""Test harness: real Postgres + pgvector and Redis (compose.test.yml), fake AI providers."""

import os
import shutil
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import redis
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

os.environ.setdefault("AI_PROVIDER", "fake")
os.environ.setdefault("STORAGE_DIR", "/tmp/vault-storage")

from app.core.config import get_settings  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]

TABLES = [
    "message_citations",
    "messages",
    "chat_session_documents",
    "chat_sessions",
    "chunks",
    "document_insights",
    "document_segments",
    "processing_runs",
    "ai_calls",
    "documents",
]


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["skip_logging"] = True
    return cfg


def reset_schema(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    settings = get_settings()
    reset_schema(settings.database_url)
    command.upgrade(alembic_config(), "head")
    yield


@pytest.fixture(autouse=True)
def _clean_state() -> Iterator[None]:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
    engine.dispose()
    for url in (settings.redis_url, settings.cache_redis_url):
        redis.Redis.from_url(url).flushdb()
    shutil.rmtree(settings.storage_dir, ignore_errors=True)
    Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture
def app():
    from app.main import create_app

    return create_app()


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        yield c
