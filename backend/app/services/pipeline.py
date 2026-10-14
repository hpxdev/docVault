"""Stage execution for the Celery worker (sync SQLAlchemy).

Each stage:
1. claims the document row (`SELECT … FOR UPDATE`): only a `pending`/`running` stage can be
   claimed, so a re-delivered task for a finished stage is a no-op and status never moves back;
2. records a `processing_runs` row and publishes a status event on `doc:{id}`;
3. does its work; data writes and the final status update commit in one transaction;
4. on a transient error asks the caller to retry with backoff, otherwise fails with a code.
"""

import json
import logging
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from app.ai.errors import AIError
from app.core.config import get_settings
from app.core.redis import sync_cache
from app.db.session import sync_session
from app.models import Document, ProcessingRun
from app.services.stage_errors import StageError, TransientStageError
from app.services.status import ACTIVE, STAGE_COLUMN, channel, recompute, status_payload

log = logging.getLogger(__name__)

StageFn = Callable[[Session, Document], None]
_STAGE_FUNCS: dict[str, StageFn] = {}
# Called after a stage commits successfully (e.g. extract -> enqueue index + insights).
_AFTER_SUCCESS: dict[str, Callable[[uuid.UUID], None]] = {}


def register_stage(name: str, after_success: Callable[[uuid.UUID], None] | None = None):
    def deco(fn: StageFn) -> StageFn:
        _STAGE_FUNCS[name] = fn
        if after_success:
            _AFTER_SUCCESS[name] = after_success
        return fn

    return deco


@dataclass
class StageOutcome:
    result: str  # succeeded | failed | retry | skipped
    countdown: float = 0.0
    error_code: str | None = None


def publish(doc: Document) -> None:
    try:
        sync_cache().publish(channel(doc.id), json.dumps(status_payload(doc)))
    except Exception:  # events are best-effort; Postgres stays the source of truth
        log.warning("status publish failed", extra={"document_id": str(doc.id)})


def backoff_seconds(attempt: int) -> float:
    """Exponential backoff with full jitter: attempt 1 -> up to 2 s, 2 -> 4 s, 3 -> 8 s."""
    return random.uniform(0.5, 1.0) * min(60, 2**attempt)


def _now() -> datetime:
    return datetime.now(UTC)


def claim(
    session: Session, document_id: uuid.UUID, stage: str, attempt: int, task_id: str | None
) -> ProcessingRun | None:
    col = STAGE_COLUMN[stage]
    doc = session.get(Document, document_id, with_for_update=True)
    if doc is None:
        return None
    if getattr(doc, col) not in ACTIVE:
        return None
    if stage != "extract" and doc.extract_status != "succeeded":
        return None
    # A run still marked running means the previous worker died mid-task (acks_late re-delivery).
    session.execute(
        update(ProcessingRun)
        .where(
            ProcessingRun.document_id == document_id,
            ProcessingRun.stage == stage,
            ProcessingRun.status == "running",
        )
        .values(status="failed", error_code="WORKER_LOST", finished_at=_now())
    )
    setattr(doc, col, "running")
    recompute(doc)
    run = ProcessingRun(
        document_id=document_id,
        stage=stage,
        attempt=attempt,
        status="running",
        celery_task_id=task_id,
        started_at=_now(),
    )
    session.add(run)
    session.commit()
    publish(doc)
    return run


def _close_run(run: ProcessingRun, status: str, code: str | None, message: str | None) -> None:
    run.status = status
    run.finished_at = _now()
    run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    run.error_code = code
    run.error_message = message[:2000] if message else None


def _finish(
    session: Session,
    run_id: uuid.UUID,
    stage: str,
    *,
    stage_status: str,
    run_status: str,
    code: str | None = None,
    message: str | None = None,
) -> Document | None:
    col = STAGE_COLUMN[stage]
    run = session.get(ProcessingRun, run_id)
    if run is None:  # document deleted mid-run (cascade)
        return None
    doc = session.get(Document, run.document_id, with_for_update=True)
    if doc is None:
        return None
    _close_run(run, run_status, code, message)
    # Conditional: only move the stage forward if this run still owns it.
    if getattr(doc, col) == "running":  # this run still owns the stage
        setattr(doc, col, stage_status)
        now = _now()
        if stage_status == "failed":
            doc.error_code, doc.error_message = code, message
        if stage == "index" and stage_status == "succeeded":
            doc.chat_ready_at = doc.chat_ready_at or now
        recompute(doc)
        if doc.status == "ready":
            doc.ready_at = doc.ready_at or now
            doc.error_code = doc.error_message = None
    return doc


def execute_stage(
    stage: str,
    document_id: uuid.UUID | str,
    *,
    attempt: int = 1,
    task_id: str | None = None,
    max_retries: int | None = None,
) -> StageOutcome:
    """Run one stage. Returns what the caller (Celery task or test) should do next."""
    document_id = uuid.UUID(str(document_id))
    max_retries = get_settings().ai_max_retries if max_retries is None else max_retries
    fn = _STAGE_FUNCS[stage]
    extra = {"document_id": str(document_id), "stage": stage, "attempt": attempt}

    with sync_session() as session:
        run = claim(session, document_id, stage, attempt, task_id)
        if run is None:
            log.info("stage skipped (not claimable)", extra=extra)
            return StageOutcome("skipped")
        run_id = run.id

    started = time.perf_counter()
    error: StageError | None = None
    with sync_session() as session:
        try:
            doc = session.get(Document, document_id)
            if doc is None:
                return StageOutcome("skipped")
            fn(session, doc)
            doc = _finish(session, run_id, stage, stage_status="succeeded", run_status="succeeded")
            session.commit()
        except StageError as exc:
            session.rollback()
            error = exc
        except SoftTimeLimitExceeded:
            session.rollback()
            error = StageError("STAGE_TIMEOUT", f"The {stage} stage exceeded its time limit.")
        except AIError as exc:
            session.rollback()
            error = (
                TransientStageError(exc.code, exc.message)
                if exc.transient
                else StageError(exc.code, exc.message)
            )
        except (OperationalError, DBAPIError) as exc:
            session.rollback()
            error = TransientStageError("DB_UNAVAILABLE", type(exc).__name__)
        except Exception as exc:
            session.rollback()
            log.exception("stage crashed", extra=extra)
            error = StageError("INTERNAL_ERROR", f"Unexpected error: {type(exc).__name__}")

    duration_ms = int((time.perf_counter() - started) * 1000)
    if error is None:
        if doc is not None:
            publish(doc)
        log.info("stage succeeded", extra={**extra, "duration_ms": duration_ms})
        after = _AFTER_SUCCESS.get(stage)
        if after:
            after(document_id)
        return StageOutcome("succeeded")

    retry = isinstance(error, TransientStageError) and attempt <= max_retries
    with sync_session() as session:
        if retry:
            doc = _finish(
                session,
                run_id,
                stage,
                stage_status="retrying",
                run_status="retrying",
                code=error.code,
                message=error.message,
            )
        else:
            code = error.final_code if isinstance(error, TransientStageError) else error.code
            doc = _finish(
                session,
                run_id,
                stage,
                stage_status="failed",
                run_status="failed",
                code=code,
                message=error.message,
            )
        session.commit()
    if doc is not None:
        publish(doc)
    if retry:
        countdown = backoff_seconds(attempt)
        log.warning(
            "stage will retry",
            extra={**extra, "error_code": error.code, "duration_ms": duration_ms},
        )
        return StageOutcome("retry", countdown=countdown, error_code=error.code)
    log.warning(
        "stage failed", extra={**extra, "error_code": error.code, "duration_ms": duration_ms}
    )
    return StageOutcome("failed", error_code=error.code)
