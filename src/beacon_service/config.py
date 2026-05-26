"""Configuration for beacon service."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BeaconConfig:
    """Beacon service configuration from environment."""

    database_url: str
    log_level: str = "INFO"
    version_latest: str = "0.1.0"
    version_minimum: str = "0.1.0"
    version_deprecated: str = "0.1.0"

    @classmethod
    def from_env(cls) -> BeaconConfig:
        """Load configuration from environment variables."""
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable is required")

        return cls(
            database_url=database_url,
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            version_latest=os.environ.get("VERSION_LATEST", "0.1.0"),
            version_minimum=os.environ.get("VERSION_MINIMUM", "0.1.0"),
            version_deprecated=os.environ.get("VERSION_DEPRECATED", "0.1.0"),
        )
