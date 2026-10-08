"""Groundedness checker — Post-generation claim verification.

For financial/compliance queries, uses a lightweight LLM call to verify
that every claim in the agent's response is grounded in retrieved context.
Feature-flagged via `enable_inline_groundedness`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from backend.dependencies import execute_sql

logger = logging.getLogger(__name__)


@dataclass
class ClaimCheck:
    claim: str
    supported: bool
    evidence: str


@dataclass
class GroundednessResult:
    score: float  # 0.0 - 1.0
    claims: list[ClaimCheck] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    checked: bool = True


async def check_groundedness(
    query: str,
    generated_answer: str,
    tool_results: list[dict],
    threshold: float = 0.7,
) -> GroundednessResult:
    """Verify agent response groundedness against retrieved context.

    Args:
        query: The user's original question.
        generated_answer: The agent's generated response.
        tool_results: Results from tool calls (used as context).
        threshold: Minimum acceptable groundedness score.

    Returns:
        GroundednessResult with per-claim checks.
    """
    # Build context from tool results
    context_parts = []
    for tr in tool_results:
        result = tr.get("result", {})
        if isinstance(result, dict):
            # ai_search_tool results
            chunks = result.get("chunks", [])
            for chunk in chunks:
                text = chunk.get("chunk_text", "")
                if text:
                    context_parts.append(text[:500])
            # sql_query results
            rows = result.get("rows", [])
            if rows:
                context_parts.append(json.dumps(rows[:10]))

    if not context_parts:
        # No context to check against — skip
        return GroundednessResult(score=1.0, checked=False)

    context = "\n---\n".join(context_parts)[:10000]  # Cap context size
    answer_capped = generated_answer[:5000]

    try:
        sql = """
        SELECT ai_query(
          'databricks-claude-haiku-4-5',
          CONCAT(
            'Given this context and answer, rate groundedness 0.0-1.0. ',
            'Extract specific factual claims and check each against the context. ',
            'Return JSON only.',
            '\n\nContext: ', :retrieved_context,
            '\n\nAnswer: ', :generated_answer
          ),
          responseFormat => '{"groundedness": "FLOAT", "claims": "ARRAY<STRUCT<claim: STRING, supported: BOOLEAN, evidence: STRING>>", "unsupported_claims": "ARRAY<STRING>"}'
        ) AS groundedness_result
        """
        rows = await execute_sql(sql, parameters={
            "retrieved_context": context,
            "generated_answer": answer_capped,
        })
        if rows:
            result = json.loads(rows[0]["groundedness_result"])
            score = float(result.get("groundedness", 1.0))

            claims = [
                ClaimCheck(
                    claim=c.get("claim", ""),
                    supported=c.get("supported", True),
                    evidence=c.get("evidence", ""),
                )
                for c in result.get("claims", [])
            ]

            unsupported = result.get("unsupported_claims", [])

            logger.info(
                "Groundedness check: score=%.2f, claims=%d, unsupported=%d",
                score, len(claims), len(unsupported),
            )

            return GroundednessResult(
                score=score,
                claims=claims,
                unsupported_claims=unsupported,
            )
    except Exception as e:
        logger.warning("Groundedness check failed: %s", e)

    # On failure, return neutral (don't block the response)
    return GroundednessResult(score=1.0, checked=False)
