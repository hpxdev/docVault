"""Hybrid retrieval restricted to an allowed set of documents (always filtered server-side).

- Vector search, document scope: an **exact** scan over the scoped chunks. The MATERIALIZED CTE
  stops the planner from using the HNSW index, whose post-filtering on `document_id` could
  return fewer than k rows.
- Vector search, whole vault (`scope_mode=all`): HNSW with pgvector iterative index scans
  (`hnsw.iterative_scan = relaxed_order`, pgvector >= 0.8) so filtering cannot starve results;
  rows are re-sorted by exact distance afterwards.
- Full-text search: Postgres `tsvector` (GIN) with OR semantics over the query's lexemes.
- Fusion: Reciprocal Rank Fusion (k=60), then a soft per-document cap. For document scope the
  candidate lists are per document (up to 20 each), so every scoped document can contribute.
"""

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from app.db.session import get_async_engine

RRF_K = 60
CANDIDATES = 20  # per list (per document for scoped search)
MAX_SCOPED_CANDIDATES = 200

# Exact scan with per-document candidate lists, so a small document is never crowded out of the
# candidate set by a large one before fusion (the soft cap below can only pick from candidates).
_VECTOR_SCOPED = text(
    """
    WITH scoped AS MATERIALIZED (
        SELECT id, document_id, embedding <=> CAST(:q AS vector) AS distance FROM chunks
        WHERE document_id = ANY(:ids) AND embedding_model = :model
    ), ranked AS (
        SELECT id, distance,
               row_number() OVER (PARTITION BY document_id ORDER BY distance, id) AS rn
        FROM scoped
    )
    SELECT id, distance FROM ranked WHERE rn <= :per_doc ORDER BY distance, id LIMIT :k
    """
)
_VECTOR_VAULT = text(
    """
    SELECT id, embedding <=> CAST(:q AS vector) AS distance
    FROM chunks
    WHERE document_id = ANY(:ids) AND embedding_model = :model
    ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k
    """
)
# plainto_tsquery normalises the question (stemming, stopwords); swapping AND for OR lets any
# term match, and ts_rank_cd still rewards chunks matching more terms. 'simple' re-parses the
# already-normalised lexemes without stemming them twice.
_FULLTEXT = text(
    """
    WITH q AS (
        SELECT to_tsquery('simple', replace(plainto_tsquery('english', :text)::text, '&', '|'))
               AS query
    ), hits AS (
        SELECT c.id, ts_rank_cd(c.tsv, q.query) AS rank,
               row_number() OVER (
                   PARTITION BY c.document_id ORDER BY ts_rank_cd(c.tsv, q.query) DESC, c.id
               ) AS rn
        FROM chunks c, q
        WHERE c.document_id = ANY(:ids) AND c.embedding_model = :model
          AND q.query <> ''::tsquery AND c.tsv @@ q.query
    )
    SELECT id, rank FROM hits WHERE rn <= :per_doc ORDER BY rank DESC, id LIMIT :k
    """
)
_DETAILS = text(
    """
    SELECT c.id, c.document_id, d.filename, c.text, c.locator, c.page_number, c.ordinal
    FROM chunks c JOIN documents d ON d.id = c.document_id
    WHERE c.id = ANY(:ids)
    """
)


@dataclass
class Candidate:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    text: str
    locator: dict[str, Any]
    page_number: int | None
    vector_rank: int | None = None
    similarity: float | None = None
    fts_rank: int | None = None
    fts_score: float | None = None
    rrf: float = 0.0

    def trace(self) -> dict[str, Any]:
        return {
            "chunk_id": str(self.chunk_id),
            "document_id": str(self.document_id),
            "vector_rank": self.vector_rank,
            "similarity": None if self.similarity is None else round(self.similarity, 4),
            "fts_rank": self.fts_rank,
            "rrf": round(self.rrf, 5),
        }


@dataclass
class RetrievalResult:
    chunks: list[Candidate]
    mode: str
    trace: dict[str, Any] = field(default_factory=dict)


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


def rrf_fuse(
    vector_hits: list[tuple[uuid.UUID, float]], fts_hits: list[tuple[uuid.UUID, float]]
) -> dict[uuid.UUID, dict[str, Any]]:
    fused: dict[uuid.UUID, dict[str, Any]] = {}
    for rank, (chunk_id, distance) in enumerate(vector_hits, start=1):
        entry = fused.setdefault(chunk_id, {"rrf": 0.0})
        entry.update(vector_rank=rank, similarity=1.0 - float(distance))
        entry["rrf"] += 1.0 / (RRF_K + rank)
    for rank, (chunk_id, score) in enumerate(fts_hits, start=1):
        entry = fused.setdefault(chunk_id, {"rrf": 0.0})
        entry.update(fts_rank=rank, fts_score=float(score))
        entry["rrf"] += 1.0 / (RRF_K + rank)
    return fused


def apply_document_cap(
    ranked: list[Candidate], top_k: int, n_docs: int
) -> tuple[list[Candidate], int | None, int]:
    """Soft cap: first take at most `cap` chunks per document in rank order, then fill any
    remaining slots from the leftovers. Returns (selected, cap, backfilled)."""
    if n_docs <= 1:
        return ranked[:top_k], None, 0
    cap = max(2, math.ceil(top_k / n_docs))
    selected, leftovers, per_doc = [], [], {}
    for cand in ranked:
        if len(selected) < top_k and per_doc.get(cand.document_id, 0) < cap:
            selected.append(cand)
            per_doc[cand.document_id] = per_doc.get(cand.document_id, 0) + 1
        else:
            leftovers.append(cand)
    backfill = leftovers[: max(0, top_k - len(selected))]
    selected += backfill
    selected.sort(key=lambda c: -c.rrf)
    return selected, cap, len(backfill)


async def retrieve(
    query_text: str,
    query_vector: list[float],
    document_ids: list[uuid.UUID],
    *,
    vault_wide: bool,
    embedding_model: str,
    top_k: int,
) -> RetrievalResult:
    started = time.perf_counter()
    if vault_wide:  # global top candidates (HNSW); per-document lists would not scale
        params = {"ids": list(document_ids), "model": embedding_model, "k": CANDIDATES}
        params["per_doc"] = CANDIDATES
    else:
        params = {
            "ids": list(document_ids),
            "model": embedding_model,
            "per_doc": CANDIDATES,
            "k": min(MAX_SCOPED_CANDIDATES, CANDIDATES * max(1, len(document_ids))),
        }
    async with get_async_engine().connect() as conn, conn.begin():
        if vault_wide:
            await conn.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
            await conn.execute(text("SET LOCAL hnsw.ef_search = 100"))
            rows = await conn.execute(_VECTOR_VAULT, {**params, "q": vector_literal(query_vector)})
            vector_hits = sorted(((r.id, r.distance) for r in rows), key=lambda x: x[1])
        else:
            rows = await conn.execute(_VECTOR_SCOPED, {**params, "q": vector_literal(query_vector)})
            vector_hits = [(r.id, r.distance) for r in rows]
        fts_rows = await conn.execute(_FULLTEXT, {**params, "text": query_text})
        fts_hits = [(r.id, r.rank) for r in fts_rows]
        fused = rrf_fuse(vector_hits, fts_hits)
        details = await conn.execute(_DETAILS, {"ids": list(fused)})
        by_id = {r.id: r for r in details}

    candidates = []
    for chunk_id, info in fused.items():
        row = by_id.get(chunk_id)
        if row is None:  # chunk deleted between queries
            continue
        candidates.append(
            Candidate(
                chunk_id=chunk_id,
                document_id=row.document_id,
                document_name=row.filename,
                text=row.text,
                locator=row.locator,
                page_number=row.page_number,
                vector_rank=info.get("vector_rank"),
                similarity=info.get("similarity"),
                fts_rank=info.get("fts_rank"),
                fts_score=info.get("fts_score"),
                rrf=info["rrf"],
            )
        )
    candidates.sort(key=lambda c: (-c.rrf, c.vector_rank or 10**6))
    n_docs = len({c.document_id for c in candidates})
    selected, cap, backfilled = apply_document_cap(candidates, top_k, n_docs)
    mode = "vault_hnsw" if vault_wide else "scoped_exact"
    return RetrievalResult(
        chunks=selected,
        mode=mode,
        trace={
            "mode": mode,
            "vector_candidates": len(vector_hits),
            "fulltext_candidates": len(fts_hits),
            "fused_candidates": len(candidates),
            "per_document_cap": cap,
            "backfilled": backfilled,
            "top_k": top_k,
            "candidates": [c.trace() for c in candidates[:40]],
            "retrieval_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    )
