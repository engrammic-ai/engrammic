import pytest
from pydantic import ValidationError

from context_service.schemas.skill import SkillCreate


@pytest.mark.parametrize("ns", ["engrammic", "coding", "b2b-ops"])
def test_reserved_namespaces_rejected(ns):
    with pytest.raises(ValidationError):
        SkillCreate(name=f"{ns}:mine", description="d", body="b")


def test_non_reserved_namespace_allowed():
    s = SkillCreate(name="acme:mine", description="d", body="b")
    assert s.name == "acme:mine"
