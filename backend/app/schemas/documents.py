import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Document
from app.services.status import is_chat_ready

DOC_ID = "6f1c2a9e-3b7d-4c2e-9a51-0d8e4b7f2c10"


class ErrorInfo(BaseModel):
    code: str
    message: str | None = None


class StageStatuses(BaseModel):
    extract: str = Field(description="pending | running | succeeded | failed")
    index: str
    insights: str


class DocumentOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": DOC_ID,
                "filename": "falcon-plan.pdf",
                "file_type": "pdf",
                "mime_type": "application/pdf",
                "size_bytes": 48213,
                "sha256": "9f2b…",
                "status": "ready",
                "stages": {"extract": "succeeded", "index": "succeeded", "insights": "succeeded"},
                "chat_ready": True,
                "page_count": 5,
                "segment_count": 5,
                "char_count": 10342,
                "token_count": 2210,
                "warnings": [{"code": "EMPTY_PAGES", "pages": [4]}],
                "error": None,
                "category": "report",
                "version": 2,
                "version_group_id": DOC_ID,
                "is_latest": True,
                "created_at": "2026-10-15T09:12:03.120Z",
                "updated_at": "2026-10-15T09:12:09.880Z",
                "chat_ready_at": "2026-10-15T09:12:07.410Z",
                "ready_at": "2026-10-15T09:12:09.880Z",
            }
        }
    )

    id: uuid.UUID
    filename: str
    file_type: str
    mime_type: str
    size_bytes: int
    sha256: str
    status: str = Field(description="queued | processing | ready | partial | failed")
    stages: StageStatuses
    chat_ready: bool = Field(description="True when the index stage succeeded")
    page_count: int | None = Field(description="PDF pages; null for DOCX/TXT/MD (no pages)")
    segment_count: int | None
    char_count: int | None
    token_count: int | None
    warnings: list[dict[str, Any]]
    error: ErrorInfo | None = Field(description="Last stage error, if any")
    category: str | None = None
    version: int = Field(description="1 for the first upload; +1 for each new version")
    version_group_id: uuid.UUID = Field(
        description="Shared by all versions of a document (the id of version 1)"
    )
    is_latest: bool = Field(description="False once a newer version has been uploaded")
    created_at: datetime
    updated_at: datetime
    chat_ready_at: datetime | None
    ready_at: datetime | None

    @classmethod
    def from_model(cls, doc: Document, category: str | None = None) -> "DocumentOut":
        return cls(
            id=doc.id,
            filename=doc.filename,
            file_type=doc.file_type,
            mime_type=doc.mime_type,
            size_bytes=doc.size_bytes,
            sha256=doc.sha256,
            status=doc.status,
            stages=StageStatuses(
                extract=doc.extract_status, index=doc.index_status, insights=doc.insights_status
            ),
            chat_ready=is_chat_ready(doc),
            page_count=doc.page_count,
            segment_count=doc.segment_count,
            char_count=doc.char_count,
            token_count=doc.token_count,
            warnings=doc.warnings or [],
            error=ErrorInfo(code=doc.error_code, message=doc.error_message)
            if doc.error_code
            else None,
            category=category,
            version=doc.version,
            version_group_id=doc.version_group_id,
            is_latest=doc.is_latest,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            chat_ready_at=doc.chat_ready_at,
            ready_at=doc.ready_at,
        )


class UploadResult(BaseModel):
    filename: str
    outcome: Literal["accepted", "duplicate", "rejected"]
    duplicate: bool = False
    document: DocumentOut | None = None
    error: ErrorInfo | None = None


class UploadResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "results": [
                    {
                        "filename": "falcon-plan.pdf",
                        "outcome": "accepted",
                        "duplicate": False,
                        "document": {"id": DOC_ID, "status": "queued", "...": "…"},
                        "error": None,
                    },
                    {
                        "filename": "falcon-plan-copy.pdf",
                        "outcome": "duplicate",
                        "duplicate": True,
                        "document": {"id": DOC_ID, "status": "ready", "...": "…"},
                        "error": None,
                    },
                    {
                        "filename": "setup.exe",
                        "outcome": "rejected",
                        "duplicate": False,
                        "document": None,
                        "error": {
                            "code": "UNSUPPORTED_FILE_TYPE",
                            "message": "Only PDF, DOCX, TXT and Markdown files are supported.",
                        },
                    },
                ],
                "accepted": 1,
                "duplicates": 1,
                "rejected": 1,
            }
        }
    )

    results: list[UploadResult]
    accepted: int
    duplicates: int
    rejected: int


class Page(BaseModel):
    total: int
    limit: int
    offset: int


class DocumentList(Page):
    items: list[DocumentOut]


class SegmentOut(BaseModel):
    ordinal: int
    locator: dict[str, Any] = Field(
        description='{"type":"page","page":3} | {"type":"section","heading":…,"index":…} | '
        '{"type":"lines","start":1,"end":40}'
    )
    text: str
    char_start: int
    char_end: int


class ContentPage(Page):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "document_id": DOC_ID,
                "file_type": "pdf",
                "items": [
                    {
                        "ordinal": 3,
                        "locator": {"type": "page", "page": 3},
                        "text": "3. Budget\nThe total approved budget is $4.2M…",
                        "char_start": 4210,
                        "char_end": 6388,
                    }
                ],
                "total": 5,
                "limit": 20,
                "offset": 2,
            }
        }
    )

    document_id: uuid.UUID
    file_type: str
    items: list[SegmentOut]


class VersionList(BaseModel):
    version_group_id: uuid.UUID
    latest_id: uuid.UUID
    items: list[DocumentOut] = Field(description="All versions, newest first")


class ReprocessResponse(BaseModel):
    document: DocumentOut
    stages: list[str] = Field(description="Stages reset to pending and enqueued")


class KeyPoint(BaseModel):
    text: str
    pages: list[int] = Field(description="Source PDF pages (empty for non-PDF documents)")
    sections: list[int] | None = Field(
        default=None, description="Source section numbers for DOCX/MD/TXT (see /content ordinals)"
    )


class InsightsOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "document_id": DOC_ID,
                "ai_mode": "openai",
                "model": "gpt-4o-mini",
                "prompt_version": "insights.single.v1",
                "summary_short": "Status report for Project Falcon: budget approved at $4.2M…",
                "summary_detailed": "…",
                "key_points": [
                    {"text": "The total approved budget is $4.2M, approved in March.", "pages": [3]}
                ],
                "entities": {
                    "people": [],
                    "organizations": ["Project Falcon"],
                    "locations": [],
                    "dates": ["March"],
                    "amounts": ["4.2 million dollars"],
                },
                "topics": ["budget", "milestones"],
                "category": "report",
                "tags": ["project", "budget"],
                "sentiment": {"label": "neutral", "rationale": "Factual status reporting."},
                "suggested_questions": ["What is the approved budget?"],
                "coverage": {
                    "segments_total": 5,
                    "segments_covered": 5,
                    "method": "single",
                    "groups": 1,
                    "validation": {
                        "dropped_refs": 0,
                        "dropped_key_points": 0,
                        "invalid_enums": 0,
                        "truncated_fields": [],
                    },
                },
                "created_at": "2026-10-15T09:12:09.880Z",
            }
        }
    )

    document_id: uuid.UUID
    ai_mode: Literal["openai", "fake"] = Field(
        description="`fake` = produced by the deterministic test double, not a real model"
    )
    model: str
    prompt_version: str
    summary_short: str
    summary_detailed: str
    key_points: list[KeyPoint]
    entities: dict[str, list[str]]
    topics: list[str]
    category: str
    tags: list[str]
    sentiment: dict[str, Any]
    suggested_questions: list[str]
    coverage: dict[str, Any]
    created_at: datetime
