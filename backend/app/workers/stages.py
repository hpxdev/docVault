"""Stage implementations (run inside `execute_stage`, which owns status and retries)."""

import uuid

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.tokens import count_chat_tokens
from app.models import Document, DocumentSegment
from app.services.extraction import extract
from app.services.pipeline import _STAGE_FUNCS, register_stage
from app.services.stage_errors import StageError
from app.services.storage import get_storage
from app.workers import dispatch

SEGMENT_JOIN = "\n\n"


def enqueue_downstream(document_id: uuid.UUID) -> None:
    """After extraction: index and insights run as independent tasks."""
    for stage in ("index", "insights"):
        if stage in _STAGE_FUNCS:
            dispatch.enqueue_stage(stage, document_id)


@register_stage("extract", after_success=enqueue_downstream)
def extract_stage(session: Session, doc: Document) -> None:
    path = get_storage().local_path(doc.storage_path)
    if not path.is_file():
        raise StageError("FILE_MISSING", "The stored file is missing.")
    result = extract(path, doc.file_type, get_settings().max_pages)

    # Idempotent: replace any segments (and, via cascade, chunks) from a previous run.
    session.execute(delete(DocumentSegment).where(DocumentSegment.document_id == doc.id))
    offset = 0
    texts = []
    for ordinal, seg in enumerate(result.segments, start=1):
        session.add(
            DocumentSegment(
                document_id=doc.id,
                ordinal=ordinal,
                locator=seg.locator,
                text=seg.text,
                char_start=offset,
                char_end=offset + len(seg.text),
            )
        )
        texts.append(seg.text)
        offset += len(seg.text) + len(SEGMENT_JOIN)
    full_text = SEGMENT_JOIN.join(texts)
    doc.page_count = result.page_count
    doc.segment_count = len(result.segments)
    doc.char_count = len(full_text)
    doc.token_count = count_chat_tokens(full_text)
    doc.warnings = result.warnings
