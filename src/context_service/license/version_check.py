"""Version check against telemetry endpoint."""

from __future__ import annotations

from enum import Enum

import httpx
from packaging.version import Version

from context_service import __version__
from context_service.config.logging import get_logger
from context_service.config.settings import get_settings

logger = get_logger(__name__)


class VersionCheckResult(Enum):
    """Result of version check."""

    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    DEPRECATED = "deprecated"
    UNSUPPORTED = "unsupported"
    CHECK_FAILED = "check_failed"


def _get_versions_url() -> str:
    """Get versions endpoint URL from settings."""
    settings = get_settings()
    base_url = settings.telemetry.beacon_url.removesuffix("/beacon").removesuffix("/v1")
    return f"{base_url}/versions"


async def check_version() -> VersionCheckResult:
    """Check current version against telemetry endpoint.

    Returns:
        VersionCheckResult indicating version status.

    Raises:
        SystemExit: If version is below minimum supported.
    """
    versions_url = _get_versions_url()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(versions_url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("version_check_failed", error=str(e), url=versions_url)
        return VersionCheckResult.CHECK_FAILED

    current = Version(__version__.replace("-dev", ""))
    minimum = Version(data["minimum_supported"])
    deprecated = Version(data["deprecation_threshold"])
    latest = Version(data["latest"])

    if current < minimum:
        logger.error(
            "unsupported_version",
            current=str(current),
            minimum=str(minimum),
            message=f"Version {current} is no longer supported. Minimum required: {minimum}",
        )
        raise SystemExit(1)

    if current < deprecated:
        logger.warning(
            "deprecated_version",
            current=str(current),
            latest=str(latest),
            message=f"Running deprecated version {current}. Upgrade to {latest}: docker compose pull && docker compose up -d",
        )
        return VersionCheckResult.DEPRECATED

    if current < latest:
        logger.info(
            "newer_version_available",
            current=str(current),
            latest=str(latest),
        )
        return VersionCheckResult.UPDATE_AVAILABLE

    return VersionCheckResult.UP_TO_DATE
