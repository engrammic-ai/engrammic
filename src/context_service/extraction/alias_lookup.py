"""Stage 4a helper: commitment-cache-backed alias resolution.

Used by the entity-resolution cascade's deterministic pass (O-28 4a). Returns
``None`` on miss; caller then escalates to 4b (embedding similarity).
"""

from __future__ import annotations

import unicodedata
from typing import Any, Protocol


class _CacheReader(Protocol):
    async def get(self, silo_id: str, normalized_form: str) -> dict[str, Any] | None: ...


def _normalize(form: str) -> str:
    return unicodedata.normalize("NFKC", form).casefold()


async def resolve_alias(
    *, cache: _CacheReader, silo_id: str, surface_form: str
) -> dict[str, Any] | None:
    """Look up a surface form in the commitment cache.

    ``surface_form`` is normalized (NFKC + casefold) before lookup to match the
    keys the compiler wrote.
    """
    return await cache.get(silo_id, _normalize(surface_form))
