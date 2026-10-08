"""Contract explorer service — queries contracts_current with filtering and pagination.

Powers the Explorer page: card list, filter panel, detail view with
trust badges, and the distinct-values dropdowns.
"""
import base64
import json
import logging
from datetime import date, datetime, timezone

from backend.config import get_settings
from backend.dependencies import execute_sql

logger = logging.getLogger("healthcontracts")


class ExplorerService:
    """Read-only queries against contracts_current and contracts_parsed."""

    # ------------------------------------------------------------------
    # Contract listing (card list)
    # ------------------------------------------------------------------

    async def list_contracts(
        self,
        cursor: str | None = None,
        limit: int = 25,
        contract_type: str | None = None,
        state: str | None = None,
        status: str | None = None,
        reimbursement_method: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
    ) -> tuple[list[dict], str | None, int]:
        """Return contract summaries grouped by document_family_id.

        Returns (items, next_cursor, total_count).
        """
        s = get_settings()
        tbl = f"{s.customer_catalog}.{s.customer_schema}.contracts_current"

        where = ["applicability_status = 'ACTIVE'"]
        # Note: these filter conditions are applied post-aggregation via
        # helper methods that build parameterized WHERE fragments.
        # See _type_filter, _state_filter, _reimb_filter, _conf_filter below.

        # Build parameterized filter fragments
        query_params: dict[str, str] = {}

        date_filter = ""
        if date_from:
            date_filter += " AND (eff.trusted_value >= :date_from OR exp.trusted_value >= :date_from)"
            query_params["date_from"] = date_from
        if date_to:
            date_filter += " AND (eff.trusted_value <= :date_to OR exp.trusted_value <= :date_to)"
            query_params["date_to"] = date_to

        cursor_filter = ""
        if cursor:
            try:
                decoded = base64.b64decode(cursor).decode()
                cursor_filter = "HAVING MIN(c.last_updated_at) < TIMESTAMP :cursor_ts"
                query_params["cursor_ts"] = decoded
            except Exception:
                pass

        # Main contract summary query
        sql = f"""
            WITH base AS (
                SELECT document_family_id, field_name, trusted_value,
                       confidence_score, review_status, last_updated_at
                FROM {tbl}
                WHERE applicability_status = 'ACTIVE'
            ),
            summaries AS (
                SELECT
                    c.document_family_id,
                    MAX(CASE WHEN c.field_name = 'contract_type' THEN c.trusted_value END) AS contract_type,
                    MAX(CASE WHEN c.field_name = 'state_jurisdiction' THEN c.trusted_value END) AS state_jurisdiction,
                    MAX(CASE WHEN c.field_name = 'effective_date' THEN c.trusted_value END) AS effective_date,
                    MAX(CASE WHEN c.field_name = 'expiration_date' THEN c.trusted_value END) AS expiration_date,
                    MAX(CASE WHEN c.field_name = 'reimbursement_method' THEN c.trusted_value END) AS reimbursement_method,
                    MAX(CASE WHEN c.field_name = 'parties' THEN c.trusted_value END) AS parties,
                    MAX(CASE WHEN c.field_name = 'governing_law' THEN c.trusted_value END) AS governing_law,
                    AVG(c.confidence_score) AS avg_confidence,
                    COUNT(*) AS field_count,
                    COUNT(CASE WHEN c.review_status = 'APPROVED' THEN 1 END) AS approved_fields,
                    COUNT(CASE WHEN c.review_status = 'CORRECTED' THEN 1 END) AS corrected_fields,
                    COUNT(CASE WHEN c.review_status = 'FLAGGED' THEN 1 END) AS flagged_fields,
                    MIN(c.last_updated_at) AS oldest_update
                FROM base c
                GROUP BY c.document_family_id
                {cursor_filter}
            )
            SELECT s.*,
                CASE
                    WHEN s.effective_date <= CURRENT_DATE()
                         AND (s.expiration_date IS NULL OR s.expiration_date >= CURRENT_DATE())
                    THEN 'Active'
                    WHEN s.expiration_date < CURRENT_DATE() THEN 'Expired'
                    WHEN s.effective_date > CURRENT_DATE() THEN 'Pending'
                    ELSE 'Unknown'
                END AS computed_status
            FROM summaries s
            WHERE 1=1
                {self._type_filter(contract_type, query_params)}
                {self._state_filter(state, query_params)}
                {self._reimb_filter(reimbursement_method, query_params)}
                {self._conf_filter(min_confidence, max_confidence)}
            ORDER BY s.oldest_update DESC
            LIMIT {limit + 1}
        """

        rows = await execute_sql(sql, parameters=query_params if query_params else None)

        # Apply status filter in Python (computed from dates)
        if status and status != "All":
            rows = [r for r in rows if r.get("computed_status") == status]

        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = None
        if has_more and items:
            last_ts = str(items[-1].get("oldest_update", ""))
            next_cursor = base64.b64encode(last_ts.encode()).decode()

        # Get total count
        count_rows = await execute_sql(
            f"SELECT COUNT(DISTINCT document_family_id) AS cnt FROM {tbl} "
            f"WHERE applicability_status = 'ACTIVE'"
        )
        total = int(count_rows[0]["cnt"]) if count_rows else 0

        return items, next_cursor, total

    # ------------------------------------------------------------------
    # Contract detail (all fields for one document)
    # ------------------------------------------------------------------

    async def get_contract_detail(self, document_family_id: str) -> dict | None:
        """Return all fields for a contract with trust/review metadata."""
        s = get_settings()
        rows = await execute_sql(
            f"""
            SELECT
                cc.record_id, cc.document_family_id, cc.field_name, cc.trusted_value,
                cc.value_type, cc.review_status, cc.reviewed_by, cc.reviewed_at,
                cc.source_citation, cc.confidence_score, cc.confidence_explanation,
                cc.effective_date, cc.expiration_date, cc.applicability_status,
                cc.last_updated_at
            FROM {s.customer_catalog}.{s.customer_schema}.contracts_current cc
            WHERE cc.document_family_id = :family_id
            ORDER BY cc.field_name
            """,
            parameters={"family_id": document_family_id},
        )
        if not rows:
            return None

        # Group fields by class
        financial_fields = []
        compliance_fields = []
        structural_fields = []
        metadata_fields = []

        for row in rows:
            fn = row.get("field_name", "")
            field_class = _classify_field(fn)
            row["field_class"] = field_class
            row["trust_badge"] = _compute_trust_badge(row)

            if field_class == "critical_financial":
                financial_fields.append(row)
            elif field_class == "critical_compliance":
                compliance_fields.append(row)
            elif field_class == "important_structural":
                structural_fields.append(row)
            else:
                metadata_fields.append(row)

        # Get source document info
        first_row = rows[0]
        doc_vid = first_row.get("source_document_version_id") or ""
        source_info = None
        if doc_vid:
            src_rows = await execute_sql(
                f"""
                SELECT file_name, file_path, file_type, page_count, extraction_profile
                FROM {s.customer_catalog}.{s.customer_schema}.contracts_parsed
                WHERE source_document_id = :family_id
                ORDER BY extraction_ts DESC LIMIT 1
                """,
                parameters={"family_id": document_family_id},
            )
            source_info = src_rows[0] if src_rows else None

        return {
            "document_family_id": document_family_id,
            "total_fields": len(rows),
            "source_document": source_info,
            "field_groups": {
                "financial": financial_fields,
                "compliance": compliance_fields,
                "structural": structural_fields,
                "metadata": metadata_fields,
            },
            "summary": {
                "avg_confidence": round(sum(r.get("confidence_score") or 0 for r in rows) / max(len(rows), 1), 3),
                "approved": sum(1 for r in rows if r.get("review_status") == "APPROVED"),
                "corrected": sum(1 for r in rows if r.get("review_status") == "CORRECTED"),
                "flagged": sum(1 for r in rows if r.get("review_status") == "FLAGGED"),
                "pending_review": sum(1 for r in rows if r.get("review_status") in ("PENDING", "IN_REVIEW", None)),
            },
        }

    # ------------------------------------------------------------------
    # Filter dropdown values
    # ------------------------------------------------------------------

    async def get_filter_values(self) -> dict:
        """Return distinct values for all filter dropdowns."""
        s = get_settings()
        tbl = f"{s.customer_catalog}.{s.customer_schema}.contracts_current"

        contract_types = await execute_sql(
            f"SELECT DISTINCT trusted_value AS v FROM {tbl} "
            f"WHERE field_name = 'contract_type' AND trusted_value IS NOT NULL ORDER BY v"
        )
        states = await execute_sql(
            f"SELECT DISTINCT trusted_value AS v FROM {tbl} "
            f"WHERE field_name = 'state_jurisdiction' AND trusted_value IS NOT NULL ORDER BY v"
        )
        reimb = await execute_sql(
            f"SELECT DISTINCT trusted_value AS v FROM {tbl} "
            f"WHERE field_name = 'reimbursement_method' AND trusted_value IS NOT NULL ORDER BY v"
        )

        return {
            "contract_types": [r["v"] for r in contract_types],
            "states": [r["v"] for r in states],
            "statuses": ["Active", "Expired", "Pending", "All"],
            "reimbursement_methods": [r["v"] for r in reimb],
        }

    # ------------------------------------------------------------------
    # Dashboard aggregations (for the Lakeview dashboard queries)
    # ------------------------------------------------------------------

    async def get_dashboard_data(self) -> dict:
        """Pre-aggregated data for all 5 dashboard widgets."""
        s = get_settings()
        tbl = f"{s.customer_catalog}.{s.customer_schema}.contracts_current"

        by_type = await execute_sql(
            f"SELECT trusted_value AS contract_type, COUNT(DISTINCT document_family_id) AS cnt "
            f"FROM {tbl} WHERE field_name = 'contract_type' AND trusted_value IS NOT NULL "
            f"GROUP BY trusted_value ORDER BY cnt DESC"
        )
        by_state = await execute_sql(
            f"SELECT trusted_value AS state, COUNT(DISTINCT document_family_id) AS cnt "
            f"FROM {tbl} WHERE field_name = 'state_jurisdiction' AND trusted_value IS NOT NULL "
            f"GROUP BY trusted_value ORDER BY cnt DESC"
        )
        by_reimb = await execute_sql(
            f"SELECT trusted_value AS method, COUNT(DISTINCT document_family_id) AS cnt "
            f"FROM {tbl} WHERE field_name = 'reimbursement_method' AND trusted_value IS NOT NULL "
            f"GROUP BY trusted_value ORDER BY cnt DESC"
        )
        expiring = await execute_sql(
            f"SELECT trusted_value AS expiration_date, COUNT(DISTINCT document_family_id) AS cnt "
            f"FROM {tbl} WHERE field_name = 'expiration_date' AND trusted_value IS NOT NULL "
            f"AND trusted_value BETWEEN CURRENT_DATE() AND DATE_ADD(CURRENT_DATE(), 180) "
            f"GROUP BY trusted_value ORDER BY trusted_value"
        )

        return {
            "by_type": by_type,
            "by_state": by_state,
            "by_reimbursement": by_reimb,
            "expiring_180d": expiring,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _type_filter(v: str | None, params: dict[str, str]) -> str:
        if v:
            params["filter_contract_type"] = v
            return "AND s.contract_type = :filter_contract_type"
        return ""

    @staticmethod
    def _state_filter(v: str | None, params: dict[str, str]) -> str:
        if v:
            params["filter_state"] = v
            return "AND s.state_jurisdiction = :filter_state"
        return ""

    @staticmethod
    def _reimb_filter(v: str | None, params: dict[str, str]) -> str:
        if v:
            params["filter_reimb"] = v
            return "AND s.reimbursement_method = :filter_reimb"
        return ""

    @staticmethod
    def _conf_filter(lo: float | None, hi: float | None) -> str:
        parts = []
        if lo is not None:
            parts.append(f"s.avg_confidence >= {lo}")
        if hi is not None:
            parts.append(f"s.avg_confidence <= {hi}")
        return ("AND " + " AND ".join(parts)) if parts else ""


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

_FINANCIAL_FIELDS = {
    "reimbursement_method", "fee_schedule", "drg_terms", "per_diem_rates",
    "capitation_rates", "stop_loss_terms", "shared_savings",
}
_COMPLIANCE_FIELDS = {
    "baa_terms", "regulatory_tags", "cms_regulatory_refs",
    "cms_contract_id", "mlr_terms", "risk_adjustment",
}
_STRUCTURAL_FIELDS = {
    "effective_date", "expiration_date", "term_months", "parties",
    "auto_renewal", "termination_notice_days", "governing_law",
    "state_jurisdiction", "contract_type",
}


def _classify_field(field_name: str) -> str:
    if field_name in _FINANCIAL_FIELDS:
        return "critical_financial"
    if field_name in _COMPLIANCE_FIELDS:
        return "critical_compliance"
    if field_name in _STRUCTURAL_FIELDS:
        return "important_structural"
    return "low_risk_metadata"


def _compute_trust_badge(row: dict) -> str:
    """Determine the trust badge type for a field row."""
    status = row.get("review_status")
    conf = row.get("confidence_score")

    if status == "APPROVED":
        return "VERIFIED"
    if status == "CORRECTED":
        return "CORRECTED"
    if status == "FLAGGED":
        return "FLAGGED"
    if conf is not None and conf < 0.70:
        return "LOW_CONFIDENCE"
    return "AI_EXTRACTED"


# _esc() removed — all queries now use parameterized :param syntax


# Singleton
explorer_service = ExplorerService()
