"""HIPAA-compliant audit logging service.

Append-only logger that writes every API action and PHI access event
to the hipaa_audit_log Delta table. Never UPDATE or DELETE.
"""
import json
import logging
import uuid
from datetime import datetime, timezone

from backend.config import get_settings
from backend.dependencies import execute_sql

logger = logging.getLogger("healthcontracts")


class HIPAAAuditService:
    """Append-only audit logger for every API action and PHI access."""

    async def log_event(
        self,
        event_type: str,
        user_identity: str,
        user_role: str,
        resource_type: str,
        resource_id: str,
        action: str,
        phi_accessed: bool = False,
        phi_fields_accessed: list[str] | None = None,
        source_ip: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        details: dict | None = None,
        outcome: str = "SUCCESS",
    ) -> None:
        """INSERT a single audit event into hipaa_audit_log. Never UPDATE or DELETE.

        Uses parameterized queries to prevent SQL injection.
        """
        settings = get_settings()
        event_id = str(uuid.uuid4())
        event_timestamp = datetime.now(timezone.utc).isoformat()

        # For phi_fields_accessed (ARRAY type) and details (STRING/JSON),
        # we pass them as string params and use SQL casting
        phi_fields_str = ""
        if phi_fields_accessed:
            phi_fields_str = json.dumps(phi_fields_accessed)

        details_str = ""
        if details:
            details_str = json.dumps(details)

        sql = f"""
        INSERT INTO {settings.app_catalog}.{settings.app_schema}.hipaa_audit_log
        (event_id, event_timestamp, event_type, user_identity, user_role,
         resource_type, resource_id, action, phi_accessed,
         phi_fields_accessed,
         source_ip, session_id, request_id, details, outcome)
        VALUES (
            :event_id,
            CAST(:event_ts AS TIMESTAMP),
            :event_type,
            :user_identity,
            :user_role,
            :resource_type,
            :resource_id,
            :action,
            CAST(:phi_accessed AS BOOLEAN),
            CASE WHEN :phi_fields = '' THEN NULL
                 ELSE from_json(:phi_fields, 'ARRAY<STRING>') END,
            :source_ip,
            :session_id,
            :request_id,
            :details,
            :outcome
        )
        """
        params = {
            "event_id": event_id,
            "event_ts": event_timestamp,
            "event_type": event_type,
            "user_identity": user_identity,
            "user_role": user_role,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "action": action,
            "phi_accessed": str(phi_accessed).lower(),
            "phi_fields": phi_fields_str,
            "source_ip": source_ip or "",
            "session_id": session_id or "",
            "request_id": request_id or "",
            "details": details_str,
            "outcome": outcome,
        }
        try:
            await execute_sql(sql, parameters=params)
        except Exception as exc:
            # Audit logging failures must never crash the request — log and continue
            logger.error(
                "HIPAA audit log write failed: %s (event_type=%s, user=%s)",
                exc,
                event_type,
                user_identity,
            )


# Singleton instance
audit_service = HIPAAAuditService()
