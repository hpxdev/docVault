"""Server-side citation validation and excerpt selection.

The model may only cite markers it was given. Unknown markers are removed from the answer and
recorded; valid ones are mapped to the stored chunk, whose original text (never model text)
provides the excerpt.
"""

import re
from dataclasses import dataclass, field

from app.ai.fakes import content_words

NO_ANSWER = "[NO_ANSWER]"
_GROUP = re.compile(r"\s?\[(S\d+(?:\s*[,;]\s*S\d+)*)\]")
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
EXCERPT_MAX_CHARS = 600


@dataclass
class CitationCheck:
    content: str
    answer_status: str  # answered | not_found | unsupported
    valid: list[int] = field(default_factory=list)  # marker numbers, first-use order
    invalid: list[str] = field(default_factory=list)
    sentences_by_marker: dict[int, list[str]] = field(default_factory=dict)


def check_citations(text: str, n_sources: int) -> CitationCheck:
    stripped = text.strip()
    if stripped.startswith(NO_ANSWER):
        body = stripped[len(NO_ANSWER) :].strip()
        markers = [m for g in _GROUP.findall(body) for m in re.split(r"\s*[,;]\s*", g)]
        body = _GROUP.sub("", body).strip()
        return CitationCheck(body, "not_found", invalid=markers)

    valid: list[int] = []
    invalid: list[str] = []

    def replace(match: re.Match[str]) -> str:
        keep = []
        for marker in re.split(r"\s*[,;]\s*", match.group(1)):
            number = int(marker[1:])
            if 1 <= number <= n_sources:
                keep.append(number)
                if number not in valid:
                    valid.append(number)
            else:
                invalid.append(marker)
        if not keep:
            return ""
        lead = " " if match.group(0).startswith(" ") else ""
        return lead + "".join(f"[S{n}]" for n in keep)

    content = _GROUP.sub(replace, stripped).strip()
    by_marker: dict[int, list[str]] = {}
    for sentence in re.split(r"(?<=[.!?\]])\s+", content):
        for number in {int(n) for n in re.findall(r"\[S(\d+)\]", sentence)}:
            by_marker.setdefault(number, []).append(sentence)
    return CitationCheck(
        content=content,
        answer_status="answered" if valid else "unsupported",
        valid=valid,
        invalid=invalid,
        sentences_by_marker=by_marker,
    )


def best_excerpt(chunk_text: str, focus: str, max_chars: int = EXCERPT_MAX_CHARS) -> str:
    """Return a contiguous substring of the stored chunk around the sentence that best matches
    `focus` (the question plus the answer sentences citing this chunk)."""
    if len(chunk_text) <= max_chars:
        return chunk_text
    spans = [(m.start(), m.end()) for m in _SENTENCE.finditer(chunk_text) if m.group().strip()]
    if not spans:
        return chunk_text[:max_chars]
    target = set(content_words(focus))

    def score(span: tuple[int, int]) -> int:
        return len(target & set(content_words(chunk_text[span[0] : span[1]])))

    best = max(range(len(spans)), key=lambda i: (score(spans[i]), -i))
    lo = hi = best
    while True:
        grew = False
        if hi + 1 < len(spans) and spans[hi + 1][1] - spans[lo][0] <= max_chars:
            hi += 1
            grew = True
        if lo > 0 and spans[hi][1] - spans[lo - 1][0] <= max_chars:
            lo -= 1
            grew = True
        if not grew:
            break
    start, end = spans[lo][0], spans[hi][1]
    if end - start > max_chars:  # a single very long sentence
        end = start + max_chars
    return chunk_text[start:end].strip()
