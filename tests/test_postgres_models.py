from sqlalchemy import inspect, text

from context_service.models.postgres.org import OrgPreferences, SiloConfig


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


def test_silo_config_columns():
    """SiloConfig has required columns."""
    mapper = inspect(SiloConfig)
    columns = {c.key for c in mapper.columns}
    assert columns == {
        "silo_id",
        "org_id",
        "name",
        "quotas",
        "feature_flags",
        "created_at",
        "updated_at",
    }


def test_silo_config_defaults():
    """SiloConfig has correct defaults for JSONB fields."""
    silo = SiloConfig(silo_id="test-silo", org_id="test-org", name="Test Silo")
    assert silo.quotas == {}
    assert silo.feature_flags == {}


def test_silo_config_server_defaults():
    """SiloConfig JSONB columns have server_default set."""
    table = SiloConfig.__table__
    assert table.c["quotas"].server_default is not None
    assert table.c["feature_flags"].server_default is not None


def test_org_preferences_server_defaults():
    """OrgPreferences columns have server_default set."""
    table = OrgPreferences.__table__
    assert table.c["default_llm"].server_default is not None
    assert table.c["embedding_model"].server_default is not None
    assert table.c["settings"].server_default is not None
