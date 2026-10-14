"""Provider interfaces. Implementations: `openai_provider` (LangChain) and `fakes` (tests/demo).

Messages use LangChain's message types. Methods receive `purpose` so the fake can choose a
default behaviour; real providers ignore it.
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    # True when tokens were counted locally (e.g. an interrupted stream) instead of reported.
    estimated: bool = False


@dataclass
class StreamResult:
    """Filled in while `astream` runs; complete once the iterator is exhausted."""

    text: str = ""
    usage: Usage = field(default_factory=Usage)


class ChatModel(Protocol):
    name: str

    def structured(
        self, schema: type[T], messages: Sequence[BaseMessage], *, purpose: str, max_tokens: int
    ) -> tuple[T, Usage]: ...

    async def acomplete(
        self, messages: Sequence[BaseMessage], *, purpose: str, max_tokens: int
    ) -> tuple[str, Usage]: ...

    def astream(
        self,
        messages: Sequence[BaseMessage],
        *,
        purpose: str,
        max_tokens: int,
        result: StreamResult,
    ) -> AsyncIterator[str]: ...


class EmbeddingModel(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> tuple[list[list[float]], Usage]: ...

    async def aembed_query(self, text: str) -> tuple[list[float], Usage]: ...


def usage_from_metadata(meta: dict[str, Any] | None) -> Usage:
    """LangChain `usage_metadata` → Usage."""
    if not meta:
        return Usage()
    details = meta.get("input_token_details") or {}
    return Usage(
        input_tokens=int(meta.get("input_tokens") or 0),
        output_tokens=int(meta.get("output_tokens") or 0),
        cached_tokens=int(details.get("cache_read") or 0),
    )
