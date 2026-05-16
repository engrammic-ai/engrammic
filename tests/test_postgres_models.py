from sqlalchemy import inspect

from context_service.models.inference import Conclusion
from context_service.models.postgres.audit import AuditEvents, Events
from context_service.models.postgres.org import OrgPreferences, SiloConfig
from context_service.models.postgres.reasoning import (
    OrphanedChains,
    ReasoningChainSteps,
)


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
        "preset",
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


def test_reasoning_chain_steps_columns():
    """ReasoningChainSteps has required columns."""
    mapper = inspect(ReasoningChainSteps)
    columns = {c.key for c in mapper.columns}
    assert columns == {
        "chain_id",
        "silo_id",
        "steps",
        "created_at",
        "updated_at",
    }


def test_orphaned_chains_columns():
    """OrphanedChains has required columns for dead-letter."""
    mapper = inspect(OrphanedChains)
    columns = {c.key for c in mapper.columns}
    assert columns == {
        "chain_id",
        "silo_id",
        "failed_at",
        "retry_count",
        "last_error",
    }


def test_events_columns():
    """Events has required columns including expires_at for TTL."""
    mapper = inspect(Events)
    columns = {c.key for c in mapper.columns}
    assert "expires_at" in columns
    assert "silo_id" in columns
    assert "event_type" in columns
    assert "source_chain_id" in columns
    assert "content" in columns


def test_audit_events_has_actor_fields():
    """AuditEvents tracks who triggered the event."""
    mapper = inspect(AuditEvents)
    columns = {c.key for c in mapper.columns}
    assert "actor_id" in columns
    assert "actor_type" in columns


def test_conclusion_model_fields():
    """Conclusion has required fields including valid_to."""
    conclusion = Conclusion(
        silo_id="test-silo",
        query_context_hash="abc123",
        content="User prefers X",
        confidence=0.9,
        created_by_agent_id="agent-1",
    )
    assert conclusion.status == "active"
    assert conclusion.valid_to is None
    assert hasattr(conclusion, "valid_from")
