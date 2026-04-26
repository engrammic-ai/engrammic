"""member_fingerprint and Jaccard drift comparison helpers for child-finding reuse."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def _validate_str_list(values: Iterable[str], name: str) -> list[str]:
    if not isinstance(values, (list, set, frozenset, tuple)):
        raise TypeError(f"{name} must be a list/set of strings")
    result: list[str] = []
    for v in values:
        if not isinstance(v, str):
            raise TypeError(f"{name} must contain only strings, got {type(v).__name__}")
        result.append(v)
    return result


def member_fingerprint(member_node_ids: list[str]) -> str:
    """Stable hash of a cluster's member node_id set.

    Order-independent: sorts member_node_ids before hashing so any permutation
    yields the same fingerprint. Uses blake2b-128 for cheap equality checks.
    """
    ids = _validate_str_list(member_node_ids, "member_node_ids")
    canonical = ",".join(sorted(set(ids))).encode()
    return hashlib.blake2b(canonical, digest_size=16).hexdigest()


def jaccard_overlap(a: set[str] | list[str], b: set[str] | list[str]) -> float:
    """Jaccard similarity |A intersection B| / |A union B|.

    Returns 1.0 for identical sets, 0.0 for disjoint sets.
    Returns 1.0 if both inputs are empty (vacuous equality).
    """
    set_a = set(_validate_str_list(a, "a"))
    set_b = set(_validate_str_list(b, "b"))
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 1.0
    intersection = set_a & set_b
    return len(intersection) / len(union)


def fingerprint_drift_ok(
    prior_members: list[str],
    current_members: list[str],
    threshold: float = 0.8,
) -> bool:
    """True when Jaccard overlap >= threshold (default 0.8).

    Called by fetch_lower_findings to filter stale child findings.
    """
    return jaccard_overlap(prior_members, current_members) >= threshold
