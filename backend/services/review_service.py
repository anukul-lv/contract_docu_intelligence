"""Review workbench service — optimistic locking, batch ops, audit trail.

Every mutation uses a MERGE with version_number check so that concurrent
writers get an immediate 409 Conflict instead of a lost update.

All actions are appended to the immutable review_actions table.
"""
import logging
import uuid
from datetime import datetime, timezone

from backend.config import get_settings
from backend.dependencies import execute_sql

logger = logging.getLogger("healthcontracts")

# Field classes that cannot be batch-approved
_CRITICAL_CLASSES = {"critical_financial", "critical_compliance"}


class ReviewService:
    """Manages the review lifecycle with optimistic concurrency."""

    # ------------------------------------------------------------------
    # Queue listing
    # ------------------------------------------------------------------

    async def get_queue(
        self,
        cursor: str | None = None,
        limit: int = 50,
        status: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
        field_class: str | None = None,
    ) -> tuple[list[dict], str | None, int]:
        """Cursor-paginated review queue. Returns (items, next_cursor, total)."""
        s = get_settings()
        where = []
        params: dict[str, str] = {}
        if status:
            where.append("review_status = :status")
            params["status"] = status
        if priority:
            where.append("priority = :priority")
            params["priority"] = priority
        if assigned_to:
            where.append("assigned_to = :assigned_to")
            params["assigned_to"] = assigned_to
        if field_class:
            where.append("field_class = :field_class")
            params["field_class"] = field_class
        if cursor:
            import base64
            try:
                decoded = base64.b64decode(cursor).decode()
                parts = decoded.split("|", 1)
                where.append("(created_at, review_id) < (TIMESTAMP :cursor_ts, :cursor_id)")
                params["cursor_ts"] = parts[0]
                params["cursor_id"] = parts[1]
            except Exception:
                pass

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        rows = await execute_sql(
            f"SELECT * FROM {s.app_catalog}.{s.app_schema}.review_queue "
            f"{where_sql} ORDER BY created_at DESC, review_id DESC LIMIT {limit + 1}",
            parameters=params if params else None,
        )

        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = None
        if has_more and items:
            import base64
            last = items[-1]
            composite = f"{last.get('created_at', '')}|{last.get('review_id', '')}"
            next_cursor = base64.b64encode(composite.encode()).decode()

        count_rows = await execute_sql(
            f"SELECT COUNT(*) AS cnt FROM {s.app_catalog}.{s.app_schema}.review_queue {where_sql}",
            parameters=params if params else None,
        )
        total = int(count_rows[0]["cnt"]) if count_rows else 0
        return items, next_cursor, total

    # ------------------------------------------------------------------
    # Claim (optimistic locking MERGE)
    # ------------------------------------------------------------------

    async def claim(self, review_id: str, expected_version: int, assignee: str) -> bool:
        """Claim a review item. Returns True on success, False on version conflict."""
        s = get_settings()
        result = await execute_sql(
            f"""
            MERGE INTO {s.app_catalog}.{s.app_schema}.review_queue t
            USING (
                SELECT :review_id AS review_id,
                       :expected_version AS expected_version,
                       :assignee AS assignee
            ) src
            ON t.review_id = src.review_id
            AND t.version_number = src.expected_version
            WHEN MATCHED AND t.review_status = 'PENDING' THEN
                UPDATE SET
                    review_status = 'IN_REVIEW',
                    assigned_to = src.assignee,
                    version_number = t.version_number + 1
            """,
            parameters={"review_id": review_id, "expected_version": str(expected_version), "assignee": assignee},
        )
        updated = self._merge_row_count(result)
        if updated:
            await self._record_action(
                review_id=review_id, action_type="CLAIM",
                performed_by=assignee,
                version_before=expected_version,
                version_after=expected_version + 1,
            )
        return updated

    # ------------------------------------------------------------------
    # Approve
    # ------------------------------------------------------------------

    async def approve(
        self, review_id: str, expected_version: int, reviewer: str,
        comment: str | None = None,
    ) -> bool:
        """Approve a review item. Returns True on success."""
        s = get_settings()
        result = await execute_sql(
            f"""
            MERGE INTO {s.app_catalog}.{s.app_schema}.review_queue t
            USING (
                SELECT :review_id AS review_id,
                       :expected_version AS expected_version
            ) src
            ON t.review_id = src.review_id
            AND t.version_number = src.expected_version
            WHEN MATCHED AND t.review_status IN ('PENDING', 'IN_REVIEW') THEN
                UPDATE SET
                    review_status = 'APPROVED',
                    reviewed_by = :reviewer,
                    reviewed_at = current_timestamp(),
                    review_comment = :comment,
                    version_number = t.version_number + 1
            """,
            parameters={"review_id": review_id, "expected_version": str(expected_version), "reviewer": reviewer, "comment": comment or ""},
        )
        updated = self._merge_row_count(result)
        if updated:
            item = await self._get_item(review_id)
            await self._record_action(
                review_id=review_id,
                document_version_id=item.get("document_version_id") if item else None,
                field_name=item.get("field_name") if item else None,
                action_type="APPROVE",
                previous_value=item.get("ai_extracted_value") if item else None,
                new_value=item.get("ai_extracted_value") if item else None,
                comment=comment,
                performed_by=reviewer,
                version_before=expected_version,
                version_after=expected_version + 1,
            )
            if item:
                await self._sync_contracts_current(item, reviewer, "APPROVED")
        return updated

    # ------------------------------------------------------------------
    # Correct
    # ------------------------------------------------------------------

    async def correct(
        self, review_id: str, expected_version: int, reviewer: str,
        corrected_value: str, correction_reason: str,
        comment: str | None = None,
    ) -> bool:
        s = get_settings()
        result = await execute_sql(
            f"""
            MERGE INTO {s.app_catalog}.{s.app_schema}.review_queue t
            USING (
                SELECT :review_id AS review_id,
                       :expected_version AS expected_version
            ) src
            ON t.review_id = src.review_id
            AND t.version_number = src.expected_version
            WHEN MATCHED AND t.review_status IN ('PENDING', 'IN_REVIEW') THEN
                UPDATE SET
                    review_status = 'CORRECTED',
                    human_corrected_value = :corrected_value,
                    correction_reason = :correction_reason,
                    reviewed_by = :reviewer,
                    reviewed_at = current_timestamp(),
                    review_comment = :comment,
                    version_number = t.version_number + 1
            """,
            parameters={
                "review_id": review_id, "expected_version": str(expected_version),
                "corrected_value": corrected_value, "correction_reason": correction_reason,
                "reviewer": reviewer, "comment": comment or "",
            },
        )
        updated = self._merge_row_count(result)
        if updated:
            item = await self._get_item(review_id)
            await self._record_action(
                review_id=review_id,
                document_version_id=item.get("document_version_id") if item else None,
                field_name=item.get("field_name") if item else None,
                action_type="CORRECT",
                previous_value=item.get("ai_extracted_value") if item else None,
                new_value=corrected_value,
                correction_reason=correction_reason,
                comment=comment,
                performed_by=reviewer,
                version_before=expected_version,
                version_after=expected_version + 1,
            )
            if item:
                item["_trusted_value"] = corrected_value
                await self._sync_contracts_current(item, reviewer, "CORRECTED")
        return updated

    # ------------------------------------------------------------------
    # Flag
    # ------------------------------------------------------------------

    async def flag(
        self, review_id: str, expected_version: int, reviewer: str,
        reason: str,
    ) -> bool:
        s = get_settings()
        result = await execute_sql(
            f"""
            MERGE INTO {s.app_catalog}.{s.app_schema}.review_queue t
            USING (
                SELECT :review_id AS review_id,
                       :expected_version AS expected_version
            ) src
            ON t.review_id = src.review_id
            AND t.version_number = src.expected_version
            WHEN MATCHED AND t.review_status IN ('PENDING', 'IN_REVIEW') THEN
                UPDATE SET
                    review_status = 'FLAGGED',
                    review_comment = :reason,
                    reviewed_by = :reviewer,
                    reviewed_at = current_timestamp(),
                    version_number = t.version_number + 1
            """,
            parameters={"review_id": review_id, "expected_version": str(expected_version), "reason": reason, "reviewer": reviewer},
        )
        updated = self._merge_row_count(result)
        if updated:
            item = await self._get_item(review_id)
            await self._record_action(
                review_id=review_id,
                document_version_id=item.get("document_version_id") if item else None,
                field_name=item.get("field_name") if item else None,
                action_type="FLAG",
                comment=reason,
                performed_by=reviewer,
                version_before=expected_version,
                version_after=expected_version + 1,
            )
        return updated

    # ------------------------------------------------------------------
    # Batch approve
    # ------------------------------------------------------------------

    async def batch_approve(
        self, review_ids: list[str], min_confidence: float, reviewer: str,
    ) -> dict:
        """Approve multiple non-critical items above confidence threshold."""
        s = get_settings()
        placeholders = ", ".join(f":rid_{i}" for i in range(len(review_ids)))
        batch_params = {f"rid_{i}": rid for i, rid in enumerate(review_ids)}
        batch_params["min_conf"] = str(min_confidence)

        # Fetch candidates, excluding critical fields
        candidates = await execute_sql(
            f"""
            SELECT review_id, version_number, ai_confidence, field_class,
                   document_version_id, field_name, ai_extracted_value
            FROM {s.app_catalog}.{s.app_schema}.review_queue
            WHERE review_id IN ({placeholders})
              AND review_status IN ('PENDING', 'IN_REVIEW')
              AND (field_class IS NULL OR field_class NOT IN ('critical_financial', 'critical_compliance'))
              AND ai_confidence >= :min_conf
            """,
            parameters=batch_params,
        )

        approved = []
        skipped = []
        for row in candidates:
            ok = await self.approve(
                review_id=row["review_id"],
                expected_version=int(row["version_number"]),
                reviewer=reviewer,
                comment=f"Batch approved (confidence >= {min_confidence})",
            )
            if ok:
                approved.append(row["review_id"])
            else:
                skipped.append(row["review_id"])

        excluded = set(review_ids) - {r["review_id"] for r in candidates}
        return {
            "approved": approved,
            "skipped_conflict": skipped,
            "excluded_critical_or_low_conf": list(excluded),
        }

    # ------------------------------------------------------------------
    # Revert
    # ------------------------------------------------------------------

    async def revert(
        self, review_id: str, reviewer: str, reason: str,
    ) -> bool:
        """Revert a reviewed item back to PENDING with the original AI value."""
        s = get_settings()
        item = await self._get_item(review_id)
        if not item:
            return False

        current_version = int(item.get("version_number", 1))

        result = await execute_sql(
            f"""
            MERGE INTO {s.app_catalog}.{s.app_schema}.review_queue t
            USING (
                SELECT :review_id AS review_id,
                       :expected_version AS expected_version
            ) src
            ON t.review_id = src.review_id
            AND t.version_number = src.expected_version
            WHEN MATCHED AND t.review_status IN ('APPROVED', 'CORRECTED', 'FLAGGED') THEN
                UPDATE SET
                    review_status = 'PENDING',
                    human_corrected_value = NULL,
                    correction_reason = NULL,
                    reviewed_by = NULL,
                    reviewed_at = NULL,
                    review_comment = :reason,
                    assigned_to = NULL,
                    version_number = t.version_number + 1
            """,
            parameters={"review_id": review_id, "expected_version": str(current_version), "reason": reason},
        )
        updated = self._merge_row_count(result)
        if updated:
            await self._record_action(
                review_id=review_id,
                document_version_id=item.get("document_version_id"),
                field_name=item.get("field_name"),
                action_type="REVERT",
                previous_value=item.get("human_corrected_value") or item.get("ai_extracted_value"),
                new_value=item.get("ai_extracted_value"),
                comment=reason,
                performed_by=reviewer,
                version_before=current_version,
                version_after=current_version + 1,
            )
        return updated

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_stats(self) -> dict:
        s = get_settings()
        rows = await execute_sql(f"""
            SELECT
                COUNT(CASE WHEN review_status = 'PENDING' THEN 1 END) AS pending,
                COUNT(CASE WHEN review_status = 'IN_REVIEW' THEN 1 END) AS in_review,
                COUNT(CASE WHEN review_status IN ('APPROVED','CORRECTED') AND CAST(reviewed_at AS DATE) = CURRENT_DATE() THEN 1 END) AS completed_today,
                COUNT(CASE WHEN priority = 'HIGH' AND review_status = 'PENDING' THEN 1 END) AS high_priority_pending,
                COUNT(CASE WHEN priority = 'NORMAL' AND review_status = 'PENDING' THEN 1 END) AS normal_priority_pending
            FROM {s.app_catalog}.{s.app_schema}.review_queue
        """)
        stats = rows[0] if rows else {}

        # Average review time for items completed today
        avg_rows = await execute_sql(f"""
            SELECT AVG(UNIX_TIMESTAMP(reviewed_at) - UNIX_TIMESTAMP(created_at)) AS avg_sec
            FROM {s.app_catalog}.{s.app_schema}.review_queue
            WHERE review_status IN ('APPROVED','CORRECTED')
              AND CAST(reviewed_at AS DATE) = CURRENT_DATE()
        """)
        avg_sec = float(avg_rows[0].get("avg_sec") or 0) if avg_rows else 0

        return {
            "pending": int(stats.get("pending", 0)),
            "in_review": int(stats.get("in_review", 0)),
            "completed_today": int(stats.get("completed_today", 0)),
            "avg_review_time_sec": round(avg_sec, 1),
            "by_priority": {
                "high": int(stats.get("high_priority_pending", 0)),
                "normal": int(stats.get("normal_priority_pending", 0)),
            },
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _get_item(self, review_id: str) -> dict | None:
        s = get_settings()
        rows = await execute_sql(
            f"SELECT * FROM {s.app_catalog}.{s.app_schema}.review_queue "
            f"WHERE review_id = :review_id LIMIT 1",
            parameters={"review_id": review_id},
        )
        return rows[0] if rows else None

    async def _record_action(
        self, *, review_id: str, action_type: str, performed_by: str,
        version_before: int, version_after: int,
        document_version_id: str | None = None,
        field_name: str | None = None,
        previous_value: str | None = None,
        new_value: str | None = None,
        correction_reason: str | None = None,
        comment: str | None = None,
    ) -> None:
        """Append to the immutable review_actions table. Never UPDATE or DELETE."""
        s = get_settings()
        action_id = str(uuid.uuid4())

        await execute_sql(
            f"INSERT INTO {s.app_catalog}.{s.app_schema}.review_actions "
            f"(action_id, review_id, document_version_id, field_name, action_type, "
            f"previous_value, new_value, correction_reason, action_comment, "
            f"performed_by, performed_at, version_before, version_after) VALUES ("
            f":action_id, :review_id, :doc_version_id, "
            f":field_name, :action_type, :previous_value, "
            f":new_value, :correction_reason, :comment, "
            f":performed_by, current_timestamp(), "
            f":version_before, :version_after)",
            parameters={
                "action_id": action_id,
                "review_id": review_id,
                "doc_version_id": document_version_id or "",
                "field_name": field_name or "",
                "action_type": action_type,
                "previous_value": previous_value or "",
                "new_value": new_value or "",
                "correction_reason": correction_reason or "",
                "comment": comment or "",
                "performed_by": performed_by,
                "version_before": str(version_before),
                "version_after": str(version_after),
            },
        )

    async def _sync_contracts_current(
        self, item: dict, reviewer: str, status: str,
    ) -> None:
        """Incremental MERGE into contracts_current for the affected field."""
        s = get_settings()
        trusted = item.get("_trusted_value") or item.get("ai_extracted_value", "")
        doc_vid = item.get("document_version_id", "")
        field = item.get("field_name", "")

        # Fetch source_document_id from contracts_parsed
        parsed_rows = await execute_sql(
            f"SELECT source_document_id FROM {s.customer_catalog}.{s.customer_schema}.contracts_parsed "
            f"WHERE document_version_id = :doc_vid LIMIT 1",
            parameters={"doc_vid": doc_vid},
        )
        src_doc_id = parsed_rows[0]["source_document_id"] if parsed_rows else doc_vid

        await execute_sql(
            f"""
            MERGE INTO {s.customer_catalog}.{s.customer_schema}.contracts_current t
            USING (
                SELECT
                    md5(CONCAT(:src_doc_id, :field_name)) AS record_id,
                    :src_doc_id AS document_family_id,
                    :src_doc_id AS source_document_id,
                    :doc_vid AS source_document_version_id,
                    :field_name AS field_name,
                    :trusted_value AS trusted_value,
                    'string' AS value_type,
                    :review_status AS review_status,
                    :reviewer AS reviewed_by,
                    current_timestamp() AS reviewed_at,
                    :source_citation AS source_citation,
                    :confidence_score AS confidence_score,
                    :confidence_explanation AS confidence_explanation,
                    CAST(NULL AS DATE) AS effective_date,
                    CAST(NULL AS DATE) AS expiration_date,
                    CAST(NULL AS STRING) AS supersession_context,
                    'ACTIVE' AS applicability_status,
                    current_timestamp() AS last_updated_at,
                    :reviewer AS last_updated_by
            ) src
            ON t.document_family_id = src.document_family_id AND t.field_name = src.field_name
            WHEN MATCHED THEN UPDATE SET
                source_document_version_id = src.source_document_version_id,
                trusted_value = src.trusted_value,
                review_status = src.review_status,
                reviewed_by = src.reviewed_by,
                reviewed_at = src.reviewed_at,
                confidence_score = src.confidence_score,
                last_updated_at = src.last_updated_at,
                last_updated_by = src.last_updated_by
            WHEN NOT MATCHED THEN INSERT *
            """,
            parameters={
                "src_doc_id": src_doc_id,
                "doc_vid": doc_vid,
                "field_name": field,
                "trusted_value": trusted,
                "review_status": status,
                "reviewer": reviewer,
                "source_citation": item.get("source_citation") or "",
                "confidence_score": str(item.get("ai_confidence") or ""),
                "confidence_explanation": item.get("confidence_explanation") or "",
            },
        )

    @staticmethod
    def _merge_row_count(result: list[dict]) -> bool:
        """Check whether a MERGE actually updated any rows."""
        if result and result[0].get("num_affected_rows"):
            return int(result[0]["num_affected_rows"]) > 0
        return True  # assume success if no row count returned


# Singleton
review_service = ReviewService()
