from context_service.config.settings import Settings


def test_default_icp_preset_defaults_to_coding():
    s = Settings()
    assert s.default_icp_preset == "coding"


def test_default_icp_preset_env_override(monkeypatch):
    monkeypatch.setenv("DEFAULT_ICP_PRESET", "b2b-ops")
    s = Settings()
    assert s.default_icp_preset == "b2b-ops"
