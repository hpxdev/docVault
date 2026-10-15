"""Choose the parts of a document that fit an on-demand prompt (custom summary, comparison).

Small documents are sent whole. A document over the token budget is cut into windows of at most
`PIECE_TOKENS`; with a focus, the windows sharing the most words with it are taken first,
otherwise windows spread evenly over the document. The chosen windows keep their markers and
document order, and the coverage report says exactly how much was included, so a partial input
is never presented as the whole document.
"""

from typing import Any

from app.ai.fakes import content_words
from app.services.insights import MarkedSegment, piece_cost, split_large

PIECE_TOKENS = 1500


def spread_order(n: int) -> list[int]:
    """0, n/2, n/4, 3n/4, …: any prefix of the order is spread over the whole range."""
    order: list[int] = []
    seen: set[int] = set()
    step = n
    while len(order) < n:
        for i in range(0, n, max(1, step)):
            if i not in seen:
                seen.add(i)
                order.append(i)
        step //= 2
    return order


def select_parts(
    parts: list[MarkedSegment], budget: int, focus: str | None
) -> tuple[list[MarkedSegment], dict[str, Any]]:
    total_segments = len({p.segment_id for p in parts})
    costs = [piece_cost(p) for p in parts]
    if sum(costs) <= budget:
        return parts, {
            "segments_total": total_segments,
            "segments_included": total_segments,
            "complete": True,
            "selection": "all",
            "input_token_budget": budget,
        }
    pieces = split_large(parts, PIECE_TOKENS)
    costs = [piece_cost(p) for p in pieces]
    terms = set(content_words(focus or ""))
    if terms:
        scores = [len(terms & set(content_words(p.text))) for p in pieces]
        order = sorted(range(len(pieces)), key=lambda i: (-scores[i], i))
        selection = "focus"
    else:
        order = spread_order(len(pieces))
        selection = "spread"
    chosen: list[int] = []
    used = 0
    for i in order:
        if used + costs[i] <= budget:
            chosen.append(i)
            used += costs[i]
    chosen.sort()
    selected = [pieces[i] for i in chosen]
    return selected, {
        "segments_total": total_segments,
        "segments_included": len({p.segment_id for p in selected}),
        "complete": False,
        "selection": selection,
        "input_token_budget": budget,
    }
