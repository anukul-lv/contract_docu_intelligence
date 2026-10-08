"""Vector service — AI Search hybrid retrieval wrapper.

Wraps the Databricks Vector Search SDK for hybrid retrieval (BM25 + vector + RRF)
with metadata filters specific to healthcare contracts.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from databricks.sdk import WorkspaceClient

from backend.services.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

APP_CATALOG = os.environ.get("APP_CATALOG", "dev")
APP_SCHEMA = os.environ.get("APP_SCHEMA", "doc_intel")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")

INDEX_NAME = f"{APP_CATALOG}.{APP_SCHEMA}.document_chunks_index"
ENDPOINT_NAME = f"{ENVIRONMENT}_healthcare_search_endpoint"


@dataclass
class SearchResult:
    chunk_id: str
    document_version_id: str
    chunk_index: int
    chunk_to_retrieve: str
    page_numbers: list[int] | None
    section_header: str | None
    contract_type: str | None
    state_jurisdiction: str | None
    effective_date: str | None
    expiration_date: str | None
    reimbursement_method: str | None
    contains_table: bool
    score: float


@dataclass
class SearchResponse:
    results: list[SearchResult]
    total_count: int
    latency_ms: int
    query_type: str  # "ANN" or "HYBRID"
    filters_applied: dict[str, Any] = field(default_factory=dict)


class VectorService:
    """AI Search hybrid retrieval for healthcare contract chunks."""

    def __init__(self) -> None:
        self._client = WorkspaceClient()
        self._circuit = CircuitBreaker(
            name="ai_search",
            failure_threshold=3,
            recovery_timeout_sec=60,
        )

    def _build_filters(self, filters: dict[str, Any] | None) -> dict[str, Any] | None:
        """Convert user-friendly filters to AI Search filter dict.

        Supported filters:
        - contract_type: str or list[str] (exact/IN)
        - state_jurisdiction: str or list[str] (exact/IN)
        - effective_date_min / effective_date_max: str (ISO date range)
        - expiration_date_min / expiration_date_max: str (ISO date range)
        - reimbursement_method: str (exact match)
        - contains_table: bool
        - document_version_id: str or list[str] (exact/IN, for doc-specific queries)
        """
        if not filters:
            return None

        conditions: dict[str, Any] = {}

        for key in ("contract_type", "state_jurisdiction", "reimbursement_method", "document_version_id"):
            val = filters.get(key)
            if val is not None:
                conditions[key] = val  # SDK handles str vs list

        if filters.get("contains_table") is not None:
            conditions["contains_table"] = filters["contains_table"]

        # Date range filters
        for date_col in ("effective_date", "expiration_date"):
            min_val = filters.get(f"{date_col}_min")
            max_val = filters.get(f"{date_col}_max")
            if min_val or max_val:
                range_filter: dict[str, str] = {}
                if min_val:
                    range_filter[">="] = min_val
                if max_val:
                    range_filter["<="] = max_val
                conditions[date_col] = range_filter

        return conditions if conditions else None

    async def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        num_results: int = 20,
        query_type: str = "ANN",
    ) -> SearchResponse:
        """Execute hybrid retrieval with optional metadata filters.

        Args:
            query: The search query (text or rewritten query).
            filters: Metadata filters (see _build_filters).
            num_results: Max chunks to return (default 20).
            query_type: "ANN" for pure vector, "HYBRID" for BM25 + vector + RRF.

        Returns:
            SearchResponse with ranked results.
        """
        start_ms = int(time.time() * 1000)

        search_filters = self._build_filters(filters)

        async def _do_search() -> dict:
            return self._client.vector_search_indexes.query_index(
                index_name=INDEX_NAME,
                columns=[
                    "chunk_id", "document_version_id", "chunk_index",
                    "chunk_to_retrieve", "page_numbers", "section_header",
                    "contract_type", "state_jurisdiction", "effective_date",
                    "expiration_date", "reimbursement_method", "contains_table",
                ],
                query_text=query,
                num_results=num_results,
                query_type=query_type,
                filters_json=search_filters,
            )

        try:
            response = await self._circuit.call(_do_search)
        except Exception as e:
            logger.error("AI Search query failed: %s", e)
            return SearchResponse(
                results=[], total_count=0,
                latency_ms=int(time.time() * 1000) - start_ms,
                query_type=query_type,
                filters_applied=filters or {},
            )

        # Parse results
        results: list[SearchResult] = []
        if hasattr(response, "result") and response.result:
            data_array = response.result.data_array or []
            columns = [c.name for c in (response.manifest.columns if response.manifest else [])]
            for row in data_array:
                row_dict = dict(zip(columns, row)) if columns else {}
                results.append(SearchResult(
                    chunk_id=row_dict.get("chunk_id", ""),
                    document_version_id=row_dict.get("document_version_id", ""),
                    chunk_index=int(row_dict.get("chunk_index", 0)),
                    chunk_to_retrieve=row_dict.get("chunk_to_retrieve", ""),
                    page_numbers=row_dict.get("page_numbers"),
                    section_header=row_dict.get("section_header"),
                    contract_type=row_dict.get("contract_type"),
                    state_jurisdiction=row_dict.get("state_jurisdiction"),
                    effective_date=row_dict.get("effective_date"),
                    expiration_date=row_dict.get("expiration_date"),
                    reimbursement_method=row_dict.get("reimbursement_method"),
                    contains_table=bool(row_dict.get("contains_table", False)),
                    score=float(row_dict.get("score", 0.0)),
                ))

        elapsed_ms = int(time.time() * 1000) - start_ms
        logger.info(
            "AI Search: %d results in %dms (type=%s, filters=%s)",
            len(results), elapsed_ms, query_type, bool(search_filters),
        )

        return SearchResponse(
            results=results,
            total_count=len(results),
            latency_ms=elapsed_ms,
            query_type=query_type,
            filters_applied=filters or {},
        )

    async def search_for_tables(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        num_results: int = 10,
    ) -> SearchResponse:
        """Search specifically for table-containing chunks.

        Used when query involves rates, fee schedules, or tabular data.
        """
        table_filters = dict(filters or {})
        table_filters["contains_table"] = True
        return await self.search(
            query=query,
            filters=table_filters,
            num_results=num_results,
            query_type="HYBRID",
        )
