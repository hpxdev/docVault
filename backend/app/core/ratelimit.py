"""Per-client rate limits: fixed one-minute windows counted in Redis.

Two groups, applied as route dependencies: `upload` (uploads, new versions, reprocessing) and
`ai` (questions, custom summaries, comparisons). The client is identified by its socket address;
`X-Forwarded-For` is ignored because it can be forged (behind a trusted proxy, key on the
proxy's header instead). A fixed window can let up to twice the limit through around a window
boundary; that is acceptable for abuse protection, and the AI spend cap still bounds cost. If
Redis is unavailable the request is allowed (logged): availability over strictness.
"""

import logging
import time
from typing import Literal

from fastapi import Depends, Request, Response
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.redis import async_cache

log = logging.getLogger(__name__)

WINDOW_S = 60
Group = Literal["ai", "upload"]
_LABEL = {"ai": "AI requests", "upload": "uploads and reprocessing"}
_INCR = (
    "local n = redis.call('incr', KEYS[1]) "
    "if n == 1 then redis.call('expire', KEYS[1], ARGV[1]) end return n"
)


def _limit(group: Group) -> int:
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return 0
    return (
        settings.rate_limit_ai_per_minute
        if group == "ai"
        else settings.rate_limit_upload_per_minute
    )


def rate_limit(group: Group):
    async def check(request: Request, response: Response) -> None:
        limit = _limit(group)
        if limit <= 0:
            return
        client = request.client.host if request.client else "unknown"
        now = time.time()
        window = int(now // WINDOW_S)
        reset = max(1, int((window + 1) * WINDOW_S - now))
        try:
            count = int(
                await async_cache().eval(_INCR, 1, f"rl:{group}:{client}:{window}", WINDOW_S + 5)
            )
        except RedisError:
            log.warning("rate limiter unavailable; request allowed", extra={"purpose": group})
            return
        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(max(0, limit - count)),
            "X-RateLimit-Reset": str(reset),
        }
        if count > limit:
            log.info("rate limited", extra={"purpose": group, "count": count})
            raise AppError(
                f"Too many {_LABEL[group]}: at most {limit} per minute. Try again in {reset} s.",
                code="RATE_LIMITED",
                status_code=429,
                details={
                    "group": group,
                    "limit": limit,
                    "window_s": WINDOW_S,
                    "retry_after_s": reset,
                },
                headers={**headers, "Retry-After": str(reset)},
            )
        response.headers.update(headers)

    return Depends(check)


RATE_LIMITED_EXAMPLE = (
    "RATE_LIMITED",
    "Too many AI requests: at most 20 per minute. Try again in 12 s.",
)
