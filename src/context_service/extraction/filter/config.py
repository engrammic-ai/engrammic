from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from context_service.extraction.filter.models import FilterRuleSet

# Silo override keys that would *add to* base rules — disallowed.
TIGHTENING_KEYS = {
    "extra_hard_drop_triples",
    "extra_suspect_predicates",
    "extra_public_entity_allowlist",
    "llm_threshold",
}


def _lower_triple(t: list[str]) -> tuple[str, str, str]:
    if len(t) != 3:
        raise ValueError(f"hard_drop_triples entries must be 3-tuples: {t!r}")
    p, s, o = t
    return (p.strip(), s.strip().lower(), o.strip().lower())


def _silo_hash(override: dict[str, Any]) -> str:
    canonical = json.dumps(override, sort_keys=True).encode()
    return hashlib.sha256(canonical).hexdigest()[:16]


def merge_silo_override(
    base: dict[str, Any], override: dict[str, Any] | None
) -> tuple[dict[str, Any], str | None]:
    if not override:
        return base, None
    for key in override:
        if key in TIGHTENING_KEYS:
            raise ValueError(
                f"Silo override cannot tighten base config (key={key!r}); "
                "additive-only per design §8.2"
            )

    merged = dict(base)
    # never_filter_predicates: additive
    extra_nfp = override.get("extra_never_filter_predicates", [])
    merged["never_filter_predicates"] = list(
        set(base.get("never_filter_predicates", [])) | set(extra_nfp)
    )
    # public_entity_allowlist: removals only
    removals = set(override.get("extra_public_entity_allowlist_removals", []))
    merged["public_entity_allowlist"] = [
        e for e in base.get("public_entity_allowlist", []) if e not in removals
    ]
    # retention override
    if "retention_days" in override:
        merged["retention_days"] = int(override["retention_days"])

    return merged, _silo_hash(override)


def load_filter_rule_set(
    yaml_path: Path | str, silo_override: dict[str, Any] | None
) -> FilterRuleSet:
    path = Path(yaml_path)
    raw = yaml.safe_load(path.read_text())
    merged, override_hash = merge_silo_override(raw, silo_override)

    wd = merged["wikidata"]
    wd_cb = wd["circuit_breaker"]
    llm = merged["llm_classifier"]
    llm_cb = llm["circuit_breaker"]

    return FilterRuleSet(
        version=merged["version"],
        enabled=bool(merged.get("enabled", False)),
        hard_drop_triples=frozenset(_lower_triple(t) for t in merged.get("hard_drop_triples", [])),
        suspect_predicates=frozenset(merged.get("suspect_predicates", [])),
        public_entity_allowlist=frozenset(
            e.lower() for e in merged.get("public_entity_allowlist", [])
        ),
        never_filter_predicates=frozenset(merged.get("never_filter_predicates", [])),
        wikidata_endpoint=wd["endpoint"],
        wikidata_timeout_s=float(wd["timeout_seconds"]),
        wikidata_cache_ttl_days=int(wd["cache_ttl_days"]),
        wikidata_cb_failure_threshold=int(wd_cb["failure_threshold"]),
        wikidata_cb_window_s=float(wd_cb["window_seconds"]),
        wikidata_cb_cooldown_s=float(wd_cb["cooldown_seconds"]),
        llm_provider=llm["provider"],
        llm_threshold=float(llm["threshold"]),
        llm_timeout_s=float(llm["timeout_seconds"]),
        llm_cb_failure_threshold=int(llm_cb["failure_threshold"]),
        llm_cb_window_s=float(llm_cb["window_seconds"]),
        llm_cb_cooldown_s=float(llm_cb["cooldown_seconds"]),
        retention_days=int(merged.get("retention_days", 90)),
        silo_override_hash=override_hash,
    )
