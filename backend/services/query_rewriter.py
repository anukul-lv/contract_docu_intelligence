"""Query rewriter — Healthcare term normalization and query decomposition.

For Routes B and C, rewrites the user query to expand healthcare abbreviations,
normalize terminology, and add synonyms for better retrieval recall.

For Route C only, decomposes complex queries into 2-4 independent sub-queries.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from backend.dependencies import execute_sql
from backend.config import get_settings

logger = logging.getLogger(__name__)

# Static abbreviation map for fast local expansion (no LLM call needed)
_HEALTHCARE_ABBREVIATIONS: dict[str, str] = {
    "cap rate": "capitation PMPM rate",
    "drg": "Diagnosis Related Group",
    "pmpm": "Per Member Per Month",
    "baa": "Business Associate Agreement",
    "ma": "Medicare Advantage",
    "mco": "Managed Care Organization",
    "npi": "National Provider Identifier",
    "tin": "Tax Identification Number",
    "oon": "Out of Network",
    "ehr": "Electronic Health Record",
    "cms": "Centers for Medicare and Medicaid Services",
    "mlr": "Medical Loss Ratio",
    "hmo": "Health Maintenance Organization",
    "ppo": "Preferred Provider Organization",
    "epo": "Exclusive Provider Organization",
    "pos": "Point of Service",
    "snf": "Skilled Nursing Facility",
    "asc": "Ambulatory Surgery Center",
    "rvu": "Relative Value Unit",
    "aco": "Accountable Care Organization",
    "hedis": "Healthcare Effectiveness Data and Information Set",
    "ncqa": "National Committee for Quality Assurance",
}

# State abbreviation map
_STATE_ABBREVIATIONS: dict[str, str] = {
    "tx": "Texas", "ca": "California", "ny": "New York", "fl": "Florida",
    "il": "Illinois", "pa": "Pennsylvania", "oh": "Ohio", "ga": "Georgia",
    "nc": "North Carolina", "mi": "Michigan", "nj": "New Jersey",
    "va": "Virginia", "wa": "Washington", "az": "Arizona", "ma": "Massachusetts",
    "tn": "Tennessee", "in": "Indiana", "mo": "Missouri", "md": "Maryland",
    "wi": "Wisconsin", "co": "Colorado", "mn": "Minnesota", "sc": "South Carolina",
    "al": "Alabama", "la": "Louisiana", "ky": "Kentucky", "or": "Oregon",
    "ok": "Oklahoma", "ct": "Connecticut", "ut": "Utah", "ia": "Iowa",
    "nv": "Nevada", "ar": "Arkansas", "ms": "Mississippi", "ks": "Kansas",
}


@dataclass
class RewriteResult:
    original_query: str
    rewritten_query: str
    search_terms: list[str] = field(default_factory=list)
    expansions_applied: list[str] = field(default_factory=list)


@dataclass
class DecompositionResult:
    original_query: str
    sub_queries: list[str]
    reasoning: str


def _apply_local_expansions(query: str) -> tuple[str, list[str]]:
    """Apply static abbreviation expansions without an LLM call."""
    expanded = query
    applied: list[str] = []
    query_lower = query.lower()

    for abbr, full_form in _HEALTHCARE_ABBREVIATIONS.items():
        if abbr in query_lower and full_form.lower() not in query_lower:
            expanded = expanded + f" ({full_form})"
            applied.append(f"{abbr} → {full_form}")

    for abbr, state_name in _STATE_ABBREVIATIONS.items():
        # Match standalone state abbrevs (e.g., "TX Medicaid")
        import re
        pattern = rf"\b{abbr}\b"
        if re.search(pattern, query_lower) and state_name.lower() not in query_lower:
            expanded = re.sub(pattern, f"{abbr.upper()} ({state_name})", expanded, flags=re.IGNORECASE)
            applied.append(f"{abbr.upper()} → {state_name}")

    return expanded, applied


async def rewrite_query(query: str, use_llm: bool = True) -> RewriteResult:
    """Rewrite a query with healthcare term normalization.

    Step 1: Apply local abbreviation expansions (fast, no cost).
    Step 2: Optionally use ai_query for deeper rewriting (LLM call).

    Args:
        query: The original user query.
        use_llm: Whether to use the LLM for advanced rewriting.

    Returns:
        RewriteResult with the rewritten query and applied expansions.
    """
    # Step 1: Local expansions
    expanded, applied = _apply_local_expansions(query)

    if not use_llm or not applied:
        return RewriteResult(
            original_query=query,
            rewritten_query=expanded if applied else query,
            search_terms=[query],
            expansions_applied=applied,
        )

    # Step 2: LLM rewriting for deeper normalization
    try:
        sql = """
        SELECT ai_query(
          'databricks-claude-haiku-4-5',
          CONCAT(
            'Rewrite this healthcare contract query for better retrieval. ',
            'Expand abbreviations, normalize terms, add synonyms. ',
            'Return JSON only. ',
            'Original: ', :user_query
          ),
          responseFormat => '{"rewritten_query": "STRING", "search_terms": "ARRAY<STRING>"}'
        ) AS rewritten
        """
        rows = await execute_sql(sql, parameters={"user_query": query})
        if rows:
            result = json.loads(rows[0]["rewritten"])
            return RewriteResult(
                original_query=query,
                rewritten_query=result.get("rewritten_query", expanded),
                search_terms=result.get("search_terms", [query]),
                expansions_applied=applied + ["llm_rewrite"],
            )
    except Exception as e:
        logger.warning("LLM rewrite failed, using local expansion: %s", e)

    return RewriteResult(
        original_query=query,
        rewritten_query=expanded,
        search_terms=[expanded],
        expansions_applied=applied,
    )


async def decompose_query(query: str) -> DecompositionResult:
    """Decompose a complex Route C query into 2-4 independent sub-queries.

    Each sub-query can be answered independently and results are merged.
    """
    try:
        sql = """
        SELECT ai_query(
          'databricks-claude-haiku-4-5',
          CONCAT(
            'Decompose this complex healthcare contract query into 2-4 simpler sub-queries. ',
            'Each sub-query should be answerable independently from a document search. ',
            'Return JSON only. ',
            'Query: ', :user_query
          ),
          responseFormat => '{"sub_queries": "ARRAY<STRING>", "reasoning": "STRING"}'
        ) AS decomposed
        """
        rows = await execute_sql(sql, parameters={"user_query": query})
        if rows:
            result = json.loads(rows[0]["decomposed"])
            sub_queries = result.get("sub_queries", [query])
            # Enforce 2-4 limit
            if len(sub_queries) < 2:
                sub_queries = [query]
            elif len(sub_queries) > 4:
                sub_queries = sub_queries[:4]
            return DecompositionResult(
                original_query=query,
                sub_queries=sub_queries,
                reasoning=result.get("reasoning", ""),
            )
    except Exception as e:
        logger.warning("Query decomposition failed: %s", e)

    return DecompositionResult(
        original_query=query,
        sub_queries=[query],
        reasoning="Decomposition failed, using original query",
    )
