"""Redis caches. Chat answers are never cached (see README "Caching")."""

import logging

from app.core.redis import async_cache

log = logging.getLogger(__name__)

METRICS_PREFIX = "metrics:"
METRICS_TTL_S = 15


async def invalidate_metrics() -> None:
    try:
        client = async_cache()
        keys = [k async for k in client.scan_iter(match=f"{METRICS_PREFIX}*", count=100)]
        if keys:
            await client.delete(*keys)
    except Exception:
        log.warning("metrics cache invalidation failed")
