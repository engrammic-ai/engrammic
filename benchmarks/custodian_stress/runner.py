"""Standalone runner for custodian stress tests."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from benchmarks.custodian_stress.harness import HarnessConfig, StressHarness
from benchmarks.custodian_stress.mocks import MockLLMClient
from benchmarks.custodian_stress.scenarios import (
    concurrency,
    edge_cases,
    history,
    recovery,
    security,
    synthesis,
    volume,
)


async def run_all_scenarios(
    store: Any,
    config: HarnessConfig,
) -> StressHarness:
    """Run all stress scenarios and return harness with results."""
    harness = StressHarness(store=store, config=config)
    mock_llm = MockLLMClient() if not config.real_llm else None

    # Volume scenarios
    harness.add_result(await volume.test_500_commitments_consensus(store, mock_llm=mock_llm))
    harness.add_result(await volume.test_uneven_cluster_scaling(store, mock_llm=mock_llm))

    # Edge case scenarios
    harness.add_result(await edge_cases.test_supersession_chain_terminal_only(store, mock_llm=mock_llm))
    harness.add_result(await edge_cases.test_circular_dep_no_hang(store))
    harness.add_result(await edge_cases.test_cross_cluster_supersession_chain(store, mock_llm=mock_llm))

    # Concurrency scenarios
    harness.add_result(await concurrency.test_no_duplicate_findings(store))
    harness.add_result(await concurrency.test_no_duplicate_supersedes_edges(store))

    # Recovery scenarios
    harness.add_result(await recovery.test_enum_recovery_uppercase())
    harness.add_result(await recovery.test_enum_recovery_titlecase())

    # Security scenarios
    harness.add_result(await security.test_cross_tenant_citation_rejected(store))

    # Synthesis scenarios
    harness.add_result(await synthesis.test_silo_synthesis_creates_summary(store, mock_llm=mock_llm))

    # History scenarios
    harness.add_result(await history.test_finding_history_trim(store))

    return harness


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Custodian stress test runner")
    parser.add_argument("--real-llm", action="store_true", help="Use real LLM client")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    parser.add_argument("--timeout", type=float, default=300.0, help="Timeout per scenario")
    args = parser.parse_args()

    config = HarnessConfig(
        real_llm=args.real_llm,
        timeout_s=args.timeout,
    )

    # Connect to Memgraph
    try:
        from context_service.config.settings import get_settings
        from context_service.engine.memgraph_store import MemgraphStore

        settings = get_settings()
        store = MemgraphStore(
            host=settings.memgraph_host,
            port=settings.memgraph_port,
            user=settings.memgraph_user,
            password=settings.memgraph_password,
        )
        await store.connect()
    except Exception as e:
        print(f"Failed to connect to Memgraph: {e}", file=sys.stderr)
        return 1

    try:
        harness = await run_all_scenarios(store, config)
        result = harness.aggregate()

        if args.json:
            print(result.to_json())
        else:
            harness.print_summary()

        return 0 if result.failed == 0 else 1

    finally:
        await store.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
