"""Enqueue pipeline stages. Called only after the triggering transaction has committed."""

import uuid

from app.workers.celery_app import QUEUES, celery_app

TASK_NAMES = {"extract": "vault.extract", "index": "vault.index", "insights": "vault.insights"}


def enqueue_stage(stage: str, document_id: uuid.UUID | str) -> None:
    celery_app.send_task(TASK_NAMES[stage], args=[str(document_id)], queue=QUEUES[stage])
