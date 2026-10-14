from alembic import command
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from tests.conftest import alembic_config


def _scalar(sql: str):
    engine = create_engine(get_settings().database_url)
    with engine.begin() as conn:
        value = conn.execute(text(sql)).scalar()
    engine.dispose()
    return value


def test_schema_has_vector_indexes_and_generated_tsv():
    assert _scalar("SELECT extversion FROM pg_extension WHERE extname='vector'")
    hnsw = _scalar("SELECT indexdef FROM pg_indexes WHERE indexname='ix_chunks_embedding_hnsw'")
    assert "hnsw" in hnsw and "vector_cosine_ops" in hnsw
    gin = _scalar("SELECT indexdef FROM pg_indexes WHERE indexname='ix_chunks_tsv'")
    assert "gin" in gin
    generated = _scalar(
        "SELECT is_generated FROM information_schema.columns "
        "WHERE table_name='chunks' AND column_name='tsv'"
    )
    assert generated == "ALWAYS"


def test_pgvector_supports_iterative_index_scans():
    # pgvector >= 0.8.0 exposes hnsw.iterative_scan; retrieval relies on it for scope_mode=all.
    engine = create_engine(get_settings().database_url)
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        assert conn.execute(text("SHOW hnsw.iterative_scan")).scalar() == "relaxed_order"
    engine.dispose()


def test_downgrade_then_upgrade_round_trip():
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    assert _scalar("SELECT to_regclass('public.documents')") is None
    command.upgrade(cfg, "head")
    assert _scalar("SELECT to_regclass('public.documents')") == "documents"
