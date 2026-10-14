"""Celery application: Redis broker, no result backend (Postgres holds all state)."""

import logging
import os
import socket
import threading
import time

from celery import Celery
from celery.signals import worker_process_init, worker_ready, worker_shutdown

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.redis import HEARTBEAT_KEY, HEARTBEAT_TTL_S, sync_cache

log = logging.getLogger(__name__)

# Soft/hard time limits per stage (seconds).
TIME_LIMITS = {"extract": (120, 150), "index": (300, 360), "insights": (300, 360)}
QUEUES = {"extract": "ingest", "index": "ai", "insights": "ai"}

settings = get_settings()

celery_app = Celery("ai_vault", broker=settings.redis_url, include=["app.workers.tasks"])
celery_app.conf.update(
    task_ignore_result=True,
    result_backend=None,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Must exceed the longest hard time limit, or Redis re-delivers tasks still running.
    broker_transport_options={"visibility_timeout": 3600},
    broker_connection_retry_on_startup=True,
    task_default_queue="ingest",
    task_routes={
        "vault.extract": {"queue": "ingest"},
        "vault.index": {"queue": "ai"},
        "vault.insights": {"queue": "ai"},
    },
    task_serializer="json",
    accept_content=["json"],
    worker_hijack_root_logger=False,
    worker_concurrency=settings.worker_concurrency,
    timezone="UTC",
)

_stop = threading.Event()


def _heartbeat_loop() -> None:
    ident = f"{socket.gethostname()}:{os.getpid()}"
    while not _stop.is_set():
        try:
            sync_cache().set(HEARTBEAT_KEY, f"{ident}@{int(time.time())}", ex=HEARTBEAT_TTL_S)
        except Exception:  # Redis briefly unavailable; try again next tick
            log.warning("worker heartbeat failed")
        _stop.wait(10)


@worker_ready.connect
def _start_heartbeat(**_: object) -> None:
    configure_logging(settings.log_level)
    threading.Thread(target=_heartbeat_loop, name="heartbeat", daemon=True).start()
    log.info("worker ready; heartbeat started")


@worker_shutdown.connect
def _stop_heartbeat(**_: object) -> None:
    _stop.set()


@worker_process_init.connect
def _init_child(**_: object) -> None:
    # Prefork children must not reuse the parent's DB connections.
    from app.db.session import reset_sync_engine

    configure_logging(settings.log_level)
    reset_sync_engine()
