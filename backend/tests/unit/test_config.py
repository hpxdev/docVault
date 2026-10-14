import pytest

from app.core.config import Settings


@pytest.mark.parametrize("raw", ["", "   ", "# set in .env only; never commit"])
def test_blank_or_comment_only_key_counts_as_missing(raw):
    s = Settings(_env_file=None, ai_provider="openai", openai_api_key=raw)
    assert s.openai_api_key is None
    assert s.ai_configured is False


def test_fake_mode_labels_models_as_fake():
    s = Settings(_env_file=None, ai_provider="fake")
    assert s.ai_configured and s.chat_model_name == "fake" and s.embedding_model_name == "fake"


def test_embedding_dimensions_must_match_schema():
    with pytest.raises(ValueError):
        Settings(_env_file=None, embedding_dimensions=768)
