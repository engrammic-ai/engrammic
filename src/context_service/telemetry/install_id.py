from __future__ import annotations

import os
import uuid
from pathlib import Path

import structlog


def _default_install_id_path() -> Path:
    """Return platform-appropriate path for install_id persistence."""
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        return Path(xdg_data) / "engrammic" / "install_id"
    return Path.home() / ".local" / "share" / "engrammic" / "install_id"


_DEFAULT_PATH = _default_install_id_path()
_EPHEMERAL_ID: str | None = None

logger = structlog.get_logger(__name__)


def get_or_create_install_id(path: Path = _DEFAULT_PATH) -> str:
    """Return persistent anonymous install ID, creating if needed.

    Falls back to an ephemeral in-memory ID if the path is not writable
    (e.g., rootless Docker, read-only filesystem).
    """
    global _EPHEMERAL_ID

    try:
        if path.exists():
            return path.read_text().strip()

        path.parent.mkdir(parents=True, exist_ok=True)
        install_id = str(uuid.uuid4())
        path.write_text(install_id)
        return install_id
    except OSError as e:
        if _EPHEMERAL_ID is None:
            _EPHEMERAL_ID = str(uuid.uuid4())
            logger.warning(
                "install_id_fallback_to_ephemeral",
                error=str(e),
                path=str(path),
            )
        return _EPHEMERAL_ID
