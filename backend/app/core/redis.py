"""Redis clients.

- `REDIS_URL` (db 0): Celery broker; queue depth is read from here.
- `CACHE_REDIS_URL` (db 1): caches, spend total, worker heartbeat, pub/sub status events.
Redis holds no source-of-truth data: losing it loses no documents or history.
"""

import asyncio
import weakref
from functools import lru_cache

import redis
import redis.asyncio as aioredis

from app.core.config import get_settings

_ClientMap = dict[str, aioredis.Redis]
_async_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _ClientMap]" = (
    weakref.WeakKeyDictionary()
)


def _async_client(url: str) -> aioredis.Redis:
    loop = asyncio.get_running_loop()
    per_loop = _async_clients.setdefault(loop, {})
    client = per_loop.get(url)
    if client is None:
        client = aioredis.from_url(url, decode_responses=True, health_check_interval=30)
        per_loop[url] = client
    return client


def async_cache() -> aioredis.Redis:
    return _async_client(get_settings().cache_redis_url)


def async_broker() -> aioredis.Redis:
    return _async_client(get_settings().redis_url)


@lru_cache
def sync_cache() -> redis.Redis:
    return redis.Redis.from_url(get_settings().cache_redis_url, decode_responses=True)


async def close_async_clients() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for client in _async_clients.pop(loop, {}).values():
        await client.aclose()


HEARTBEAT_KEY = "worker:heartbeat"
HEARTBEAT_TTL_S = 30
