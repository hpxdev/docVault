"""Shared API helpers: pagination params and OpenAPI error examples."""

from typing import Annotated, Any

from fastapi import Query

Limit = Annotated[int, Query(ge=1, le=100, description="Page size (max 100)")]
Offset = Annotated[int, Query(ge=0, description="Items to skip")]

_ERROR_EXAMPLES: dict[int, tuple[str, str]] = {
    400: ("TOO_MANY_FILES", "At most 10 files per request (12 sent)."),
    404: ("NOT_FOUND", "Document not found."),
    409: ("DOCUMENTS_NOT_READY", "Some documents in scope are not chat-ready yet."),
    413: ("FILE_TOO_LARGE", "The file exceeds the 25 MB limit."),
    415: ("UNSUPPORTED_FILE_TYPE", "Only PDF, DOCX, TXT and Markdown files are supported."),
    422: ("VALIDATION_ERROR", "Invalid request."),
    429: ("AI_BUDGET_EXCEEDED", "The AI spend cap of $0.50 has been reached."),
    503: ("AI_PROVIDER_UNAVAILABLE", "The AI provider is unavailable; try again shortly."),
}


def error_responses(*codes: int, overrides: dict[int, tuple[str, str]] | None = None) -> dict:
    out: dict[int, Any] = {}
    for status in codes:
        code, message = (overrides or {}).get(status) or _ERROR_EXAMPLES[status]
        out[status] = {
            "description": code,
            "content": {
                "application/json": {
                    "example": {
                        "error": {"code": code, "message": message, "details": {}},
                        "request_id": "4b8f0c2d9e1a4f6b8c3d2e1f0a9b8c7d",
                    }
                }
            },
        }
    return out
