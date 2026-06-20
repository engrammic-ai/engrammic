import pytest
from pydantic import ValidationError


def test_batch_embed_threshold_default():
    from context_service.config.settings import Settings

    s = Settings()
    assert s.batch_embed_threshold == 10


def test_batch_embed_threshold_custom(monkeypatch):
    monkeypatch.setenv("BATCH_EMBED_THRESHOLD", "50")
    from context_service.config.settings import Settings

    s = Settings()
    assert s.batch_embed_threshold == 50


def test_batch_embed_threshold_min_bound():
    from context_service.config.settings import Settings

    s = Settings(batch_embed_threshold=1)
    assert s.batch_embed_threshold == 1


def test_batch_embed_threshold_max_bound():
    from context_service.config.settings import Settings

    s = Settings(batch_embed_threshold=1000)
    assert s.batch_embed_threshold == 1000


def test_batch_embed_threshold_below_min():
    from context_service.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings(batch_embed_threshold=0)


def test_batch_embed_threshold_above_max():
    from context_service.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings(batch_embed_threshold=1001)
