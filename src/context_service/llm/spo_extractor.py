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
Extract (subject, predicate, object) from the claim. Convert passive to active voice.
Output ONLY valid JSON.

Examples:
- "Caching improves performance" -> {{"subject":"caching","predicate":"improves","object":"performance"}}
- "Bugs are caught by tests" -> {{"subject":"tests","predicate":"catch","object":"bugs"}}

Claim: {claim}
JSON:"""


@dataclass
class SPOTriple:
    """Extracted subject-predicate-object triple."""

    subject: str
    predicate: str
    object: str

    def is_valid(self) -> bool:
        """Check if all fields are non-empty."""
        return bool(self.subject and self.predicate and self.object)


async def _extract_spo_once(
    llm: LLMProvider,
    claim: str,
    timeout: float,
) -> SPOTriple | None:
    """Single extraction attempt."""
    prompt = _EXTRACTION_PROMPT.format(claim=claim)
    messages = [{"role": "user", "content": prompt}]

    text, _usage = await asyncio.wait_for(
        llm.complete(
            messages,
            temperature=0.0,
            max_tokens=300,  # Buffer for models that add preamble
        ),
        timeout=timeout,
    )

    if not text:
        raise ValueError("empty_response")

    # Strip markdown code blocks if present
    clean_text = text.strip()
    if clean_text.startswith("```"):
        lines = clean_text.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        clean_text = "\n".join(lines).strip()

    parsed = robust_json_loads(clean_text)
    if not isinstance(parsed, dict):
        raise ValueError(f"invalid_json: {text[:100]}")

    triple = SPOTriple(
        subject=str(parsed.get("subject", "")).strip().lower(),
        predicate=str(parsed.get("predicate", "")).strip().lower().replace(" ", "_"),
        object=str(parsed.get("object", "")).strip().lower(),
    )

    if not triple.is_valid():
        raise ValueError(f"incomplete: {triple}")

    return triple


async def extract_spo(
    llm: LLMProvider,
    claim: str,
    timeout: float = 15.0,
    max_retries: int = 3,
    base_delay: float = 0.5,
) -> SPOTriple | None:
    """Extract SPO triple from a claim using LLM with retry logic.

    Args:
        llm: LLM provider instance.
        claim: The claim text to extract from.
        timeout: Request timeout in seconds per attempt.
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay for exponential backoff.

    Returns:
        SPOTriple if extraction succeeds, None otherwise.
    """
    if not claim or len(claim) < 10:
        return None

    last_error: str | None = None
    for attempt in range(max_retries):
        try:
            triple = await _extract_spo_once(llm, claim, timeout)
            if attempt > 0:
                logger.info(
                    "spo_extraction_retry_succeeded",
                    attempt=attempt + 1,
                    subject=triple.subject if triple else None,
                )
            else:
                logger.debug(
                    "spo_extraction_ok",
                    subject=triple.subject if triple else None,
                    predicate=triple.predicate if triple else None,
                    object=triple.object if triple else None,
                )
            return triple

        except TimeoutError:
            last_error = "timeout"
        except ValueError as e:
            last_error = str(e)
        except Exception as e:
            last_error = str(e)

        if attempt < max_retries - 1:
            delay = base_delay * (2 ** attempt)
            logger.debug(
                "spo_extraction_retry",
                attempt=attempt + 1,
                max_retries=max_retries,
                delay=delay,
                error=last_error,
            )
            await asyncio.sleep(delay)

    logger.warning(
        "spo_extraction_failed",
        claim_len=len(claim),
        attempts=max_retries,
        last_error=last_error,
    )
    return None
