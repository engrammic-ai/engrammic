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


class TestSiloApiCleanup:
    """Silo API reflects 1:1 org-to-silo model."""

    def test_silo_create_not_exported(self) -> None:
        """silo_create is removed from public API."""
        from context_service.mcp.tools import __all__

        assert "register_silo_create" not in __all__

    def test_context_admin_exported(self) -> None:
        """context_admin is available in public API."""
        from context_service.mcp.tools import register_admin

        assert callable(register_admin)

    @pytest.mark.asyncio
    async def test_silo_list_auto_creates(self) -> None:
        """silo_list auto-creates the org silo if missing."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from context_service.auth.context import AuthContext
        from context_service.services.silo import SiloService

        mock_store = MagicMock()
        mock_store.execute_query = AsyncMock(return_value=[])
        mock_store.execute_write = AsyncMock(return_value=[])

        svc = SiloService(memgraph=mock_store)
        auth = AuthContext(org_id="org-456", user_id="user-1", email=None, is_dev=True)

        with (
            patch(
                "context_service.mcp.tools.context_admin.get_mcp_auth_context",
                new=AsyncMock(return_value=auth),
            ),
            patch("context_service.mcp.tools.context_admin.get_silo_service", return_value=svc),
        ):
            from context_service.mcp.tools.context_admin import _silo_list_impl

            result = await _silo_list_impl()

        assert "silos" in result
        assert len(result["silos"]) == 1
        assert result["silos"][0]["org_id"] == "org-456"


class TestValidateSiloOwnershipAutoCreate:
    """validate_silo_ownership auto-creates silo if missing."""

    @pytest.mark.asyncio
    async def test_auto_creates_when_missing(self) -> None:
        """Silo is auto-created when validation finds it missing."""
        from unittest.mock import AsyncMock, MagicMock

        from context_service.services.models import derive_silo_id
        from context_service.services.silo import SiloService, validate_silo_ownership

        org_id = "org-auto-create"
        silo_id = str(derive_silo_id(org_id))

        mock_store = MagicMock()
        mock_store.execute_query = AsyncMock(return_value=[])
        mock_store.execute_write = AsyncMock(return_value=[])

        svc = SiloService(memgraph=mock_store)
        result = await validate_silo_ownership(svc, silo_id, org_id)

        assert result is None  # No error = success
        mock_store.execute_write.assert_called_once()  # Silo was created
