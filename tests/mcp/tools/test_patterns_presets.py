"""Tests for preset-aware patterns tool resolution and ranking."""

from __future__ import annotations

import pytest

from context_service.mcp.tools import patterns as patterns_mod


class _Skill:
    def __init__(self, name: str):
        self.name = name

    def model_dump(self, exclude_none: bool = True) -> dict[str, str]:
        return {"name": self.name}


class _FakeSkillSvc:
    def __init__(self) -> None:
        self.last_namespace: str | None = "UNSET"  # type: ignore[assignment]

    async def list(
        self,
        silo_id: str,
        namespace: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[_Skill]:
        self.last_namespace = namespace
        return [_Skill("engrammic:recall"), _Skill("coding:onboarding")]

    async def get(self, silo_id: str, name: str) -> _Skill | None:
        return _Skill(name) if name == "coding:onboarding" else None

    async def search(
        self,
        silo_id: str,
        query: str,
        namespace: str | None = None,
        limit: int = 20,
    ) -> list[_Skill]:
        self.last_namespace = namespace
        return [_Skill("engrammic:recall"), _Skill("coding:onboarding")]


class _FakePreset:
    name = "coding"
    namespace = "coding"
    onboarding_skill = "coding:onboarding"


class _FakeResolver:
    async def resolve(self, silo_id: str) -> _FakePreset:
        return _FakePreset()


@pytest.fixture(autouse=True)
def _patch(monkeypatch: pytest.MonkeyPatch) -> _FakeSkillSvc:
    svc = _FakeSkillSvc()
    monkeypatch.setattr(patterns_mod, "get_skill_service", lambda: svc)
    monkeypatch.setattr(patterns_mod, "get_preset_resolver", lambda: _FakeResolver())

    async def _auth() -> object:
        class A:
            org_id = "org-1"

        return A()

    monkeypatch.setattr(patterns_mod, "get_mcp_auth_context", _auth)
    monkeypatch.setattr(patterns_mod, "derive_silo_id", lambda _: "silo-1")
    return svc


@pytest.mark.asyncio
async def test_list_without_profile_ranks_preset_namespace_first(
    _patch: _FakeSkillSvc,
) -> None:
    out = await patterns_mod._patterns_impl("list")
    names = [p["name"] for p in out["patterns"]]
    assert names[0] == "coding:onboarding"
    assert "engrammic:recall" in names
    assert _patch.last_namespace is None


@pytest.mark.asyncio
async def test_explicit_profile_passed_through_as_namespace(
    _patch: _FakeSkillSvc,
) -> None:
    await patterns_mod._patterns_impl("list", profile="reasoning")
    assert _patch.last_namespace == "reasoning"


@pytest.mark.asyncio
async def test_get_bare_name_autoqualifies_to_preset_namespace(
    _patch: _FakeSkillSvc,
) -> None:
    out = await patterns_mod._patterns_impl("get", name="onboarding")
    assert out["pattern"]["name"] == "coding:onboarding"


@pytest.mark.asyncio
async def test_get_qualified_name_passed_through(
    _patch: _FakeSkillSvc,
) -> None:
    out = await patterns_mod._patterns_impl("get", name="engrammic:recall")
    assert out["error"] == "not_found"
