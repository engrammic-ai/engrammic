"""Fixtures and configuration for HIL eval tests."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from context_service.config.settings import get_settings
from context_service.services.context import ContextService
from context_service.services.models import ScopeContext
from context_service.stores import MemgraphClient, QdrantClient

# Re-export integration fixtures so evals can use them without double-declaration.
from tests.integration.conftest import (  # noqa: F401
    cleanup_silo,
    memgraph_client,
    memgraph_driver,
    unique_org_id,
    unique_silo_id,
)

if TYPE_CHECKING:
    pass


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--with-llm",
        action="store_true",
        default=False,
        help="Enable eval cases that call live LLM APIs.",
    )
    parser.addoption(
        "--llm-provider",
        default="anthropic",
        choices=["anthropic", "openai", "gemini", "vertex"],
        help="LLM provider to use when --with-llm is active.",
    )
    parser.addoption(
        "--eval-output",
        default=None,
        metavar="PATH",
        help="Write eval results as JSON to this file path.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "evals: mark test as an HIL quality eval")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Any:
    """Auto-capture eval test results for JSON output."""
    outcome = yield
    report = outcome.get_result()

    if call.when != "call":
        return

    if not any(mark.name == "evals" for mark in item.iter_markers()):
        return

    item._eval_report = {  # type: ignore[attr-defined]
        "name": item.name,
        "nodeid": item.nodeid,
        "outcome": report.outcome,
        "duration_s": round(report.duration, 3),
        "failed_reason": str(report.longrepr) if report.failed else None,
    }


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:  # noqa: ARG001
    output_path: str | None = session.config.getoption("--eval-output", default=None)
    if not output_path:
        return

    results: list[dict[str, Any]] = []
    for item in session.items:
        rep = getattr(item, "_eval_report", None)
        if rep is None:
            continue
        results.append(rep)

    Path(output_path).write_text(json.dumps(results, indent=2))


@pytest.fixture
def llm_provider(request: pytest.FixtureRequest) -> str:
    return str(request.config.getoption("--llm-provider"))


@pytest.fixture
def with_llm(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--with-llm"))


@pytest.fixture
def scope_context(
    unique_org_id: str,  # noqa: F811
    unique_silo_id: uuid.UUID,  # noqa: F811
) -> ScopeContext:
    return ScopeContext(org_id=unique_org_id, silo_id=unique_silo_id)


@pytest.fixture
async def context_service(
    memgraph_client: MemgraphClient,  # noqa: F811
) -> ContextService:
    """Wired ContextService with embedding for eval tests."""
    from context_service.embeddings.jina import JinaEmbeddingService

    settings = get_settings()
    qdrant = QdrantClient.from_settings(settings)
    await qdrant.ensure_collection()
    embedding = JinaEmbeddingService.from_settings(settings)
    return ContextService(memgraph=memgraph_client, qdrant=qdrant, embedding=embedding)
