"""SAGE source content verification for claims."""

from __future__ import annotations

import structlog

from context_service.llm.base import LLMProvider

logger = structlog.get_logger(__name__)


async def verify_claim_against_source(
    claim_content: str,
    source_content: str,
    llm: LLMProvider,
) -> bool:
    """Check if source content supports the claim.

    Returns True if the source directly supports or implies the claim.
    Returns False if the source contradicts, is unrelated, or doesn't support it.

    Fails open: returns True on LLM errors to avoid blocking promotion.
    """
    prompt = f"""Does this source text support the following claim?

CLAIM: {claim_content}

SOURCE:
{source_content}

Answer YES if the source directly supports or implies the claim.
Answer NO if the source contradicts, is unrelated, or doesn't support the claim.
Answer only YES or NO."""

    try:
        response_text, _usage = await llm.complete(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
        )
        return "YES" in response_text.upper()
    except Exception as e:
        # ponytail: fail open, don't block promotion on LLM errors
        logger.warning("source_verification_failed", error=str(e))
        return True
