"""JSON helpers backed by orjson for fast serialization on hot paths.

orjson.dumps returns bytes; dumps() wraps to str for drop-in stdlib compatibility.
JSONDecodeError is re-exported so callers can catch it without importing json directly.
orjson always uses compact separators, so the separators kwarg is a no-op here.
"""

from json import JSONDecodeError
from typing import Any

import orjson

__all__ = ["JSONDecodeError", "dumps", "loads"]


def dumps(obj: Any, *, sort_keys: bool = False, separators: Any = None, **_kwargs: Any) -> str:  # noqa: ARG001
    option = orjson.OPT_SORT_KEYS if sort_keys else None
    return orjson.dumps(obj, option=option).decode()


def loads(s: str | bytes, **_kwargs: Any) -> Any:
    return orjson.loads(s)
