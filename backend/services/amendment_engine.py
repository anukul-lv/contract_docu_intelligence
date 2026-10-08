"""Amendment engine — Supersession chain resolution.

Resolves the current-in-force contract state across amendment chains.
Builds a directed graph from contracts_relationships, performs topological sort
by effective_date, and returns the latest ACTIVE value for each field.

Relationship types: AMENDS, SUPERSEDES, EXHIBITS, ADDENDUM, RESTATES.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backend.dependencies import execute_sql
from backend.config import get_settings
from backend.services.feature_flag_cache import flag_cache

logger = logging.getLogger(__name__)


@dataclass
class Relationship:
    relationship_id: str
    parent_document_id: str
    child_document_id: str
    relationship_type: str
    applicability_status: str
    effective_date: date | None
    expiration_date: date | None
    supersession_notes: str | None


@dataclass
class FieldResolution:
    value: Any
    source_document_id: str
    source_version_id: str
    status: str  # ACTIVE, SUPERSEDED, INHERITED
    chain: list[str]  # Document IDs in the resolution chain


@dataclass
class ResolutionResult:
    document_family_id: str
    fields: dict[str, FieldResolution]
    chain_depth: int
    relationships: list[Relationship]


class AmendmentEngine:
    """Resolves current-in-force state across amendment chains."""

    async def _fetch_relationships(self, document_family_id: str) -> list[Relationship]:
        """Fetch all relationships for a document family."""
        settings = get_settings()
        sql = f"""
        SELECT
          relationship_id,
          parent_document_id,
          child_document_id,
          relationship_type,
          CASE
            WHEN applicability_status = 'SUPERSEDED' THEN 'SUPERSEDED'
            WHEN expiration_date < current_date() THEN 'EXPIRED'
            WHEN effective_date > current_date() THEN 'FUTURE'
            WHEN applicability_status = 'TERMINATED' THEN 'TERMINATED'
            ELSE 'ACTIVE'
          END AS computed_status,
          effective_date,
          expiration_date,
          supersession_notes
        FROM {settings.customer_catalog}.{settings.customer_schema}.contracts_relationships
        WHERE parent_document_id = :family_id
           OR child_document_id = :family_id
        ORDER BY effective_date ASC NULLS LAST
        """
        rows = await execute_sql(sql, parameters={"family_id": document_family_id})
        return [
            Relationship(
                relationship_id=r["relationship_id"],
                parent_document_id=r["parent_document_id"],
                child_document_id=r["child_document_id"],
                relationship_type=r["relationship_type"],
                applicability_status=r["computed_status"],
                effective_date=r.get("effective_date"),
                expiration_date=r.get("expiration_date"),
                supersession_notes=r.get("supersession_notes"),
            )
            for r in rows
        ]

    # Field columns from contracts_parsed DDL (R1_02)
    _FIELD_COLUMNS = [
        "contract_type", "parties", "effective_date", "expiration_date",
        "reimbursement_method", "state_jurisdiction", "covered_services",
        "termination_clause", "executive_summary",
    ]

    async def _fetch_document_fields(
        self, document_version_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Fetch extracted fields for a set of documents.

        Reads individual field columns from contracts_parsed (per R1_02 DDL)
        rather than a single extracted_fields VARIANT column.

        Returns: { document_version_id: { field_name: value, ... } }
        """
        if not document_version_ids:
            return {}

        settings = get_settings()
        field_cols = ", ".join(self._FIELD_COLUMNS)
        # Use IN clause with parameterized list (build safely)
        placeholders = ", ".join(f":id_{i}" for i in range(len(document_version_ids)))
        params = {f"id_{i}": doc_id for i, doc_id in enumerate(document_version_ids)}
        sql = f"""
        SELECT
          document_version_id,
          {field_cols}
        FROM {settings.customer_catalog}.{settings.customer_schema}.contracts_parsed
        WHERE document_version_id IN ({placeholders})
        """
        rows = await execute_sql(sql, parameters=params)
        result: dict[str, dict[str, Any]] = {}
        for r in rows:
            fields = {col: r.get(col) for col in self._FIELD_COLUMNS if r.get(col) is not None}
            result[r["document_version_id"]] = fields
        return result

    def _build_chain(
        self, relationships: list[Relationship], root_id: str
    ) -> list[str]:
        """Build topologically sorted chain from root outward.

        Returns document IDs in order: [root, first_amendment, second_amendment, ...].
        Only follows ACTIVE relationships.
        """
        # Build adjacency (parent -> children)
        children: dict[str, list[tuple[str, Relationship]]] = defaultdict(list)
        for rel in relationships:
            if rel.applicability_status == "ACTIVE" and rel.relationship_type in (
                "AMENDS", "SUPERSEDES", "RESTATES", "ADDENDUM",
            ):
                children[rel.parent_document_id].append(
                    (rel.child_document_id, rel)
                )

        # BFS from root
        chain = [root_id]
        visited = {root_id}
        queue = [root_id]
        while queue:
            current = queue.pop(0)
            for child_id, _rel in sorted(
                children.get(current, []),
                key=lambda x: x[1].effective_date or date.min,
            ):
                if child_id not in visited:
                    visited.add(child_id)
                    chain.append(child_id)
                    queue.append(child_id)

        return chain

    async def resolve_current_state(
        self, document_family_id: str
    ) -> ResolutionResult:
        """Walk the supersession chain and return current-in-force values.

        Algorithm:
        1. Fetch all relationships for this document family
        2. Build directed graph
        3. Topological sort by effective_date
        4. For each field, latest ACTIVE document wins
        5. Inherit fields from parent if child doesn't extract them

        Returns:
            ResolutionResult with per-field resolutions including chain.
        """
        relationships = await self._fetch_relationships(document_family_id)
        chain = self._build_chain(relationships, document_family_id)

        # Fetch fields for all documents in chain
        doc_fields = await self._fetch_document_fields(chain)

        # Resolve: walk chain forward, latest value wins per field
        resolved: dict[str, FieldResolution] = {}
        for doc_id in chain:
            fields = doc_fields.get(doc_id, {})
            for field_name, value in fields.items():
                if value is not None:
                    resolved[field_name] = FieldResolution(
                        value=value,
                        source_document_id=doc_id,
                        source_version_id=doc_id,  # Will be enriched by caller
                        status="ACTIVE" if doc_id == chain[-1] else "SUPERSEDED",
                        chain=[d for d in chain[:chain.index(doc_id) + 1]],
                    )

        # Mark inherited fields
        for fname, res in resolved.items():
            if res.source_document_id != chain[-1]:
                res.status = "INHERITED"

        return ResolutionResult(
            document_family_id=document_family_id,
            fields=resolved,
            chain_depth=len(chain),
            relationships=relationships,
        )

    async def detect_relationships(
        self, new_document_version_id: str
    ) -> list[dict[str, Any]]:
        """During extraction, detect if the new document amends/supersedes existing ones.

        Uses ai_extract to identify amendment references in the document.

        Returns:
            List of { parent_id, relationship_type, effective_date, confidence }.
        """
        settings = get_settings()
        sql = f"""
        SELECT ai_extract(
          parsed_content,
          '{{
            "amends_document": "STRING",
            "supersedes_document": "STRING",
            "effective_date": "DATE",
            "relationship_type": "STRING"
          }}',
          enableConfidenceScores => true
        ) AS amendment_refs
        FROM {settings.customer_catalog}.{settings.customer_schema}.contracts_parsed
        WHERE document_version_id = :new_doc_vid
        """
        rows = await execute_sql(sql, parameters={"new_doc_vid": new_document_version_id})
        if not rows:
            return []

        import json
        refs = rows[0].get("amendment_refs")
        if isinstance(refs, str):
            refs = json.loads(refs)

        detected: list[dict[str, Any]] = []
        if refs:
            for ref_type in ("amends_document", "supersedes_document"):
                ref_value = refs.get(ref_type)
                if ref_value:
                    rel_type = "AMENDS" if "amends" in ref_type else "SUPERSEDES"
                    detected.append({
                        "parent_id": ref_value,
                        "relationship_type": rel_type,
                        "effective_date": refs.get("effective_date"),
                        "confidence": refs.get(f"{ref_type}_confidence", 0.0),
                    })

        return detected
