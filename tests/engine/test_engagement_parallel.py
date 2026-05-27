"""Tests for parallel check runner with timeouts."""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_parallel_checks_complete_within_timeout():
    from context_service.engine.engagement import run_parallel_checks

    async def fast_check():
        await asyncio.sleep(0.01)
        return {"markers": [{"id": "m1"}]}

    async def slow_check():
        await asyncio.sleep(0.5)  # Exceeds 30ms individual timeout
        return {"hypotheses": []}

    checks = {
        "markers": fast_check(),
        "hypotheses": slow_check(),
    }

    results, completed, skipped = await run_parallel_checks(
        checks,
        individual_timeout=0.03,
        total_timeout=0.08,
    )

    assert "markers" in completed
    assert "hypotheses" in skipped
    assert results.get("markers") == {"markers": [{"id": "m1"}]}


@pytest.mark.asyncio
async def test_parallel_checks_respects_total_timeout():
    from context_service.engine.engagement import run_parallel_checks

    async def slow_check_1():
        await asyncio.sleep(0.1)
        return {"result": 1}

    async def slow_check_2():
        await asyncio.sleep(0.1)
        return {"result": 2}

    checks = {
        "check1": slow_check_1(),
        "check2": slow_check_2(),
    }

    results, completed, skipped = await run_parallel_checks(
        checks,
        individual_timeout=0.15,
        total_timeout=0.05,  # Both should be skipped
    )

    assert len(completed) == 0
    assert len(skipped) == 2
