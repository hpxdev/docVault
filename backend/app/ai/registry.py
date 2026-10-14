"""Select providers from settings. `AI_PROVIDER=fake` → deterministic doubles labelled "fake"."""

from functools import lru_cache

from app.ai.client import AsyncAI, SyncAI
from app.ai.errors import AINotConfigured
from app.ai.fakes import FakeChatModel, FakeEmbeddings
from app.ai.pricing import has_price
from app.ai.providers import ChatModel, EmbeddingModel
from app.core.config import get_settings

_overrides: dict[str, object] = {}


@lru_cache
def _fake_chat() -> FakeChatModel:
    return FakeChatModel()


@lru_cache
def _fake_embeddings() -> FakeEmbeddings:
    return FakeEmbeddings()


def _require_openai(model: str) -> str:
    settings = get_settings()
    if settings.openai_api_key is None:
        raise AINotConfigured("AI_PROVIDER=openai but OPENAI_API_KEY is not set.")
    if not has_price(model):
        raise AINotConfigured(
            f"No price is configured for model {model!r}; add it to app/ai/pricing.py so spend "
            "can be tracked."
        )
    return settings.openai_api_key.get_secret_value()


@lru_cache
def _openai_chat(model: str, retries: int) -> ChatModel:
    from app.ai.openai_provider import OpenAIChat

    return OpenAIChat(model, _require_openai(model), max_retries=retries)


@lru_cache
def _openai_embeddings(model: str, retries: int, dims: int) -> EmbeddingModel:
    from app.ai.openai_provider import OpenAIEmbeddingModel

    return OpenAIEmbeddingModel(model, _require_openai(model), max_retries=retries, dimensions=dims)


def _retries(context: str) -> int:
    # The worker retries whole stages via Celery; the API retries inside the SDK.
    return 0 if context == "worker" else get_settings().ai_max_retries


def get_chat_model(context: str = "api") -> ChatModel:
    if "chat" in _overrides:
        return _overrides["chat"]  # type: ignore[return-value]
    settings = get_settings()
    if settings.ai_provider == "fake":
        return _fake_chat()
    _require_openai(settings.openai_chat_model)
    return _openai_chat(settings.openai_chat_model, _retries(context))


def get_embedding_model(context: str = "api") -> EmbeddingModel:
    if "embeddings" in _overrides:
        return _overrides["embeddings"]  # type: ignore[return-value]
    settings = get_settings()
    if settings.ai_provider == "fake":
        return _fake_embeddings()
    _require_openai(settings.openai_embedding_model)
    return _openai_embeddings(
        settings.openai_embedding_model, _retries(context), settings.embedding_dimensions
    )


def sync_ai() -> SyncAI:
    return SyncAI(get_chat_model("worker"), get_embedding_model("worker"))


def async_ai() -> AsyncAI:
    return AsyncAI(get_chat_model("api"), get_embedding_model("api"))


def set_overrides(chat: ChatModel | None = None, embeddings: EmbeddingModel | None = None) -> None:
    """Test hook."""
    if chat is not None:
        _overrides["chat"] = chat
    if embeddings is not None:
        _overrides["embeddings"] = embeddings


def clear_overrides() -> None:
    _overrides.clear()
