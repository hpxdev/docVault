"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, documents, health, metrics
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.redis import close_async_clients
from app.db.session import dispose_async_engine

API_PREFIX = "/api/v1"

DESCRIPTION = """
AI-powered document vault with RAG chat ("ChatGPT for your documents").

Upload PDF/DOCX/TXT/MD files, let the background pipeline extract, index and analyse them, then
ask questions and get streamed answers with **server-verified citations** (document, page or
section, original excerpt) or an explicit "not found".

Local, single-user demo: **no authentication**. All AI cost figures are **estimates**.
When `ai_mode` is `fake`, AI output comes from deterministic test doubles, not a real model.
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logging.getLogger(__name__).info(
        "api starting", extra={"model": settings.chat_model_name, "purpose": settings.ai_mode}
    )
    yield
    await close_async_clients()
    await dispose_async_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI Vault API",
        version="0.1.0",
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(documents.router, prefix=API_PREFIX)
    app.include_router(chat.router, prefix=API_PREFIX)
    app.include_router(metrics.router, prefix=API_PREFIX)
    return app


app = create_app()
