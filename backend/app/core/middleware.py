"""Request-ID + access-log middleware (pure ASGI, so streaming responses are not buffered)."""

import json
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.errors import error_body
from app.core.logging import request_id_var

log = logging.getLogger("app.request")

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _upload_too_large(scope: Scope) -> bool:
    """Cheap pre-check on Content-Length before the multipart body is parsed. Per-file limits are
    still enforced while streaming each file."""
    if scope.get("method") != "POST" or not scope.get("path", "").endswith("/documents"):
        return False
    raw = dict(scope.get("headers") or []).get(b"content-length")
    if not raw or not raw.isdigit():
        return False
    settings = get_settings()
    limit = settings.max_upload_bytes * settings.max_files_per_upload + 1024 * 1024
    return int(raw) > limit


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_holder = {"status": 500, "started": False}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                status_holder["started"] = True
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            if _upload_too_large(scope):
                body = json.dumps(
                    error_body("FILE_TOO_LARGE", "The request body exceeds the upload limit.")
                ).encode()
                await send_wrapper(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
            await self.app(scope, receive, send_wrapper)
        except Exception:
            log.exception("unhandled error")
            if not status_holder["started"]:
                body = json.dumps(
                    error_body("INTERNAL_ERROR", "An unexpected error occurred.")
                ).encode()
                await send_wrapper(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": body})
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            path = scope.get("path", "")
            if not path.endswith("/health"):
                log.info(
                    "request",
                    extra={
                        "method": scope.get("method"),
                        "path": path,
                        "status_code": status_holder["status"],
                        "duration_ms": duration_ms,
                    },
                )
            request_id_var.reset(token)
