from context_service.config.settings import ResultCacheConfig, Settings


def test_settings_result_cache_defaults() -> None:
    s = Settings()
    rc = s.result_cache

    assert isinstance(rc, ResultCacheConfig)
    assert rc.enabled is True
    assert rc.memory_ttl == 300
    assert rc.knowledge_ttl == 3600
    assert rc.wisdom_ttl == 1800
    assert rc.maxsize == 10000
