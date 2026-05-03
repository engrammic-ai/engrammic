"""Tests for v1.4 phase 0 fixes."""



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
