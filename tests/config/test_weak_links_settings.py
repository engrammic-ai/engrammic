from context_service.config.settings import get_settings


def test_weak_links_settings_defaults():
    settings = get_settings()
    wl = settings.weak_links
    assert wl.enabled is True
    assert wl.similarity_threshold == 0.75
    assert wl.max_links_per_node == 5
    assert wl.promotion_min_weight == 0.6
    assert wl.promotion_min_edge_heat == 0.3
    assert wl.pruning_max_age_days == 30
    assert wl.pruning_min_edge_heat == 0.1
