"""Tests for multi-channel retrieval configs."""

from context_service.config.settings import (
    BM25ChannelConfig,
    CrossEncoderConfig,
    GraphChannelConfig,
    Settings,
    TemporalChannelConfig,
)


class TestChannelConfigs:
    def test_bm25_defaults(self) -> None:
        cfg = BM25ChannelConfig()
        assert cfg.enabled is True
        assert cfg.top_k == 100

    def test_temporal_defaults(self) -> None:
        cfg = TemporalChannelConfig()
        assert cfg.enabled is True
        assert cfg.memory_half_life_days == 7.0
        # Only Memory has decay; others return None
        assert cfg.half_life_for_layer("memory") == 7.0
        assert cfg.half_life_for_layer("knowledge") is None
        assert cfg.half_life_for_layer("wisdom") is None

    def test_graph_defaults(self) -> None:
        cfg = GraphChannelConfig()
        assert cfg.enabled is True
        assert cfg.damping == 0.85
        assert cfg.max_iterations == 50
        assert "SYNTHESIZED_FROM" in cfg.edge_weights

    def test_cross_encoder_defaults(self) -> None:
        cfg = CrossEncoderConfig()
        assert cfg.enabled is True
        assert "ms-marco" in cfg.model
        assert cfg.top_k == 50

    def test_attached_to_settings(self) -> None:
        assert "bm25_channel" in Settings.model_fields
        assert "temporal_channel" in Settings.model_fields
        assert "graph_channel" in Settings.model_fields
        assert "cross_encoder" in Settings.model_fields
