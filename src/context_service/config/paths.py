"""Repo-root and config-path discovery.

Several modules under ``src/`` need to point at the repo's ``config/``
directory at import time. Counting ``.parent`` steps from ``__file__`` is
fragile: the count changes whenever a file moves, and silently breaks
under git worktrees or any non-canonical checkout. ``repo_root()`` finds
the root by walking upward until it sees ``pyproject.toml`` — independent
of file depth and of where the checkout lives on disk.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_MARKER_FILE = "pyproject.toml"

# Env var pointing at a host-mounted directory of override YAML files. When set,
# any config file present there (matched by filename) takes precedence over the
# copy baked into the image. Lets self-hosters edit config (e.g. models.yaml)
# without rebuilding or clobbering the shipped defaults. See the self-hosting docs.
_OVERRIDE_DIR_ENV = "ENGRAMMIC_CONFIG_DIR"


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Return the repository root (the directory containing pyproject.toml).

    Walks upward from this module's location. Cached after the first call.

    Raises:
        RuntimeError: If no ``pyproject.toml`` is found between this file
            and the filesystem root. Indicates a packaging or installation
            problem (e.g. the wheel was installed standalone without the
            source layout).
    """
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / _MARKER_FILE).is_file():
            return candidate
    raise RuntimeError(f"Could not find {_MARKER_FILE} above {start}; repo root is undiscoverable")


def config_dir() -> Path:
    """Path to the repo's top-level ``config/`` directory.

    Loaders should resolve specific files via ``config_dir() / rel_path``
    rather than hardcoding subpaths — keeping the loader unaware of which
    consumer's prompts/configs live where.
    """
    return repo_root() / "config"


def resolve_config_file(filename: str, default: Path) -> Path:
    """Resolve a config file, preferring a host-mounted override.

    If ``ENGRAMMIC_CONFIG_DIR`` is set and contains ``filename``, that path is
    returned. Otherwise ``default`` (the copy shipped in the image or repo) is
    used. Overrides are matched by bare filename, so a single override directory
    can shadow config files that otherwise live in different locations.

    Args:
        filename: Bare file name to look for in the override dir (e.g. "models.yaml").
        default: Path to fall back to when no override is present.

    Returns:
        The override path when present and readable, otherwise ``default``.
    """
    raw = os.environ.get(_OVERRIDE_DIR_ENV)
    if raw:
        candidate = Path(raw) / filename
        if candidate.is_file():
            return candidate
    return default
