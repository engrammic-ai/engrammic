from context_service.custodian.identities import (
    CustodianIdentity,
    GroundskeeperIdentity,
    ValidatorIdentity,
)


def test_all_identities_importable():
    """Smoke test: all identities can be imported."""
    assert CustodianIdentity is not None
    assert GroundskeeperIdentity is not None
    assert ValidatorIdentity is not None
