from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import context_service.extraction.filter.circuit_breaker as cb_module
from context_service.extraction.filter.circuit_breaker import CircuitBreaker
from context_service.extraction.filter.models import FilterDecision, FilterRuleSet, RuleFired
from context_service.llm.sanitize import escape_for_prompt

if TYPE_CHECKING:
    from context_service.extraction.models import ClaimTriple
    from context_service.llm.base import LLMProvider

log = logging.getLogger(__name__)

PROMPT_TEMPLATE = """Is the following fact common/general knowledge that would appear in an introductory resource, or is it specialized/domain-specific?

Fact: {subject} {predicate} {object}

Answer with a number 0.0 (very specialized) to 1.0 (common knowledge) and nothing else."""


class LLMClassifierRule:
    """Rule 4 — provider-agnostic LLM confidence classifier with CB.

    Fail-open: unparseable / timeout / CB-open -> EXTERNAL_FAILURE (non-decisive).

    Pass silo_id to bind the CB to the registry so state persists across requests.
    When silo_id is omitted (tests / one-shot usage) a fresh CB is used instead.
    """

    def __init__(
        self,
        rs: FilterRuleSet,
        llm: LLMProvider,
        *,
        silo_id: str | None = None,
    ) -> None:
        self._rs = rs
        self._llm = llm
        self._silo_id = silo_id
        self._local_cb: CircuitBreaker | None = (
            None
            if silo_id is not None
            else CircuitBreaker(
                failure_threshold=rs.llm_cb_failure_threshold,
                window_s=rs.llm_cb_window_s,
                cooldown_s=rs.llm_cb_cooldown_s,
            )
        )

    async def _get_cb(self) -> CircuitBreaker:
        if self._local_cb is not None:
            return self._local_cb
        assert self._silo_id is not None
        return await cb_module.get_or_create(
            self._silo_id,
            "llm_classifier",
            failure_threshold=self._rs.llm_cb_failure_threshold,
            window_s=self._rs.llm_cb_window_s,
            cooldown_s=self._rs.llm_cb_cooldown_s,
        )

    async def evaluate(self, claim: ClaimTriple) -> FilterDecision | None:
        cb = await self._get_cb()
        if await cb.is_open():
            return FilterDecision(
                action="keep",
                rule_fired=RuleFired.EXTERNAL_FAILURE,
                reason="llm_cb_open",
            )

        prompt = PROMPT_TEMPLATE.format(
            subject=escape_for_prompt(claim.subject),
            predicate=escape_for_prompt(claim.predicate),
            object=escape_for_prompt(claim.object),
        )
        try:
            text, _usage = await asyncio.wait_for(
                self._llm.complete(
                    [{"role": "user", "content": prompt}],
                    temperature=0.0,
                ),
                timeout=self._rs.llm_timeout_s,
            )
        except Exception as e:  # TimeoutError is a subclass; Exception covers both
            await cb.record_failure()
            log.info("llm classifier failed: %s", e)
            return FilterDecision(
                action="keep",
                rule_fired=RuleFired.EXTERNAL_FAILURE,
                reason=f"llm_error:{type(e).__name__}",
            )

        try:
            score = float(text.strip().split()[0])
        except (ValueError, IndexError):
            # Unparseable — fail-open, but don't penalise CB (model response drift, not infra)
            return FilterDecision(
                action="keep",
                rule_fired=RuleFired.EXTERNAL_FAILURE,
                reason=f"llm_unparseable:{text[:40]!r}",
            )

        await cb.record_success()
        score = max(0.0, min(1.0, score))
        if score >= self._rs.llm_threshold:
            return FilterDecision.drop(
                rule=RuleFired.LLM_CONFIDENCE,
                reason=f"score>={self._rs.llm_threshold}",
                llm_score=score,
            )
        return FilterDecision.keep(
            rule=RuleFired.LLM_CONFIDENCE,
            reason=f"score<{self._rs.llm_threshold}",
            llm_score=score,
        )
