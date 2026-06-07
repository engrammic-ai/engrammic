import pytest

from context_service.mcp.tools import recall as recall_mod


class _FakePreset:
    param_overrides = {"default_recall_top_k": 15}


class _FakeResolver:
    async def resolve(self, silo_id: str) -> _FakePreset:
        return _FakePreset()


@pytest.fixture()
def _patch(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    async def _fake_context_recall(
        *,
        silo_id: str,
        query: str | None,
        node_ids: list[str] | None,
        depth: int,
        layers: list[str] | None,
        top_k: int,
        bypass_cache: bool = False,
        max_age_seconds: int | None = None,
        min_threshold: float | None = None,
        include_content: bool | None = True,
    ) -> dict[str, object]:
        captured["top_k"] = top_k
        return {"results": []}

    async def _auth() -> object:
        class A:
            org_id = "org-1"
            session_id = None
            db_user_id = None

        return A()

    monkeypatch.setattr(recall_mod, "_context_recall", _fake_context_recall)
    monkeypatch.setattr(recall_mod, "get_mcp_auth_context", _auth)
    monkeypatch.setattr(recall_mod, "derive_silo_id", lambda _: "silo-1")
    monkeypatch.setattr(recall_mod, "get_preset_resolver", lambda: _FakeResolver(), raising=False)
    return captured


@pytest.mark.asyncio
async def test_top_k_defaults_from_preset(_patch: dict[str, object]) -> None:
    await recall_mod._recall_impl(query="x")
    assert _patch["top_k"] == 15


@pytest.mark.asyncio
async def test_explicit_top_k_overrides_preset(_patch: dict[str, object]) -> None:
    await recall_mod._recall_impl(query="x", top_k=3)
    assert _patch["top_k"] == 3


@pytest.mark.asyncio
async def test_top_k_falls_back_to_literal_when_resolver_unconfigured(
    _patch: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raising_resolver() -> object:
        raise RuntimeError("not configured")

    monkeypatch.setattr(recall_mod, "get_preset_resolver", _raising_resolver)
    await recall_mod._recall_impl(query="x")
    assert _patch["top_k"] == 10
