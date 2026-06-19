"""SPO (Subject-Predicate-Object) triple extraction from claim text.

Extracts structured semantic triples from natural language claims to enable
corroboration matching in the SAGE pipeline.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from context_service.llm.base import robust_json_loads

if TYPE_CHECKING:
    from context_service.llm.base import LLMProvider

logger = structlog.get_logger(__name__)

_EXTRACTION_PROMPT = """\
Extract a semantic triple (subject, predicate, object) from this claim.

Rules:
- Subject: the main entity or concept the claim is about (noun phrase, lowercase)
- Predicate: the relationship or action (verb phrase, snake_case)
- Object: what the subject relates to (noun phrase, lowercase)
- Keep each part concise (1-4 words)
- Use snake_case for predicates (e.g., "improves", "should_own", "requires")
- Normalize similar concepts (e.g., "database" not "databases", "service" not "services")

Claim: "{claim}"

Respond with JSON only:
{{"subject": "...", "predicate": "...", "object": "..."}}
"""


@dataclass
class SPOTriple:
    """Extracted subject-predicate-object triple."""

    subject: str
    predicate: str
    object: str

    def is_valid(self) -> bool:
        """Check if all fields are non-empty."""
        return bool(self.subject and self.predicate and self.object)


async def extract_spo(
    llm: LLMProvider,
    claim: str,
    timeout: float = 5.0,
) -> SPOTriple | None:
    """Extract SPO triple from a claim using LLM.

    Args:
        llm: LLM provider instance.
        claim: The claim text to extract from.
        timeout: Request timeout in seconds.

    Returns:
        SPOTriple if extraction succeeds, None otherwise.
    """
    if not claim or len(claim) < 10:
        return None

    prompt = _EXTRACTION_PROMPT.format(claim=claim)
    messages = [{"role": "user", "content": prompt}]

    try:
        text, _usage = await asyncio.wait_for(
            llm.complete(
                messages,
                temperature=0.0,
                max_tokens=100,
            ),
            timeout=timeout,
        )

        if not text:
            logger.warning("spo_extraction_empty_response", claim_len=len(claim))
            return None

        parsed = robust_json_loads(text)
        if not isinstance(parsed, dict):
            logger.warning("spo_extraction_invalid_json", response=text[:100])
            return None

        triple = SPOTriple(
            subject=str(parsed.get("subject", "")).strip().lower(),
            predicate=str(parsed.get("predicate", "")).strip().lower().replace(" ", "_"),
            object=str(parsed.get("object", "")).strip().lower(),
        )

        if not triple.is_valid():
            logger.warning("spo_extraction_incomplete", triple=triple)
            return None

        logger.debug(
            "spo_extraction_ok",
            subject=triple.subject,
            predicate=triple.predicate,
            object=triple.object,
        )
        return triple

    except TimeoutError:
        logger.warning("spo_extraction_timeout", claim_len=len(claim))
        return None
    except Exception as exc:
        logger.warning("spo_extraction_failed", error=str(exc), claim_len=len(claim))
        return None
