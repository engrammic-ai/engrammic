from uuid import uuid4

from context_service.models.postgres.org import SiloConfig


def test_silo_config_has_nullable_preset_default_none():
    sc = SiloConfig(silo_id=uuid4(), org_id=uuid4(), name="s1")
    assert sc.preset is None


def test_silo_config_accepts_preset():
    sc = SiloConfig(silo_id=uuid4(), org_id=uuid4(), name="s1", preset="coding")
    assert sc.preset == "coding"
