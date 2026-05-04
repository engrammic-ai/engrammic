"""Mock validators and LLM clients for controlled failure injection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MockLLMResponse:
    """Canned LLM response for deterministic tests."""

    content: str


class MockLLMClient:
    """Deterministic LLM client for testing."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = responses or []
        self._call_count = 0

    async def complete(  # noqa: ARG002
        self,
        _prompt: str,
        *,
        _temperature: float | None = None,
    ) -> str:
        if self._call_count < len(self._responses):
            response = self._responses[self._call_count]
        else:
            response = '{"pairs": []}'
        self._call_count += 1
        return response

    @property
    def call_count(self) -> int:
        return self._call_count


class FailingValidator:
    """Validator that fails after N successful validations."""

    def __init__(self, fail_after: int, error_message: str = "Injected failure") -> None:
        self.fail_after = fail_after
        self.error_message = error_message
        self._validation_count = 0

    async def validate(self, *_args: Any, **kwargs: Any) -> dict[str, Any]:
        self._validation_count += 1
        if self._validation_count > self.fail_after:
            raise RuntimeError(self.error_message)
        return {"valid": True, "node_id": kwargs.get("node_id", "unknown")}


class SlowValidator:
    """Validator that introduces artificial delay."""

    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s

    async def validate(self, *_args: Any, **kwargs: Any) -> dict[str, Any]:
        import asyncio

        await asyncio.sleep(self.delay_s)
        return {"valid": True, "node_id": kwargs.get("node_id", "unknown")}


class MockCitationValidator:
    """Mock citation validator for testing."""

    def __init__(self, valid_node_ids: set[str] | None = None) -> None:
        self.valid_node_ids = valid_node_ids or set()
        self._seen_node_ids: set[str] = set()

    async def evaluate(  # noqa: ARG002
        self,
        claims: list[Any],
        *,
        memgraph_client: Any = None,  # noqa: ARG002
        silo_id: str = "",  # noqa: ARG002
    ) -> tuple[list[Any], Any]:
        """Return all claims as valid if their node_ids are in valid_node_ids."""
        valid_claims = []
        for claim in claims:
            citations_valid = True
            for citation in getattr(claim, "citations", []):
                if citation.node_id not in self.valid_node_ids:
                    citations_valid = False
                    break
            if citations_valid:
                valid_claims.append(claim)

        @dataclass
        class MockRejectionMetrics:
            total_citations: int = len(claims)
            valid_citations: int = len(valid_claims)
            rejected_hallucinated: int = 0
            rejected_cross_tenant: int = 0

        return valid_claims, MockRejectionMetrics()
