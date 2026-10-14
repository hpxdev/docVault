"""Stage implementations (run inside `execute_stage`, which owns status and retries)."""

import uuid
from itertools import batched

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.registry import sync_ai
from app.core.config import get_settings
from app.core.tokens import count_chat_tokens, count_embedding_tokens
from app.models import Chunk, Document, DocumentSegment
from app.services.extraction import extract
from app.services.insights import generate_insights
from app.services.locators import locator_label
from app.services.pipeline import _STAGE_FUNCS, register_stage
from app.services.stage_errors import StageError
from app.services.storage import get_storage
from app.workers import dispatch

SEGMENT_JOIN = "\n\n"
EMBED_BATCH = 100  # inputs per embeddings request


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


def make_splitter() -> RecursiveCharacterTextSplitter:
    settings = get_settings()
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",  # the embedding model's tokenizer
        chunk_size=settings.chunk_tokens,
        chunk_overlap=settings.chunk_overlap_tokens,
    )


def embedding_input(doc: Document, locator: dict, text: str) -> str:
    """Text sent to the embedding model: a short header (file + location) gives each vector
    document context. The stored chunk text, full-text index and citations use `text` only."""
    return f"{doc.filename} | {locator_label(locator)}\n{text}"


@register_stage("index")
def index_stage(session: Session, doc: Document) -> None:
    segments = session.scalars(
        select(DocumentSegment)
        .where(DocumentSegment.document_id == doc.id)
        .order_by(DocumentSegment.ordinal)
    ).all()
    splitter = make_splitter()
    # Split each segment on its own: chunks never cross page/section boundaries, so every chunk
    # keeps an exact locator.
    pieces = [
        (seg, text)
        for seg in segments
        if seg.text.strip()
        for text in splitter.split_text(seg.text)
    ]
    if not pieces:
        raise StageError("NO_EXTRACTABLE_TEXT", "The document has no text to index.")

    ai = sync_ai()
    vectors: list[list[float]] = []
    for batch in batched(pieces, EMBED_BATCH):
        vectors += ai.embed_documents(
            [embedding_input(doc, seg.locator, text) for seg, text in batch],
            document_id=doc.id,
        )

    # Idempotent: replace the document's chunks in the same transaction as the status update.
    session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    for ordinal, ((seg, text), vector) in enumerate(zip(pieces, vectors, strict=True), start=1):
        session.add(
            Chunk(
                document_id=doc.id,
                segment_id=seg.id,
                ordinal=ordinal,
                text=text,
                locator=seg.locator,
                page_number=seg.locator.get("page"),
                token_count=count_embedding_tokens(text),
                embedding=vector,
                embedding_model=ai.embeddings.name,
            )
        )
    doc.embedding_model = ai.embeddings.name


@register_stage("insights")
def insights_stage(session: Session, doc: Document) -> None:
    generate_insights(session, doc, sync_ai())
