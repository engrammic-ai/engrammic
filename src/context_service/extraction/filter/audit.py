from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Protocol

from opentelemetry import metrics

from context_service.extraction.filter.models import RuleFired  # noqa: TC001

log = logging.getLogger(__name__)

_meter = metrics.get_meter("context_service.extraction.filter")

dropped_total = _meter.create_counter(
    name="context_service.extraction.filter.dropped_total",
    description="Claims dropped by the extraction filter",
)
keep_total = _meter.create_counter(
    name="context_service.extraction.filter.keep_total",
    description="Claims kept by the extraction filter",
)
elapsed_ms = _meter.create_histogram(
    name="context_service.extraction.filter.elapsed_ms",
    description="Per-rule evaluation latency",
    unit="ms",
)
llm_score_hist = _meter.create_histogram(
    name="context_service.extraction.filter.llm_score",
    description="LLM classifier score distribution",
)
external_failure_total = _meter.create_counter(
    name="context_service.extraction.filter.external_failure_total",
    description="Fail-open events per rule",
)


@dataclass(frozen=True)
class FilterAuditRow:
    silo_id: str
    filter_version: str
    silo_override_hash: str | None
    rule_fired: RuleFired
    reason: str
    subject: str
    predicate: str
    object: str
    raw_confidence: float | None
    llm_score: float | None
    source_doc_id: str | None
    passage_id: str | None
    extractor_model: str | None


class _WriterLike(Protocol):
    def insert_many(self, rows: list[dict[str, object]]) -> None: ...


class FilterAuditor:
    """Buffers drop rows for the current job; flush() inserts them in one batch."""

    def __init__(self, writer: _WriterLike) -> None:
        self._writer = writer
        self._buf: list[FilterAuditRow] = []

    def record_drop(self, row: FilterAuditRow) -> None:
        self._buf.append(row)
        dropped_total.add(
            1, {"silo_id": row.silo_id, "rule_fired": row.rule_fired.value, "reason": row.reason}
        )

    def record_keep(self, silo_id: str) -> None:
        keep_total.add(1, {"silo_id": silo_id})

    def record_elapsed(self, rule: RuleFired, ms: float) -> None:
        elapsed_ms.record(ms, {"rule_fired": rule.value})

    def record_llm_score(self, silo_id: str, score: float) -> None:
        llm_score_hist.record(score, {"silo_id": silo_id})

    def record_external_failure(self, rule: RuleFired) -> None:
        external_failure_total.add(1, {"rule_fired": rule.value})

    def flush(self) -> None:
        if not self._buf:
            return
        rows = []
        for r in self._buf:
            d = asdict(r)
            d["rule_fired"] = r.rule_fired.value  # Enum → str for SQL bind
            rows.append(d)
        self._writer.insert_many(rows)
        self._buf.clear()
