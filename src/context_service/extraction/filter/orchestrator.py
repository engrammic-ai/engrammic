from __future__ import annotations

import time
from typing import TYPE_CHECKING, Protocol

from context_service.config.logging import get_logger
from context_service.extraction.filter.audit import FilterAuditor, FilterAuditRow
from context_service.extraction.filter.models import FilterDecision, FilterRuleSet, RuleFired
from context_service.extraction.filter.rules import rule_1_hard_drop, rule_3_heuristic

if TYPE_CHECKING:
    from context_service.extraction.models import ClaimTriple

logger = get_logger(__name__)


class _AsyncRule(Protocol):
    async def evaluate(self, claim: ClaimTriple) -> FilterDecision | None: ...


class FilterOrchestrator:
    """Layered evaluator with early exit + audit side effects.

    A rule returning EXTERNAL_FAILURE is non-decisive — we continue to the next rule.
    A rule returning a concrete keep/drop (other than EXTERNAL_FAILURE) short-circuits.
    """

    def __init__(
        self,
        rule_set: FilterRuleSet,
        wikidata_rule: _AsyncRule,
        llm_rule: _AsyncRule,
        auditor: FilterAuditor,
    ) -> None:
        self._rs = rule_set
        self._wd = wikidata_rule
        self._llm = llm_rule
        self._auditor = auditor

    async def evaluate(
        self,
        claims: list[ClaimTriple],
        silo_id: str,
        *,
        extractor_model: str | None = None,
    ) -> list[FilterDecision]:
        if not self._rs.enabled:
            logger.debug(
                f"extraction_filter: disabled, keeping all {len(claims)} claims (silo={silo_id})"
            )
            return [
                FilterDecision.keep(rule=RuleFired.KEPT, reason="filter_disabled") for _ in claims
            ]

        results: list[FilterDecision] = []
        for claim in claims:
            decision = await self._evaluate_one(claim)
            self._record(silo_id, claim, decision, extractor_model)
            logger.debug(
                f"extraction_filter: claim ({claim.subject!s} {claim.predicate} {claim.object!s}) "
                f"-> {decision.action} via {decision.rule_fired.value} ({decision.reason}) "
                f"silo={silo_id}"
            )
            results.append(decision)

        kept = sum(1 for d in results if d.action == "keep")
        dropped = len(results) - kept
        logger.info(
            f"extraction_filter: silo={silo_id} kept={kept} dropped={dropped} "
            f"total={len(results)} model={extractor_model}"
        )

        try:
            self._auditor.flush()
        except Exception as e:
            logger.warning("extraction_filter_audit_flush_failed", error=str(e))
        return results

    async def _evaluate_one(self, claim: ClaimTriple) -> FilterDecision:
        # Rule 1 — hard-drop
        t0 = time.monotonic()
        d1 = rule_1_hard_drop(claim, self._rs)
        self._auditor.record_elapsed(RuleFired.HARD_DROP, (time.monotonic() - t0) * 1000)
        if d1 is not None:
            return d1

        # Rule 2 — wikidata
        t0 = time.monotonic()
        d2 = await self._wd.evaluate(claim)
        self._auditor.record_elapsed(RuleFired.WIKIDATA, (time.monotonic() - t0) * 1000)
        if d2 is not None and d2.rule_fired is not RuleFired.EXTERNAL_FAILURE:
            return d2
        if d2 is not None and d2.rule_fired is RuleFired.EXTERNAL_FAILURE:
            self._auditor.record_external_failure(RuleFired.WIKIDATA)

        # Rule 3 — heuristic
        t0 = time.monotonic()
        d3 = rule_3_heuristic(claim, self._rs)
        self._auditor.record_elapsed(RuleFired.HEURISTIC, (time.monotonic() - t0) * 1000)
        if d3 is not None:
            return d3

        # Rule 4 — LLM
        t0 = time.monotonic()
        d4 = await self._llm.evaluate(claim)
        self._auditor.record_elapsed(RuleFired.LLM_CONFIDENCE, (time.monotonic() - t0) * 1000)
        if d4 is not None and d4.rule_fired is RuleFired.EXTERNAL_FAILURE:
            self._auditor.record_external_failure(RuleFired.LLM_CONFIDENCE)
            return FilterDecision.keep(rule=RuleFired.KEPT, reason="all_rules_inconclusive")
        if d4 is not None:
            return d4

        return FilterDecision.keep(rule=RuleFired.KEPT, reason="no_rule_decisive")

    def _record(
        self,
        silo_id: str,
        claim: ClaimTriple,
        decision: FilterDecision,
        extractor_model: str | None,
    ) -> None:
        if decision.action == "keep":
            self._auditor.record_keep(silo_id)
            if decision.llm_score is not None:
                self._auditor.record_llm_score(silo_id, decision.llm_score)
            return
        if decision.llm_score is not None:
            self._auditor.record_llm_score(silo_id, decision.llm_score)
        self._auditor.record_drop(
            FilterAuditRow(
                silo_id=silo_id,
                filter_version=self._rs.version,
                silo_override_hash=self._rs.silo_override_hash,
                rule_fired=decision.rule_fired,
                reason=decision.reason,
                subject=str(claim.subject),
                predicate=claim.predicate,
                object=str(claim.object),
                raw_confidence=claim.confidence,
                llm_score=decision.llm_score,
                source_doc_id=claim.source_doc_id,
                passage_id=claim.source_passage_id,
                extractor_model=extractor_model,
            )
        )
