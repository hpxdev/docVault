"""Publish document status events from the API side (reprocess, delete)."""

import json
import logging
import uuid

from app.core.redis import async_cache
from app.models import Document
from app.services.status import channel, status_payload

log = logging.getLogger(__name__)


async def publish_status(doc: Document) -> None:
    try:
        await async_cache().publish(channel(doc.id), json.dumps(status_payload(doc)))
    except Exception:
        log.warning("status publish failed", extra={"document_id": str(doc.id)})


async def publish_deleted(document_id: uuid.UUID) -> None:
    try:
        payload = {"id": str(document_id), "deleted": True}
        await async_cache().publish(channel(document_id), json.dumps(payload))
    except Exception:
        log.warning("delete publish failed", extra={"document_id": str(document_id)})
