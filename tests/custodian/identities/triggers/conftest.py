"""Local conftest: override the autouse reset_settings_cache fixture.

The root conftest fixture fails to import context_service.config.settings
in this test module because no heavy service-layer bootstrap is needed here.
This override is a no-op and prevents the ImportError.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def reset_settings_cache() -> Generator[None, None, None]:
    yield
