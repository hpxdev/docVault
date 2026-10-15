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
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")  # tests that need limits enable them

from app.core.config import get_settings  # noqa: E402
from app.workers import stages as _stages  # noqa: E402,F401  (registers pipeline stages)

BACKEND_DIR = Path(__file__).resolve().parents[1]

TABLES = [
    "message_citations",
    "messages",
    "chat_session_documents",
    "chat_sessions",
    "chunks",
    "document_insights",
    "document_summaries",
    "document_comparisons",
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


@pytest.fixture(autouse=True)
def enqueued(monkeypatch) -> list[tuple[str, str]]:
    """Record enqueued stages instead of sending them to Celery. Tests run stages explicitly."""
    calls: list[tuple[str, str]] = []
    from app.workers import dispatch

    monkeypatch.setattr(
        dispatch, "enqueue_stage", lambda stage, doc_id: calls.append((stage, str(doc_id)))
    )
    return calls


def run_queued(enqueued: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """Drain recorded tasks (including ones enqueued while draining), like a worker would."""
    from app.services.pipeline import execute_stage
    from app.workers import stages  # noqa: F401

    done = []
    while enqueued:
        stage, doc_id = enqueued.pop(0)
        outcome = execute_stage(stage, doc_id)
        done.append((stage, doc_id, outcome.result))
    return done


@pytest.fixture(autouse=True)
def _reset_ai():
    from app.ai import registry

    registry.clear_overrides()
    registry._fake_chat.cache_clear()
    registry._fake_embeddings.cache_clear()
    yield
    registry.clear_overrides()


@pytest.fixture
def fake_chat():
    """The shared FakeChatModel; push scripted outputs with `fake_chat.push(...)`."""
    from app.ai import registry

    return registry.get_chat_model()


@pytest.fixture
def fake_embeddings():
    from app.ai import registry

    return registry.get_embedding_model()
