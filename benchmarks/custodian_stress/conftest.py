"""Pytest fixtures for custodian stress tests."""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING

import pytest

from benchmarks.custodian_stress.mocks import MockCitationValidator, MockLLMClient

if TYPE_CHECKING:
    pass


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "stress: marks tests as stress tests")


@pytest.fixture(scope="session")
def docker_stack_available() -> bool:
    """Check if docker stack is available."""
    memgraph_host = os.environ.get("MEMGRAPH_HOST", "localhost")
    memgraph_port = os.environ.get("MEMGRAPH_PORT", "7687")

    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((memgraph_host, int(memgraph_port)))
        sock.close()
        return result == 0
    except Exception:
        return False


@pytest.fixture
def fresh_silo_id() -> str:
    """Generate a unique silo ID for test isolation."""
    return f"stress-test-{uuid.uuid4()}"


@pytest.fixture
def mock_llm_client() -> MockLLMClient:
    """Provide a mock LLM client with deterministic responses."""
    return MockLLMClient(responses=['{"pairs": []}'])


@pytest.fixture
def mock_citation_validator() -> MockCitationValidator:
    """Provide a mock citation validator."""
    return MockCitationValidator()
