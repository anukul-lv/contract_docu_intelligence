"""Route classifier — Rule-based pre-classification for chat queries.

Runs BEFORE agent invocation to select the optimal retrieval strategy:
  Route A: SQL aggregation (cheapest, < 5s)
  Route B: Single factual lookup via ai_search (low cost, < 8s)
  Route C: Full hybrid agentic with query decomposition (highest cost, < 15s)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Route(str, Enum):
    A = "A"  # SQL aggregation
    B = "B"  # Single factual lookup
    C = "C"  # Full hybrid agentic


@dataclass(frozen=True)
class RouteResult:
    route: Route
    reason: str
    cost_tier: str  # "lowest", "low", "highest"
    latency_target_ms: int


# Keyword sets for classification
_AGGREGATE_KEYWORDS = frozenset({
    "average", "total", "count", "how many", "sum", "highest",
    "lowest", "minimum", "maximum", "mean", "median",
    "percentage", "percent", "ratio", "distribution",
    "top", "bottom", "most common", "least common",
    "breakdown", "summary", "aggregate",
})

_COMPLEX_KEYWORDS = frozenset({
    "compare", "comparison", "difference", "versus", " vs ",
    "analyze", "analysis", "why", "explain how", "explain why",
    "across all", "trend", "over time", "between",
    "implications", "impact", "recommend", "should we",
    "pros and cons", "trade-off", "multi", "all contracts",
    "what if", "scenario",
})

_DOCUMENT_REFERENCE_PATTERN = re.compile(
    r"(document|contract|agreement|amendment|file)\s*#?\s*\d+"
    r"|\b[A-Z]{2,}-\d{3,}\b"  # contract IDs like HSP-00123
    r"|\bpage\s+\d+",
    re.IGNORECASE,
)


def classify_route(query: str) -> RouteResult:
    """Classify a user query into Route A, B, or C.

    Args:
        query: The raw user question.

    Returns:
        RouteResult with the selected route, reason, cost tier, and latency target.
    """
    query_lower = query.lower()

    # Check for aggregate/KPI queries first (Route A)
    matched_agg = [kw for kw in _AGGREGATE_KEYWORDS if kw in query_lower]
    if matched_agg:
        return RouteResult(
            route=Route.A,
            reason=f"Aggregate keyword detected: {matched_agg[0]}",
            cost_tier="lowest",
            latency_target_ms=5000,
        )

    # Check for complex/comparative queries (Route C)
    matched_complex = [kw for kw in _COMPLEX_KEYWORDS if kw in query_lower]
    if matched_complex:
        return RouteResult(
            route=Route.C,
            reason=f"Complex reasoning keyword: {matched_complex[0]}",
            cost_tier="highest",
            latency_target_ms=15000,
        )

    # Check for multi-sentence or multi-clause queries (Route C)
    sentence_count = len([s for s in re.split(r"[.?!]", query) if s.strip()])
    if sentence_count >= 3:
        return RouteResult(
            route=Route.C,
            reason="Multi-sentence query detected",
            cost_tier="highest",
            latency_target_ms=15000,
        )

    # Default: single factual lookup (Route B)
    reason = "Single factual lookup (default)"
    if _DOCUMENT_REFERENCE_PATTERN.search(query):
        reason = "Specific document reference detected"

    return RouteResult(
        route=Route.B,
        reason=reason,
        cost_tier="low",
        latency_target_ms=8000,
    )
