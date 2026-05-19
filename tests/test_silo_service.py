"""Unit tests for SiloService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from context_service.services.models import ScopeContext, derive_silo_id
from context_service.services.silo import SiloService, _parse_datetime, validate_silo_ownership


@pytest.fixture
def mock_store() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_cache() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def silo_service(mock_store: AsyncMock) -> SiloService:
    return SiloService(memgraph=mock_store)


@pytest.fixture
def silo_service_with_cache(mock_store: AsyncMock, mock_cache: AsyncMock) -> SiloService:
    return SiloService(memgraph=mock_store, ownership_cache=mock_cache)


class TestDeriveSiloId:
    def test_deterministic(self) -> None:
        org_id = "org-123"
        id1 = derive_silo_id(org_id)
        id2 = derive_silo_id(org_id)
        assert id1 == id2

    def test_different_orgs_different_ids(self) -> None:
        id1 = derive_silo_id("org-a")
        id2 = derive_silo_id("org-b")
        assert id1 != id2


class TestGetOrCreate:
    @pytest.mark.asyncio
    async def test_creates_new_silo(self, silo_service: SiloService, mock_store: AsyncMock) -> None:
        mock_store.execute_query.return_value = []  # get_by_id returns nothing
        mock_store.execute_write.return_value = None

        silo = await silo_service.get_or_create(
            name="test-silo",
            org_id="org-123",
            description="Test silo",
        )

        assert silo.name == "test-silo"
        assert silo.org_id == "org-123"
        assert silo.id == derive_silo_id("org-123")
        mock_store.execute_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_existing_silo(
        self, silo_service: SiloService, mock_store: AsyncMock
    ) -> None:
        existing_id = derive_silo_id("org-123")
        mock_store.execute_query.return_value = [
            {
                "id": str(existing_id),
                "name": "existing-silo",
                "org_id": "org-123",
                "description": "Existing",
                "dissolvability": 0.5,
            }
        ]

        silo = await silo_service.get_or_create(name="test-silo", org_id="org-123")

        assert silo.name == "existing-silo"
        mock_store.execute_write.assert_not_called()


class TestGetById:
    @pytest.mark.asyncio
    async def test_found(self, silo_service: SiloService, mock_store: AsyncMock) -> None:
        silo_id = uuid.uuid4()
        mock_store.execute_query.return_value = [
            {
                "id": str(silo_id),
                "name": "my-silo",
                "org_id": "org-1",
                "description": "Desc",
                "dissolvability": 0.7,
            }
        ]

        scope = ScopeContext(org_id="org-1", silo_id=silo_id)
        silo = await silo_service.get_by_id(scope)

        assert silo is not None
        assert silo.name == "my-silo"
        assert silo.dissolvability == 0.7

    @pytest.mark.asyncio
    async def test_not_found(self, silo_service: SiloService, mock_store: AsyncMock) -> None:
        mock_store.execute_query.return_value = []

        scope = ScopeContext(org_id="org-1", silo_id=uuid.uuid4())
        silo = await silo_service.get_by_id(scope)

        assert silo is None


class TestList:
    @pytest.mark.asyncio
    async def test_returns_all_silos(
        self, silo_service: SiloService, mock_store: AsyncMock
    ) -> None:
        mock_store.execute_query.return_value = [
            {"id": str(uuid.uuid4()), "name": "silo-a", "org_id": "org-1"},
            {"id": str(uuid.uuid4()), "name": "silo-b", "org_id": "org-1"},
        ]

        silos = await silo_service.list("org-1")

        assert len(silos) == 2
        assert silos[0].name == "silo-a"
        assert silos[1].name == "silo-b"

    @pytest.mark.asyncio
    async def test_empty_list(self, silo_service: SiloService, mock_store: AsyncMock) -> None:
        mock_store.execute_query.return_value = []

        silos = await silo_service.list("org-no-silos")

        assert silos == []


class TestParseDatetime:
    def test_none_returns_none(self) -> None:
        assert _parse_datetime(None) is None

    def test_datetime_passthrough(self) -> None:
        dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        assert _parse_datetime(dt) is dt

    def test_iso_string(self) -> None:
        dt = _parse_datetime("2024-01-15T12:00:00+00:00")
        assert isinstance(dt, datetime)
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15

    def test_epoch_microseconds(self) -> None:
        # epoch-microseconds for 2024-01-15T12:00:00 UTC
        epoch_us = 1705320000 * 1_000_000
        dt = _parse_datetime(epoch_us)
        assert isinstance(dt, datetime)
        assert dt.year == 2024

    def test_neo4j_iso_format(self) -> None:
        class FakeNeo4jDt:
            def iso_format(self) -> str:
                return "2024-01-15T12:00:00+00:00"

        dt = _parse_datetime(FakeNeo4jDt())
        assert isinstance(dt, datetime)
        assert dt.year == 2024


class TestSiloCreatedAtHydration:
    @pytest.mark.asyncio
    async def test_get_by_id_hydrates_created_at(
        self, silo_service: SiloService, mock_store: AsyncMock
    ) -> None:
        silo_id = uuid.uuid4()
        mock_store.execute_query.return_value = [
            {
                "id": str(silo_id),
                "name": "my-silo",
                "org_id": "org-1",
                "description": "Desc",
                "dissolvability": 0.5,
                "created_at": "2024-01-15T12:00:00+00:00",
            }
        ]

        scope = ScopeContext(org_id="org-1", silo_id=silo_id)
        silo = await silo_service.get_by_id(scope)

        assert silo is not None
        assert silo.created_at is not None
        assert isinstance(silo.created_at, datetime)
        assert silo.created_at.year == 2024

    @pytest.mark.asyncio
    async def test_get_by_id_created_at_none_when_missing(
        self, silo_service: SiloService, mock_store: AsyncMock
    ) -> None:
        silo_id = uuid.uuid4()
        mock_store.execute_query.return_value = [
            {
                "id": str(silo_id),
                "name": "my-silo",
                "org_id": "org-1",
            }
        ]

        scope = ScopeContext(org_id="org-1", silo_id=silo_id)
        silo = await silo_service.get_by_id(scope)

        assert silo is not None
        assert silo.created_at is None

    @pytest.mark.asyncio
    async def test_list_hydrates_created_at(
        self, silo_service: SiloService, mock_store: AsyncMock
    ) -> None:
        mock_store.execute_query.return_value = [
            {
                "id": str(uuid.uuid4()),
                "name": "silo-a",
                "org_id": "org-1",
                "created_at": "2024-03-10T08:00:00+00:00",
            },
            {
                "id": str(uuid.uuid4()),
                "name": "silo-b",
                "org_id": "org-1",
                "created_at": None,
            },
        ]

        silos = await silo_service.list("org-1")

        assert len(silos) == 2
        assert silos[0].created_at is not None
        assert isinstance(silos[0].created_at, datetime)
        assert silos[0].created_at.month == 3
        assert silos[1].created_at is None

    @pytest.mark.asyncio
    async def test_create_query_includes_created_at(
        self, silo_service: SiloService, mock_store: AsyncMock
    ) -> None:
        """Verify the CREATE Cypher query includes created_at: datetime()."""
        mock_store.execute_query.return_value = []  # get_by_id finds nothing
        mock_store.execute_write.return_value = None

        await silo_service.get_or_create(name="new-silo", org_id="org-new")

        call_args = mock_store.execute_write.call_args
        query: str = call_args[0][0]
        assert "created_at" in query
        assert "datetime()" in query


class TestValidateSiloOwnership:
    @pytest.mark.asyncio
    async def test_invalid_uuid(self, silo_service: SiloService) -> None:
        result = await validate_silo_ownership(silo_service, "not-a-uuid", "org-1")

        assert result is not None
        assert result["error"] == "invalid_silo_id"

    @pytest.mark.asyncio
    async def test_silo_id_mismatch(self, silo_service: SiloService) -> None:
        wrong_id = str(uuid.uuid4())  # Random UUID, not derived from org
        result = await validate_silo_ownership(silo_service, wrong_id, "org-1")

        assert result is not None
        assert result["error"] == "silo_not_found"

    @pytest.mark.asyncio
    async def test_valid_ownership(self, silo_service: SiloService, mock_store: AsyncMock) -> None:
        org_id = "org-valid"
        expected_id = derive_silo_id(org_id)
        mock_store.execute_query.return_value = [
            {
                "id": str(expected_id),
                "name": "valid-silo",
                "org_id": org_id,
            }
        ]

        result = await validate_silo_ownership(silo_service, str(expected_id), org_id)

        assert result is None  # None means success

    @pytest.mark.asyncio
    async def test_cache_hit(
        self, silo_service_with_cache: SiloService, mock_store: AsyncMock, mock_cache: AsyncMock
    ) -> None:
        org_id = "org-cached"
        expected_id = derive_silo_id(org_id)
        mock_cache.get.return_value = True

        result = await validate_silo_ownership(silo_service_with_cache, str(expected_id), org_id)

        assert result is None
        mock_store.execute_query.assert_not_called()  # Skipped due to cache

    @pytest.mark.asyncio
    async def test_cache_miss_then_set(
        self, silo_service_with_cache: SiloService, mock_store: AsyncMock, mock_cache: AsyncMock
    ) -> None:
        org_id = "org-not-cached"
        expected_id = derive_silo_id(org_id)
        mock_cache.get.return_value = False
        mock_store.execute_query.return_value = [
            {"id": str(expected_id), "name": "silo", "org_id": org_id}
        ]

        result = await validate_silo_ownership(silo_service_with_cache, str(expected_id), org_id)

        assert result is None
        mock_cache.set.assert_called_once()
