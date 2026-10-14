"""Deterministic test doubles for the AI providers (AI_PROVIDER=fake and the test suite).

Everything they produce is labelled: model name "fake" in every stored record, `ai_mode: fake`
in API responses, and "FAKE AI MODE" in generated text. They prove the plumbing, not AI quality.

- FakeEmbeddings: hashed bag-of-words vectors, so lexical overlap gives real cosine similarity
  and retrieval tests are meaningful.
- FakeChatModel: scripted outputs (strings, dicts, callables or exceptions, consumed in order);
  with an empty script it falls back to simple heuristics per purpose.
"""

import asyncio
import hashlib
import math
import re
from collections import Counter, deque
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from typing import Any, TypeVar

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.ai.providers import StreamResult, Usage
from app.ai.schemas import DocumentInsightsLLM, SectionNotesLLM
from app.core.tokens import count_chat_tokens, count_embedding_tokens

T = TypeVar("T", bound=BaseModel)

FAKE_LABEL = "FAKE AI MODE"
DIMENSIONS = 1536

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "me",
        "my",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "should",
        "so",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "about",
        "also",
        "any",
        "each",
        "just",
        "more",
        "most",
        "other",
        "over",
        "some",
        "only",
        "very",
        "per",
        "via",
    ]
)
_WORD = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")


def content_words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 1]


# ---------------------------------------------------------------- embeddings


def hashed_embedding(text: str, dims: int = DIMENSIONS) -> list[float]:
    vec = [0.0] * dims
    counts = Counter(content_words(text))
    if not counts:
        counts = Counter({"__empty__": 1})
    for word, tf in counts.items():
        h = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=8).digest(), "big")
        vec[h % dims] += (1.0 if (h >> 32) & 1 else -1.0) * (1.0 + math.log(tf))
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FakeEmbeddings:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail_with: BaseException | None = None

    def _check(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    def embed_documents(self, texts: list[str]) -> tuple[list[list[float]], Usage]:
        self._check()
        self.calls.append(list(texts))
        tokens = sum(count_embedding_tokens(t) for t in texts)
        return [hashed_embedding(t) for t in texts], Usage(input_tokens=tokens)

    async def aembed_query(self, text: str) -> tuple[list[float], Usage]:
        self._check()
        self.calls.append([text])
        return hashed_embedding(text), Usage(input_tokens=count_embedding_tokens(text))


# ---------------------------------------------------------------- chat heuristics

_SOURCE = re.compile(
    r'<source id="S(\d+)" document="([^"]*)" location="([^"]*)">\n(.*?)\n</source>', re.S
)
_MARKER = re.compile(r"\[(?:Page|Section) (\d+)[^\]]*\]")
_NOTE_LINE = re.compile(r"^- (.+?) \(refs: ([\d, ]*)\)$", re.M)
_AMOUNT = re.compile(
    r"(?:[$€£]\s?\d[\d,.]*\s?(?:million|billion|[MBK])?|\b\d[\d,.]*\s?(?:million|billion|EUR|USD|"
    r"dollars|days|%))",
    re.I,
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def _human_text(messages: Sequence[BaseMessage]) -> str:
    for msg in reversed(messages):
        if msg.type == "human":
            return str(msg.content)
    return str(messages[-1].content) if messages else ""


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 3]


def fake_answer(messages: Sequence[BaseMessage]) -> str:
    text = _human_text(messages)
    question = text.rsplit("Question:", 1)[-1].strip()
    q_words = set(content_words(question))
    best: tuple[int, int, str, str, str] | None = None
    for sid, doc, loc, body in _SOURCE.findall(text):
        for sentence in _sentences(body):
            score = len(q_words & set(content_words(sentence)))
            if score and (best is None or score > best[0]):
                best = (score, int(sid), doc, loc, sentence)
    if best is None:
        return (
            f"[NO_ANSWER] {FAKE_LABEL}: none of the retrieved sources share terms with the "
            "question."
        )
    _, sid, doc, loc, sentence = best
    return (
        f"{FAKE_LABEL} (deterministic test double, not a real model). The most relevant passage, "
        f'from {doc} ({loc}), reads: "{sentence}" [S{sid}]'
    )


_REFERENCE_WORDS = frozenset(
    [
        "it",
        "its",
        "it's",
        "that",
        "this",
        "these",
        "those",
        "they",
        "them",
        "their",
        "he",
        "she",
        "there",
    ]
)


def fake_condense(messages: Sequence[BaseMessage]) -> str:
    """Mirrors chat.condense.v1: add context only when the follow-up refers back to the
    conversation (a reference word such as "it"); a standalone question is returned unchanged."""
    text = _human_text(messages)
    follow_up = text.rsplit("Follow-up question:", 1)[-1].split("Standalone question:")[0].strip()
    users = re.findall(r"^User: (.+)$", text, re.M)
    refers_back = bool(_REFERENCE_WORDS & set(re.findall(r"[a-z']+", follow_up.lower())))
    if not users or not refers_back:
        return follow_up
    return f"{follow_up} (context: {users[-1].strip()})"


def _blocks(text: str) -> list[tuple[int, str]]:
    """Split text with [Page N]/[Section N] markers into (ref, body) blocks."""
    out = []
    matches = list(_MARKER.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((int(m.group(1)), text[m.end() : end].strip()))
    return out


def _spread(items: list[Any], k: int) -> list[Any]:
    if len(items) <= k:
        return items
    step = (len(items) - 1) / (k - 1)
    return [items[round(i * step)] for i in range(k)]


def _points_from_text(text: str) -> list[tuple[str, list[int]]]:
    notes = [(t, [int(x) for x in r.split(",") if x.strip()]) for t, r in _NOTE_LINE.findall(text)]
    if notes:
        return notes
    points = []
    for ref, body in _blocks(text):
        sentences = _sentences(body)
        if sentences:
            # Prefer the sentence with the most digits (facts), else the longest.
            best = max(sentences, key=lambda s: (sum(c.isdigit() for c in s) > 0, len(s)))
            points.append((best, [ref]))
    return points


def _entities(text: str) -> dict[str, list[str]]:
    amounts = list(dict.fromkeys(m.strip() for m in _AMOUNT.findall(text)))[:10]
    dates = list(dict.fromkeys(_YEAR.findall(text)))[:10]
    return {"people": [], "organizations": [], "locations": [], "dates": dates, "amounts": amounts}


def _top_words(text: str, k: int) -> list[str]:
    words = [w for w in content_words(text) if len(w) >= 5 and not w[0].isdigit()]
    return [w for w, _ in Counter(words).most_common(k)]


def fake_structured[M: BaseModel](schema: type[M], messages: Sequence[BaseMessage]) -> M:
    text = _human_text(messages)
    points = _points_from_text(text)
    key_points = [{"text": t[:300], "refs": refs} for t, refs in _spread(points, 8)]
    entities = _entities(text)
    if schema is SectionNotesLLM:
        return schema.model_validate(
            {"key_points": key_points[:6], "entities": entities, "figures": entities["amounts"]}
        )
    if schema is DocumentInsightsLLM:
        words = re.sub(r"\[(?:Page|Section)[^\]]*\]", " ", text).split()
        topics = _top_words(text, 5)
        return schema.model_validate(
            {
                "summary_short": f"{FAKE_LABEL} summary (not model-generated): "
                + " ".join(words[:30]),
                "summary_detailed": f"{FAKE_LABEL}: extractive placeholder built from the first "
                "sentence of evenly spaced sections. " + " ".join(t for t, _ in points[:5])[:1200],
                "key_points": key_points,
                "entities": entities,
                "topics": topics,
                "category": "other",
                "tags": [t[:24] for t in topics[:5]],
                "sentiment": {
                    "label": "neutral",
                    "rationale": f"{FAKE_LABEL}: sentiment is not analysed by the test double.",
                },
                "suggested_questions": [
                    f"What does the document say about {t}?" for t in topics[:3]
                ]
                or ["What is this document about?"],
            }
        )
    raise NotImplementedError(f"No fake for schema {schema.__name__}")


ScriptItem = str | dict | BaseModel | BaseException | Callable[[str, Sequence[BaseMessage]], Any]


class FakeChatModel:
    name = "fake"

    def __init__(self, script: Iterable[ScriptItem] | None = None, delay: float = 0.0) -> None:
        self.script: deque[ScriptItem] = deque(script or [])
        self.delay = delay
        self.calls: list[tuple[str, list[BaseMessage]]] = []

    def push(self, *items: ScriptItem) -> None:
        self.script.extend(items)

    def _next(self, purpose: str, messages: Sequence[BaseMessage], default: Callable[[], Any]):
        self.calls.append((purpose, list(messages)))
        if not self.script:
            return default()
        item = self.script.popleft()
        if isinstance(item, BaseException):
            raise item
        if callable(item) and not isinstance(item, BaseModel):
            return item(purpose, messages)
        return item

    @staticmethod
    def _usage(messages: Sequence[BaseMessage], output: str) -> Usage:
        prompt = "\n".join(str(m.content) for m in messages)
        return Usage(
            input_tokens=count_chat_tokens(prompt), output_tokens=count_chat_tokens(output)
        )

    def _default_text(self, purpose: str, messages: Sequence[BaseMessage]) -> str:
        if purpose == "condense":
            return fake_condense(messages)
        return fake_answer(messages)

    def structured(
        self, schema: type[T], messages: Sequence[BaseMessage], *, purpose: str, max_tokens: int
    ) -> tuple[T, Usage]:
        out = self._next(purpose, messages, lambda: fake_structured(schema, messages))
        if isinstance(out, dict):
            out = schema.model_validate(out)
        return out, self._usage(messages, out.model_dump_json())

    async def acomplete(
        self, messages: Sequence[BaseMessage], *, purpose: str, max_tokens: int
    ) -> tuple[str, Usage]:
        text = self._next(purpose, messages, lambda: self._default_text(purpose, messages))
        return str(text), self._usage(messages, str(text))

    async def astream(
        self,
        messages: Sequence[BaseMessage],
        *,
        purpose: str,
        max_tokens: int,
        result: StreamResult,
    ) -> AsyncIterator[str]:
        text = str(self._next(purpose, messages, lambda: self._default_text(purpose, messages)))
        for piece in re.findall(r"\S+\s*|\s+", text):
            if self.delay:
                await asyncio.sleep(self.delay)
            result.text += piece
            yield piece
        result.usage = self._usage(messages, text)
