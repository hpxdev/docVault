"""Redis caches. Chat answers are never cached (see README "Caching")."""

import hashlib
import json
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


QEMB_TTL_S = 7 * 24 * 3600


def normalize_query(text: str) -> str:
    return " ".join(text.lower().split())


def query_embedding_key(model: str, query: str) -> str:
    digest = hashlib.sha256(normalize_query(query).encode()).hexdigest()
    return f"qemb:{model}:{digest}"


async def cached_query_embedding(ai, query: str, *, message_id) -> tuple[list[float], bool]:
    """Query embeddings are cached for 7 days. The key includes the embedding model, so changing
    the model never reuses old vectors. Returns (vector, cache_hit)."""
    key = query_embedding_key(ai.embeddings.name, query)
    client = async_cache()
    try:
        cached = await client.get(key)
    except Exception:
        cached = None
        log.warning("query embedding cache read failed")
    if cached:
        return json.loads(cached), True
    vector = await ai.embed_query(query, message_id=message_id)
    try:
        await client.set(key, json.dumps(vector), ex=QEMB_TTL_S)
    except Exception:
        log.warning("query embedding cache write failed")
    return vector, False
