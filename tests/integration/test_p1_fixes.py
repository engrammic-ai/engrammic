"""Integration tests for P1 fixes."""

from __future__ import annotations

import asyncio
import resource as res
import uuid

import pytest

from context_service.extraction.filter import circuit_breaker
from context_service.services.models import derive_silo_id
from context_service.services.silo import SiloService, validate_silo_ownership
from context_service.stores import MemgraphClient

from .conftest import docker_available

# ============================================================================
# F-011, F-013: Silo Validation
# ============================================================================


@docker_available
@pytest.mark.integration
class TestSiloValidation:
    """Tests for validate_silo_ownership()."""

    async def test_valid_silo_exists_returns_none(
        self,
        silo_service: SiloService,
        unique_org_id: str,
        unique_silo_id: uuid.UUID,
        cleanup_silo: None,
    ) -> None:
        """Valid silo in Memgraph returns None (success)."""
        await silo_service.get_or_create(
            name="Test Silo",
            org_id=unique_org_id,
        )

        result = await validate_silo_ownership(
            silo_service,
            str(unique_silo_id),
            unique_org_id,
        )

        assert result is None

    async def test_invalid_uuid_format_returns_error(
        self,
        silo_service: SiloService,
        unique_org_id: str,
    ) -> None:
        """Invalid UUID format returns error dict."""
        result = await validate_silo_ownership(
            silo_service,
            "not-a-valid-uuid",
            unique_org_id,
        )

        assert result is not None
        assert result["error"] == "invalid_silo_id"
        assert "UUID" in result["message"]

    async def test_valid_uuid_wrong_org_returns_error(
        self,
        silo_service: SiloService,
        unique_org_id: str,
    ) -> None:
        """Valid UUID but derived from different org returns error."""
        wrong_org_silo = derive_silo_id("different-org-id")

        result = await validate_silo_ownership(
            silo_service,
            str(wrong_org_silo),
            unique_org_id,
        )

        assert result is not None
        assert result["error"] == "silo_not_found"

    async def test_valid_uuid_correct_org_not_in_db_returns_error(
        self,
        silo_service: SiloService,
        unique_org_id: str,
        unique_silo_id: uuid.UUID,
    ) -> None:
        """Valid UUID, correct org, but silo not created in DB."""
        result = await validate_silo_ownership(
            silo_service,
            str(unique_silo_id),
            unique_org_id,
        )

        assert result is not None
        assert result["error"] == "silo_not_found"


# ============================================================================
# F-037, F-038: CircuitBreaker Singleton
# ============================================================================


@pytest.mark.integration
class TestCircuitBreakerSingleton:
    """Tests for circuit breaker registry and behavior."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear CB registry before each test."""
        circuit_breaker._registry.clear()

    async def test_same_key_returns_same_instance(self) -> None:
        """Same (silo_id, service_name) returns identical CB instance."""
        cb1 = await circuit_breaker.get_or_create(
            "silo-1",
            "service-a",
            failure_threshold=3,
            window_s=60,
            cooldown_s=30,
        )
        cb2 = await circuit_breaker.get_or_create(
            "silo-1",
            "service-a",
            failure_threshold=3,
            window_s=60,
            cooldown_s=30,
        )

        assert cb1 is cb2

    async def test_different_silo_returns_different_instance(self) -> None:
        """Different silo_id returns separate CB instance."""
        cb1 = await circuit_breaker.get_or_create(
            "silo-1",
            "service-a",
            failure_threshold=3,
            window_s=60,
            cooldown_s=30,
        )
        cb2 = await circuit_breaker.get_or_create(
            "silo-2",
            "service-a",
            failure_threshold=3,
            window_s=60,
            cooldown_s=30,
        )

        assert cb1 is not cb2

    async def test_cb_opens_after_threshold_failures(self) -> None:
        """CB opens after failure_threshold failures within window."""
        cb = await circuit_breaker.get_or_create(
            "silo-test",
            "service-test",
            failure_threshold=3,
            window_s=60,
            cooldown_s=30,
        )

        assert not await cb.is_open()

        await cb.record_failure()
        await cb.record_failure()
        assert not await cb.is_open()

        await cb.record_failure()
        assert await cb.is_open()

    async def test_cb_resets_after_cooldown(self) -> None:
        """CB resets to closed after cooldown elapses."""
        fake_time = [0.0]

        def now_fn() -> float:
            return fake_time[0]

        cb = await circuit_breaker.get_or_create(
            "silo-cooldown",
            "service-cooldown",
            failure_threshold=2,
            window_s=60,
            cooldown_s=10,
            now_fn=now_fn,
        )

        await cb.record_failure()
        await cb.record_failure()
        assert await cb.is_open()

        fake_time[0] = 15.0
        assert not await cb.is_open()

    async def test_concurrent_calls_no_race(self) -> None:
        """Concurrent get_or_create calls return same instance."""

        async def get_cb() -> circuit_breaker.CircuitBreaker:
            return await circuit_breaker.get_or_create(
                "silo-concurrent",
                "service-concurrent",
                failure_threshold=3,
                window_s=60,
                cooldown_s=30,
            )

        cbs = await asyncio.gather(*[get_cb() for _ in range(10)])
        assert all(cb is cbs[0] for cb in cbs)


# ============================================================================
# F-039: Store Atomicity
# ============================================================================


@docker_available
@pytest.mark.integration
class TestStoreAtomicity:
    """Tests for ContextService.store() atomicity."""

    async def test_qdrant_failure_propagates_exception(
        self,
        memgraph_client: MemgraphClient,
        scope_context: object,
        cleanup_silo: None,
    ) -> None:
        """Qdrant failure raises exception (not silently swallowed)."""
        from unittest.mock import AsyncMock

        from context_service.services.context import ContextService

        mock_embedding = AsyncMock()
        mock_embedding.embed_single = AsyncMock(return_value=[0.1] * 1024)

        mock_qdrant = AsyncMock()
        mock_qdrant.upsert = AsyncMock(side_effect=Exception("Connection refused"))

        service = ContextService(
            memgraph=memgraph_client,
            qdrant=mock_qdrant,
            embedding=mock_embedding,
        )

        with pytest.raises(Exception, match="Connection refused"):
            await service.store(
                scope=scope_context,
                content="Content that should fail on Qdrant",
                node_type="Document",
            )


# ============================================================================
# F-022: Resource Teardown
# ============================================================================


@docker_available
@pytest.mark.integration
class TestResourceTeardown:
    """Tests for pipelines/resources.py _close_async()."""

    async def test_teardown_from_async_context(self) -> None:
        """Teardown works when called from async context (running loop)."""
        from context_service.config.settings import get_settings
        from context_service.pipelines.resources import MemgraphResource

        settings = get_settings()
        resource = MemgraphResource(
            uri=settings.memgraph_uri,
            user=settings.memgraph_user,
            password=settings.memgraph_password,
        )

        driver = await resource.driver()
        assert driver is not None

        resource.teardown_after_execution(None)  # type: ignore[arg-type]

        assert resource._driver is None

    def test_teardown_from_sync_context(self) -> None:
        """Teardown works when called from sync context (no running loop)."""
        import asyncio

        from context_service.config.settings import get_settings
        from context_service.pipelines.resources import MemgraphResource

        settings = get_settings()
        resource = MemgraphResource(
            uri=settings.memgraph_uri,
            user=settings.memgraph_user,
            password=settings.memgraph_password,
        )

        driver = asyncio.run(resource.driver())
        assert driver is not None

        resource.teardown_after_execution(None)  # type: ignore[arg-type]
        assert resource._driver is None

    async def test_no_fd_leak_across_cycles(self) -> None:
        """Multiple create/teardown cycles don't leak file descriptors."""
        from context_service.config.settings import get_settings
        from context_service.pipelines.resources import MemgraphResource

        settings = get_settings()
        initial_fds = res.getrlimit(res.RLIMIT_NOFILE)[0]

        for _ in range(5):
            mr = MemgraphResource(
                uri=settings.memgraph_uri,
                user=settings.memgraph_user,
                password=settings.memgraph_password,
            )
            await mr.driver()
            mr.teardown_after_execution(None)  # type: ignore[arg-type]

        final_fds = res.getrlimit(res.RLIMIT_NOFILE)[0]
        assert final_fds == initial_fds
