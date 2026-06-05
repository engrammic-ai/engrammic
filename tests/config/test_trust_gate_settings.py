from context_service.config.settings import Settings


def test_trust_gate_defaults():
    s = Settings()
    assert s.trust_gate.enabled is True
    assert s.trust_gate.withhold_unresolved_conflicts is True
    # Floor defaults OFF (0.0): conflict-withholding is the safe v1 demo;
    # raise per deployment to also withhold low-confidence memory.
    assert s.trust_gate.confidence_floor == 0.0
