"""Reranker — Optional LLM-based reranking for retrieved chunks.

Feature-flagged via `enable_reranker`. When disabled, chunks pass through
with their original AI Search scores. When enabled, uses a lightweight
LLM call to rerank top-K chunks for relevance.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from backend.dependencies import execute_sql
from backend.services.feature_flag_cache import flag_cache
from backend.services.vector_service import SearchResult

logger = logging.getLogger(__name__)

_RERANK_TOP_K = 10  # Only rerank top K chunks to control cost


@dataclass
class RerankResult:
    results: list[SearchResult]
    reranked: bool
    latency_ms: int


async def rerank_chunks(
    query: str,
    chunks: list[SearchResult],
    top_k: int = _RERANK_TOP_K,
) -> RerankResult:
    """Optionally rerank retrieved chunks using LLM relevance scoring.

    Args:
        query: The user's original or rewritten query.
        chunks: Retrieved chunks from vector search.
        top_k: Max chunks to rerank (controls cost).

    Returns:
        RerankResult with reranked (or original) chunks.
    """
    import time
    start_ms = int(time.time() * 1000)

    if not await flag_cache.is_enabled("enable_reranker"):
        return RerankResult(
            results=chunks,
            reranked=False,
            latency_ms=int(time.time() * 1000) - start_ms,
        )

    if len(chunks) <= 1:
        return RerankResult(
            results=chunks,
            reranked=False,
            latency_ms=int(time.time() * 1000) - start_ms,
        )

    # Only rerank top K by original score
    to_rerank = chunks[:top_k]
    remainder = chunks[top_k:]

    # Build chunk summaries for LLM
    chunk_summaries = []
    for i, c in enumerate(to_rerank):
        preview = c.chunk_to_retrieve[:300]
        chunk_summaries.append(f"[{i}] {c.section_header or 'N/A'}: {preview}")

    summaries_text = "\n".join(chunk_summaries)

    try:
        sql = """
        SELECT ai_query(
          'databricks-claude-haiku-4-5',
          CONCAT(
            'Given this query about healthcare contracts, rank these text chunks by relevance. ',
            'Return a JSON array of chunk indices ordered by relevance (most relevant first). ',
            'Query: ', :user_query, '\n\nChunks:\n',
            :chunk_summaries
          ),
          responseFormat => '{"ranking": "ARRAY<INT>"}'
        ) AS ranked
        """
        rows = await execute_sql(sql, parameters={
            "user_query": query,
            "chunk_summaries": summaries_text,
        })
        if rows:
            result = json.loads(rows[0]["ranked"])
            ranking = result.get("ranking", list(range(len(to_rerank))))

            # Reorder chunks by LLM ranking
            reranked = []
            seen = set()
            for idx in ranking:
                if 0 <= idx < len(to_rerank) and idx not in seen:
                    reranked.append(to_rerank[idx])
                    seen.add(idx)

            # Add any chunks not mentioned in ranking
            for i, c in enumerate(to_rerank):
                if i not in seen:
                    reranked.append(c)

            final = reranked + remainder
            elapsed = int(time.time() * 1000) - start_ms
            logger.info("Reranker: reranked %d chunks in %dms", len(to_rerank), elapsed)

            return RerankResult(
                results=final,
                reranked=True,
                latency_ms=elapsed,
            )
    except Exception as e:
        logger.warning("Reranker failed, using original order: %s", e)

    return RerankResult(
        results=chunks,
        reranked=False,
        latency_ms=int(time.time() * 1000) - start_ms,
    )
