"""Tests for v1.4 phase 0 fixes."""

import pytest


class TestHeatBackwardsCompat:
    """Heat asset handles missing event_type field."""

    def test_parse_event_type_missing(self) -> None:
        """Missing event_type defaults to 'read'."""
        from context_service.pipelines.assets.heat import parse_event_type

        fields: dict[bytes, bytes] = {b"node_id": b"abc-123"}
        assert parse_event_type(fields) == "read"

    def test_parse_event_type_present(self) -> None:
        """Present event_type is returned."""
        from context_service.pipelines.assets.heat import parse_event_type

        fields: dict[bytes, bytes] = {b"node_id": b"abc-123", b"event_type": b"write"}
        assert parse_event_type(fields) == "write"

    def test_parse_event_type_str_keys(self) -> None:
        """Handle string keys (some Redis clients decode)."""
        from context_service.pipelines.assets.heat import parse_event_type

        fields: dict[str, str] = {"node_id": "abc-123", "event_type": "write"}
        assert parse_event_type(fields) == "write"


class TestEnsureSilo:
    """ensure_silo auto-creates silo if missing."""

    @pytest.mark.asyncio
    async def test_ensure_silo_creates_if_missing(self) -> None:
        """Silo is auto-created when it doesn't exist."""
        from unittest.mock import AsyncMock, MagicMock

        from context_service.services.silo import SiloService, ensure_silo

        mock_store = MagicMock()
        mock_store.execute_query = AsyncMock(return_value=[])
        mock_store.execute_write = AsyncMock(return_value=[])

        svc = SiloService(memgraph=mock_store)
        silo = await ensure_silo(svc, org_id="org-123")

        assert silo is not None
        assert silo.org_id == "org-123"
        mock_store.execute_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_silo_returns_existing(self) -> None:
        """Existing silo is returned without create."""
        from unittest.mock import AsyncMock, MagicMock

        from context_service.services.models import derive_silo_id
        from context_service.services.silo import SiloService, ensure_silo

        expected_id = str(derive_silo_id("org-123"))
        mock_store = MagicMock()
        mock_store.execute_query = AsyncMock(
            return_value=[
                {
                    "id": expected_id,
                    "name": "default",
                    "org_id": "org-123",
                    "description": "",
                    "dissolvability": 0.5,
                }
            ]
        )

        svc = SiloService(memgraph=mock_store)
        silo = await ensure_silo(svc, org_id="org-123")

        assert silo is not None
        assert str(silo.id) == expected_id
        mock_store.execute_write.assert_not_called()
