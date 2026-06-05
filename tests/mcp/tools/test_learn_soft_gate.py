from dataclasses import dataclass

import pytest

from context_service.mcp.tools.learn import _learn_impl


@dataclass(frozen=True)
class _Cfg:
    enabled: bool
    enforce: bool


@pytest.mark.asyncio
async def test_soft_mode_stores_and_warns_without_evidence(
    mock_mcp_context, mock_context_service, mock_evidence_validator, monkeypatch
):
    import context_service.mcp.tools.learn as learn_mod

    fake_settings = type("S", (), {"evidence_enforcement": _Cfg(enabled=True, enforce=False)})()
    monkeypatch.setattr(learn_mod, "get_settings", lambda: fake_settings)

    result = await _learn_impl(claim="Sky is blue", evidence=[], source="user")

    assert "error" not in result
    assert "node_id" in result
    assert "warning" in result


@pytest.mark.asyncio
async def test_hard_mode_rejects_without_evidence(
    mock_mcp_context, mock_context_service, monkeypatch
):
    from primitives.eag.transitions import MissingEvidenceError

    import context_service.mcp.tools.learn as learn_mod

    fake_settings = type("S", (), {"evidence_enforcement": _Cfg(enabled=True, enforce=True)})()
    monkeypatch.setattr(learn_mod, "get_settings", lambda: fake_settings)

    with pytest.raises(MissingEvidenceError):
        await _learn_impl(claim="Sky is blue", evidence=[], source="user")
