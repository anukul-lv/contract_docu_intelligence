"""Provenance service — 5-table JOIN for full evidence chain.

Traces any extracted value from current state back to the source file:
  contracts_current → review_actions → contracts_parsed → review_queue → contracts_relationships

Expected latency: < 2 seconds.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from backend.dependencies import execute_sql
from backend.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class CurrentState:
    trusted_value: Any
    review_status: str
    confidence_score: float


@dataclass
class ReviewAction:
    action_type: str
    previous_value: Any | None
    new_value: Any | None
    performed_by: str
    performed_at: str


@dataclass
class ExtractedValue:
    ai_extracted_value: Any
    extraction_profile: str
    extraction_ts: str


@dataclass
class ConfidenceExplanation:
    ai_extract_confidence: float
    ocr_quality: float
    format_validation: bool
    cross_field_consistency: bool
    weighted_score: float


@dataclass
class Citation:
    page: int
    section: str | None
    text: str
    highlight_coords: dict[str, Any] | None = None


@dataclass
class SourceFile:
    file_name: str
    file_path: str
    file_checksum: str | None
    upload_date: str


@dataclass
class AmendmentLink:
    document_id: str
    relationship_type: str
    status: str
    effective_date: str | None


@dataclass
class ProvenanceResult:
    current_state: CurrentState
    review_actions: list[ReviewAction]
    extracted_value: ExtractedValue
    confidence_explanation: ConfidenceExplanation
    citations: list[Citation]
    source_file: SourceFile
    amendment_chain: list[AmendmentLink]


class ProvenanceService:
    """Full evidence chain for any extracted value."""

    async def get_provenance(
        self, document_version_id: str, field_name: str
    ) -> ProvenanceResult | None:
        """5-table JOIN for full provenance chain.

        Tables joined:
        1. contracts_current (current state)
        2. review_actions (review history)
        3. contracts_parsed (extraction output)
        4. review_queue (confidence explanation)
        5. contracts_relationships (amendment chain)
        """
        settings = get_settings()
        cc = f"{settings.customer_catalog}.{settings.customer_schema}"
        ac = f"{settings.app_catalog}.{settings.app_schema}"

        # --- 1. Current state from contracts_current ---
        current_sql = f"""
        SELECT
          trusted_value,
          review_status,
          confidence_score
        FROM {cc}.contracts_current
        WHERE document_version_id = :doc_id
          AND field_name = :field_name
        LIMIT 1
        """
        prov_params = {"doc_id": document_version_id, "field_name": field_name}
        current_rows = await execute_sql(current_sql, parameters=prov_params)
        if not current_rows:
            return None

        cr = current_rows[0]
        current_state = CurrentState(
            trusted_value=cr["trusted_value"],
            review_status=cr["review_status"],
            confidence_score=float(cr.get("confidence_score", 0)),
        )

        # --- 2. Review actions history ---
        actions_sql = f"""
        SELECT
          action_type,
          previous_value,
          new_value,
          performed_by,
          CAST(performed_at AS STRING) AS performed_at
        FROM {ac}.review_actions
        WHERE document_version_id = :doc_id
          AND field_name = :field_name
        ORDER BY performed_at DESC
        LIMIT 20
        """
        action_rows = await execute_sql(actions_sql, parameters=prov_params)
        review_actions = [
            ReviewAction(
                action_type=r["action_type"],
                previous_value=r.get("previous_value"),
                new_value=r.get("new_value"),
                performed_by=r["performed_by"],
                performed_at=r["performed_at"],
            )
            for r in action_rows
        ]

        # --- 3. Extracted value from contracts_parsed ---
        # Column names aligned with R1_02 DDL: extraction_profile, extraction_ts,
        # confidence_explanation. Individual field columns instead of extracted_fields.
        parsed_sql = f"""
        SELECT
          contract_type, parties, effective_date, expiration_date,
          reimbursement_method, state_jurisdiction, covered_services,
          termination_clause, executive_summary,
          extraction_profile,
          CAST(extraction_ts AS STRING) AS extraction_ts,
          file_name,
          file_path,
          file_checksum,
          CAST(extraction_ts AS STRING) AS upload_date,
          confidence_explanation
        FROM {cc}.contracts_parsed
        WHERE document_version_id = :doc_id
        LIMIT 1
        """
        parsed_rows = await execute_sql(parsed_sql, parameters={"doc_id": document_version_id})
        if not parsed_rows:
            return None

        pr = parsed_rows[0]

        # Build extracted fields dict from individual columns
        _field_columns = [
            "contract_type", "parties", "effective_date", "expiration_date",
            "reimbursement_method", "state_jurisdiction", "covered_services",
            "termination_clause", "executive_summary",
        ]
        extracted_fields = {col: pr.get(col) for col in _field_columns if pr.get(col) is not None}

        extracted_value = ExtractedValue(
            ai_extracted_value=extracted_fields.get(field_name),
            extraction_profile=pr.get("extraction_profile", "unknown"),
            extraction_ts=pr.get("extraction_ts", ""),
        )

        source_file = SourceFile(
            file_name=pr.get("file_name", ""),
            file_path=pr.get("file_path", ""),
            file_checksum=pr.get("file_checksum"),
            upload_date=pr.get("upload_date", ""),
        )

        # --- 4. Confidence explanation from review_queue ---
        conf_sql = f"""
        SELECT
          ai_confidence,
          format_validation_passed,
          cross_field_passed,
          citation_present,
          composite_score
        FROM {ac}.review_queue
        WHERE document_version_id = :doc_id
          AND field_name = :field_name
        LIMIT 1
        """
        conf_rows = await execute_sql(conf_sql, parameters=prov_params)
        if conf_rows:
            cfr = conf_rows[0]
            confidence_explanation = ConfidenceExplanation(
                ai_extract_confidence=float(cfr.get("ai_confidence", 0)),
                ocr_quality=0.95,  # Placeholder — would come from parse metadata
                format_validation=bool(cfr.get("format_validation_passed", False)),
                cross_field_consistency=bool(cfr.get("cross_field_passed", False)),
                weighted_score=float(cfr.get("composite_score", 0)),
            )
        else:
            confidence_explanation = ConfidenceExplanation(
                ai_extract_confidence=current_state.confidence_score,
                ocr_quality=0.95,
                format_validation=True,
                cross_field_consistency=True,
                weighted_score=current_state.confidence_score,
            )

        # Parse citations from confidence_explanation (JSON column)
        raw_conf = pr.get("confidence_explanation", "{}")
        if isinstance(raw_conf, str):
            try:
                raw_conf = json.loads(raw_conf)
            except (json.JSONDecodeError, TypeError):
                raw_conf = {}
        raw_citations = raw_conf.get("citations", []) if isinstance(raw_conf, dict) else []
        citations = [
            Citation(
                page=c.get("page", 0),
                section=c.get("section"),
                text=c.get("text", ""),
                highlight_coords=c.get("highlight_coords"),
            )
            for c in (raw_citations or [])
            if c.get("field_name") == field_name or not c.get("field_name")
        ]

        # --- 5. Amendment chain from contracts_relationships ---
        amend_sql = f"""
        SELECT
          child_document_id AS document_id,
          relationship_type,
          CASE
            WHEN applicability_status = 'SUPERSEDED' THEN 'SUPERSEDED'
            WHEN expiration_date < current_date() THEN 'EXPIRED'
            WHEN effective_date > current_date() THEN 'FUTURE'
            ELSE 'ACTIVE'
          END AS status,
          CAST(effective_date AS STRING) AS effective_date
        FROM {cc}.contracts_relationships
        WHERE parent_document_id = :doc_id
           OR child_document_id = :doc_id
        ORDER BY effective_date ASC
        """
        amend_rows = await execute_sql(amend_sql, parameters={"doc_id": document_version_id})
        amendment_chain = [
            AmendmentLink(
                document_id=r["document_id"],
                relationship_type=r["relationship_type"],
                status=r["status"],
                effective_date=r.get("effective_date"),
            )
            for r in amend_rows
        ]

        return ProvenanceResult(
            current_state=current_state,
            review_actions=review_actions,
            extracted_value=extracted_value,
            confidence_explanation=confidence_explanation,
            citations=citations,
            source_file=source_file,
            amendment_chain=amendment_chain,
        )
