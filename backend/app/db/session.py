"""Database engines: async (API) and sync (Celery worker), both on psycopg 3."""

import asyncio
import weakref
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

# Async engines are bound to an event loop; keep one per loop (tests may run a second loop).
_async_engines: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, AsyncEngine]" = (
    weakref.WeakKeyDictionary()
)
_sync_engine: Engine | None = None
_sync_factory: sessionmaker[Session] | None = None


def get_async_engine() -> AsyncEngine:
    loop = asyncio.get_running_loop()
    engine = _async_engines.get(loop)
    if engine is None:
        engine = create_async_engine(
            get_settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=10
        )
        _async_engines[loop] = engine
    return engine


def async_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_async_engine(), expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with async_session_factory()() as session:
        yield session


async def dispose_async_engine() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    engine = _async_engines.pop(loop, None)
    if engine is not None:
        await engine.dispose()


def get_sync_engine() -> Engine:
    global _sync_engine, _sync_factory
    if _sync_engine is None:
        _sync_engine = create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=5)
        _sync_factory = sessionmaker(_sync_engine, expire_on_commit=False)
    return _sync_engine


def reset_sync_engine() -> None:
    """Called after fork in Celery prefork children so connections are not shared."""
    global _sync_engine, _sync_factory
    if _sync_engine is not None:
        _sync_engine.dispose(close=False)
    _sync_engine = None
    _sync_factory = None


@contextmanager
def sync_session() -> Iterator[Session]:
    get_sync_engine()
    assert _sync_factory is not None
    with _sync_factory() as session:
        yield session
