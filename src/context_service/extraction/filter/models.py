from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class RuleFired(StrEnum):
    HARD_DROP = "hard_drop"
    WIKIDATA = "wikidata"
    HEURISTIC = "heuristic"
    LLM_CONFIDENCE = "llm_confidence"
    EXTERNAL_FAILURE = "external_failure"
    KEPT = "kept"


class FilterDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: Literal["keep", "drop"]
    rule_fired: RuleFired
    reason: str
    llm_score: float | None = None
    elapsed_ms: float | None = None

    @classmethod
    def keep(cls, *, rule: RuleFired, reason: str, **kw: float | None) -> FilterDecision:
        return cls(action="keep", rule_fired=rule, reason=reason, **kw)

    @classmethod
    def drop(cls, *, rule: RuleFired, reason: str, **kw: float | None) -> FilterDecision:
        return cls(action="drop", rule_fired=rule, reason=reason, **kw)


class FilterRuleSet(BaseModel):
    """In-memory view of config/extraction_filter.yaml after silo override merge."""

    version: str
    enabled: bool
    hard_drop_triples: frozenset[
        tuple[str, str, str]
    ]  # (predicate, subject, object), all lowercase
    suspect_predicates: frozenset[str]
    public_entity_allowlist: frozenset[str]
    never_filter_predicates: frozenset[str]
    wikidata_endpoint: str
    wikidata_timeout_s: float
    wikidata_cache_ttl_days: int
    wikidata_cb_failure_threshold: int
    wikidata_cb_window_s: float
    wikidata_cb_cooldown_s: float
    llm_provider: str
    llm_threshold: float
    llm_timeout_s: float
    llm_cb_failure_threshold: int
    llm_cb_window_s: float
    llm_cb_cooldown_s: float
    retention_days: int
    silo_override_hash: str | None = None

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
