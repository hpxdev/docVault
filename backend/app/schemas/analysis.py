"""Custom summaries and comparisons (on-demand AI)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import DocumentComparison, DocumentSummary
from app.schemas.documents import DOC_ID, KeyPoint, Page

DOC_ID_2 = "8a2d4c6e-0f1b-4a3c-9e5d-7b9f1a3c5e70"


def _ai_mode(model: str) -> Literal["openai", "fake"]:
    return "fake" if model == "fake" else "openai"


class SummaryRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"length": "short", "tone": "executive", "focus": "budget and risks"},
                {"length": "long", "tone": "plain"},
            ]
        }
    )

    length: Literal["short", "medium", "long"] = Field(
        default="medium",
        description="short ≤ 80 words / 3 points · medium ≤ 200 / 5 · long ≤ 400 / 8",
    )
    tone: Literal["neutral", "executive", "technical", "plain"] = "neutral"
    focus: str | None = Field(
        default=None,
        max_length=200,
        description="Topic to concentrate on, e.g. 'budget and risks' (treated as data, not as "
        "instructions)",
    )


class SummaryOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "1c3e5a7b-9d0f-4b2a-8c6e-4f2a0b8d6c1e",
                "document_id": DOC_ID,
                "length": "short",
                "tone": "executive",
                "focus": "budget and risks",
                "summary": "The project budget is 41.5 million euros, approved on 4 March 2026…",
                "key_points": [{"text": "Contingency of 3.2 million euros.", "pages": [3]}],
                "focus_covered": True,
                "coverage": {
                    "segments_total": 6,
                    "segments_included": 6,
                    "complete": True,
                    "selection": "all",
                    "input_token_budget": 40000,
                    "validation": {
                        "dropped_refs": 0,
                        "dropped_key_points": 0,
                        "invalid_enums": 0,
                        "truncated_fields": [],
                    },
                },
                "ai_mode": "openai",
                "model": "gpt-4o-mini",
                "prompt_version": "summary.custom.v1",
                "cached": False,
                "created_at": "2026-10-15T09:20:00Z",
            }
        }
    )

    id: uuid.UUID
    document_id: uuid.UUID
    length: str
    tone: str
    focus: str | None
    summary: str
    key_points: list[KeyPoint]
    focus_covered: bool | None = Field(
        description="False when the document does not address the focus; null without a focus"
    )
    coverage: dict[str, Any] = Field(
        description="`complete: false` means the document was too long and only the selected "
        "parts were summarised"
    )
    ai_mode: Literal["openai", "fake"]
    model: str
    prompt_version: str
    cached: bool = Field(
        description="True when an identical earlier request was reused (no AI cost)"
    )
    created_at: datetime

    @classmethod
    def from_model(cls, row: DocumentSummary, cached: bool) -> "SummaryOut":
        return cls(
            id=row.id,
            document_id=row.document_id,
            length=row.length,
            tone=row.tone,
            focus=row.focus,
            summary=row.summary,
            key_points=row.key_points,
            focus_covered=row.focus_covered,
            coverage=row.coverage,
            ai_mode=_ai_mode(row.model),
            model=row.model,
            prompt_version=row.prompt_version,
            cached=cached,
            created_at=row.created_at,
        )


class SummaryList(BaseModel):
    items: list[SummaryOut]


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"document_ids": [DOC_ID, DOC_ID_2], "focus": "budget"},
                {"document_ids": [DOC_ID, DOC_ID_2]},
            ]
        }
    )

    document_ids: list[uuid.UUID] = Field(min_length=2, max_length=4)
    focus: str | None = Field(default=None, max_length=200)


class ComparedDocument(BaseModel):
    label: str = Field(description="D1, D2, … (oldest upload first)")
    id: uuid.UUID
    filename: str
    file_type: str
    version: int
    version_group_id: uuid.UUID


class SourceRef(BaseModel):
    label: str
    document_id: uuid.UUID
    pages: list[int]
    sections: list[int] | None = None


class Similarity(BaseModel):
    text: str
    sources: list[SourceRef] = Field(description="At least two documents")


class Position(SourceRef):
    statement: str
    addressed: bool = Field(description="False: not addressed, or no source was cited")


class Difference(BaseModel):
    aspect: str
    positions: list[Position] = Field(description="One per document, in label order")


class ComparisonOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "5e7a9c1b-3d5f-4a7b-9c1e-3a5c7e9b1d3f",
                "documents": [
                    {
                        "label": "D1",
                        "id": DOC_ID,
                        "filename": "leave-policy-2025.pdf",
                        "file_type": "pdf",
                        "version": 1,
                        "version_group_id": DOC_ID,
                    },
                    {
                        "label": "D2",
                        "id": DOC_ID_2,
                        "filename": "leave-policy-2026.pdf",
                        "file_type": "pdf",
                        "version": 2,
                        "version_group_id": DOC_ID,
                    },
                ],
                "focus": None,
                "overview": "Two versions of the leave policy; 2026 adds two days of leave.",
                "focus_covered": None,
                "same_document_versions": True,
                "similarities": [
                    {
                        "text": "Up to 5 unused days can be carried over.",
                        "sources": [
                            {"label": "D1", "document_id": DOC_ID, "pages": [2]},
                            {"label": "D2", "document_id": DOC_ID_2, "pages": [2]},
                        ],
                    }
                ],
                "differences": [
                    {
                        "aspect": "Annual leave days",
                        "positions": [
                            {
                                "label": "D1",
                                "document_id": DOC_ID,
                                "pages": [1],
                                "statement": "25 days of paid annual leave.",
                                "addressed": True,
                            },
                            {
                                "label": "D2",
                                "document_id": DOC_ID_2,
                                "pages": [1],
                                "statement": "27 days of paid annual leave.",
                                "addressed": True,
                            },
                        ],
                    }
                ],
                "coverage": {"documents": {"D1": {"complete": True}, "D2": {"complete": True}}},
                "ai_mode": "openai",
                "model": "gpt-4o-mini",
                "prompt_version": "compare.v1",
                "cached": False,
                "created_at": "2026-10-15T09:25:00Z",
            }
        }
    )

    id: uuid.UUID
    documents: list[ComparedDocument]
    focus: str | None
    overview: str
    focus_covered: bool | None
    same_document_versions: bool = Field(description="True when all documents are versions of one")
    similarities: list[Similarity]
    differences: list[Difference]
    coverage: dict[str, Any]
    ai_mode: Literal["openai", "fake"]
    model: str
    prompt_version: str
    cached: bool
    created_at: datetime

    @classmethod
    def from_model(cls, row: DocumentComparison, cached: bool) -> "ComparisonOut":
        r = row.result
        return cls(
            id=row.id,
            documents=row.documents,
            focus=row.focus,
            overview=r["overview"],
            focus_covered=r.get("focus_covered"),
            same_document_versions=r.get("same_document_versions", False),
            similarities=r["similarities"],
            differences=r["differences"],
            coverage=row.coverage,
            ai_mode=_ai_mode(row.model),
            model=row.model,
            prompt_version=row.prompt_version,
            cached=cached,
            created_at=row.created_at,
        )


class ComparisonList(Page):
    items: list[ComparisonOut]
