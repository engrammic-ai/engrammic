import pytest
from pydantic import ValidationError

from context_service.models.postgres.skill import MAX_BODY_SIZE
from context_service.schemas.skill import SkillCreate, SkillUpdate


def test_skill_create_validates_name_format():
    """Name must be namespace:name format."""
    valid = SkillCreate(name="myorg:mytool", description="desc", body="body")
    assert valid.name == "myorg:mytool"


def test_skill_create_rejects_invalid_name():
    """Name with invalid chars should fail."""
    with pytest.raises(ValidationError):
        SkillCreate(name="Invalid Name!", description="desc", body="body")


def test_skill_create_rejects_engrammic_namespace():
    """The engrammic: namespace is reserved and should be rejected."""
    with pytest.raises(ValidationError):
        SkillCreate(name="engrammic:something", description="desc", body="body")


def test_skill_create_enforces_body_size():
    """Body over MAX_BODY_SIZE should fail."""
    with pytest.raises(ValidationError):
        SkillCreate(name="org:tool", description="desc", body="x" * (MAX_BODY_SIZE + 1))


def test_skill_update_allows_partial():
    """SkillUpdate should allow partial updates."""
    update = SkillUpdate(description="new desc")
    assert update.description == "new desc"
    assert update.body is None
