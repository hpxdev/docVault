"""Multi-file upload: streamed hashing and size checks, sniffing, dedupe, enqueue after commit."""

import asyncio
import hashlib
import logging
import os
import re
import tempfile
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import Document
from app.schemas.documents import DocumentOut, ErrorInfo, UploadResult
from app.services.sniff import sniff
from app.services.storage import Storage
from app.workers import dispatch

log = logging.getLogger(__name__)

READ_CHUNK = 1024 * 1024

# Per-file rejection codes and the HTTP status used when every file is rejected with that code.
REJECTION_STATUS = {"UNSUPPORTED_FILE_TYPE": 415, "EMPTY_FILE": 400, "FILE_TOO_LARGE": 413}


def safe_filename(raw: str | None) -> str:
    name = Path((raw or "").replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return (name or "upload")[:255]


class _Rejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message


async def _spool(upload: UploadFile, tmp_dir: Path, max_bytes: int) -> tuple[Path, str, int]:
    """Copy the upload to a temp file, hashing as we go; stop early when over the limit."""
    digest = hashlib.sha256()
    size = 0
    fd, name = await asyncio.to_thread(tempfile.mkstemp, dir=tmp_dir, prefix="upload-")
    path = Path(name)
    out = await asyncio.to_thread(os.fdopen, fd, "wb")
    try:
        while chunk := await upload.read(READ_CHUNK):
            size += len(chunk)
            if size > max_bytes:
                raise _Rejected(
                    "FILE_TOO_LARGE",
                    f"The file exceeds the {max_bytes // (1024 * 1024)} MB limit.",
                )
            digest.update(chunk)
            await asyncio.to_thread(out.write, chunk)
    except BaseException:
        await asyncio.to_thread(out.close)
        await asyncio.to_thread(path.unlink, missing_ok=True)
        raise
    await asyncio.to_thread(out.close)
    return path, digest.hexdigest(), size


async def _process_one(session: AsyncSession, storage: Storage, upload: UploadFile) -> UploadResult:
    settings = get_settings()
    filename = safe_filename(upload.filename)
    tmp_path: Path | None = None
    try:
        tmp_path, sha256, size = await _spool(upload, storage.temp_dir(), settings.max_upload_bytes)
        if size == 0:
            raise _Rejected("EMPTY_FILE", "The file is empty.")
        detected = sniff(tmp_path, filename)
        if detected is None:
            raise _Rejected(
                "UNSUPPORTED_FILE_TYPE",
                "Only PDF, DOCX, TXT and Markdown files are supported "
                "(the type is detected from the file content).",
            )

        existing = await session.scalar(select(Document).where(Document.sha256 == sha256))
        if existing is not None:
            return UploadResult(
                filename=filename,
                outcome="duplicate",
                duplicate=True,
                document=DocumentOut.from_model(existing),
            )

        doc_id = uuid.uuid4()
        key = storage.save(doc_id, detected.ext, tmp_path)
        tmp_path = None
        doc = Document(
            id=doc_id,
            filename=filename,
            mime_type=detected.mime_type,
            file_type=detected.file_type,
            size_bytes=size,
            sha256=sha256,
            storage_path=key,
            status="queued",
            warnings=[],
        )
        session.add(doc)
        try:
            await session.commit()
        except IntegrityError:
            # Same content uploaded concurrently: the other request won the unique constraint.
            await session.rollback()
            storage.delete_document(doc_id)
            existing = await session.scalar(select(Document).where(Document.sha256 == sha256))
            if existing is None:
                raise
            return UploadResult(
                filename=filename,
                outcome="duplicate",
                duplicate=True,
                document=DocumentOut.from_model(existing),
            )

        # Enqueue only after commit, so the worker never sees a missing row.
        try:
            await asyncio.to_thread(dispatch.enqueue_stage, "extract", doc_id)
        except Exception:
            log.exception("enqueue failed", extra={"document_id": str(doc_id)})
            doc.extract_status = "failed"
            doc.status = "failed"
            doc.error_code = "QUEUE_UNAVAILABLE"
            doc.error_message = "The task queue is unavailable; reprocess the document later."
            await session.commit()
        log.info("document accepted", extra={"document_id": str(doc_id)})
        return UploadResult(
            filename=filename, outcome="accepted", document=DocumentOut.from_model(doc)
        )
    except _Rejected as rej:
        return UploadResult(
            filename=filename,
            outcome="rejected",
            error=ErrorInfo(code=rej.code, message=rej.message),
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        await upload.close()


async def handle_upload(
    session: AsyncSession, storage: Storage, files: list[UploadFile]
) -> tuple[list[UploadResult], int]:
    settings = get_settings()
    if not files:
        raise AppError(
            "Attach at least one file in the `files` field.",
            code="VALIDATION_ERROR",
            status_code=422,
        )
    if len(files) > settings.max_files_per_upload:
        raise AppError(
            f"At most {settings.max_files_per_upload} files per request ({len(files)} sent).",
            code="TOO_MANY_FILES",
            status_code=400,
            details={"max_files": settings.max_files_per_upload, "received": len(files)},
        )
    results = [await _process_one(session, storage, f) for f in files]
    if all(r.outcome == "rejected" for r in results):
        codes = {r.error.code for r in results if r.error}
        status = REJECTION_STATUS.get(next(iter(codes)), 400) if len(codes) == 1 else 400
        return results, status
    return results, 202
