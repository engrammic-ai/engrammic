from sqlalchemy import inspect

from context_service.models.postgres.org import OrgPreferences


def test_org_preferences_columns():
    """OrgPreferences has required columns."""
    mapper = inspect(OrgPreferences)
    columns = {c.key for c in mapper.columns}
    assert columns == {
        "org_id",
        "default_llm",
        "embedding_model",
        "settings",
        "created_at",
        "updated_at",
    }


def test_org_preferences_defaults():
    """OrgPreferences has correct defaults."""
    org = OrgPreferences(org_id="test-org")
    assert org.default_llm == "claude-haiku-4-5-20251001"
    assert org.embedding_model == "jina-embeddings-v3"
    assert org.settings == {}
