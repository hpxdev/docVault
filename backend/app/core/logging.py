"""Structured JSON logging (stdlib only).

Log records carry IDs, counts and timings. Never pass full document text or full prompts.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Extra attributes copied into the JSON line when present on a record.
_EXTRA_KEYS = (
    "document_id",
    "session_id",
    "message_id",
    "stage",
    "duration_ms",
    "attempt",
    "status_code",
    "method",
    "path",
    "error_code",
    "purpose",
    "model",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "task_id",
    "count",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = getattr(record, "request_id", None) or request_id_var.get()
        if rid:
            payload["request_id"] = rid
        for key in _EXTRA_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    # sys.__stdout__: Celery replaces sys.stdout with a logging proxy, which would loop.
    handler = logging.StreamHandler(sys.__stdout__)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Uvicorn's access log is replaced by our request middleware log line.
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
