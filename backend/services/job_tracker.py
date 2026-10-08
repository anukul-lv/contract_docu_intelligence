"""Job event tracking service.

Writes events to ingestion_job_events and updates ingestion_jobs state.
Used by both the FastAPI app (job creation / submission) and the extraction
notebook (progress updates).
"""
import json
import logging
import uuid
from datetime import datetime, timezone

from backend.config import get_settings
from backend.dependencies import execute_sql

logger = logging.getLogger("healthcontracts")

# Valid event types
EVENT_TYPES = {
    "JOB_CREATED",
    "JOB_SUBMITTED",
    "JOB_PENDING",
    "JOB_STARTED",
    "BATCH_STARTED",
    "DOCUMENT_STARTED",
    "DOCUMENT_COMPLETED",
    "DOCUMENT_FAILED",
    "PHI_SCAN_COMPLETED",
    "CHUNKING_COMPLETED",
    "INDEX_SYNC_TRIGGERED",
    "JOB_COMPLETED",
    "JOB_COMPLETED_WITH_ERRORS",
    "JOB_FAILED",
    "JOB_CANCELLED",
}


class JobTracker:
    """Tracks extraction job lifecycle via events and state updates."""

    async def write_event(
        self,
        run_id: str,
        event_type: str,
        document_version_id: str | None = None,
        batch_id: str | None = None,
        payload: dict | None = None,
        created_by: str | None = None,
    ) -> str:
        """Append an event to ingestion_job_events. Returns event_id."""
        settings = get_settings()
        event_id = str(uuid.uuid4())
        event_ts = datetime.now(timezone.utc).isoformat()

        await execute_sql(
            f"INSERT INTO {settings.app_catalog}.{settings.app_schema}.ingestion_job_events "
            f"(event_id, run_id, event_ts, event_type, document_version_id, "
            f"batch_id, event_payload, created_by) VALUES ("
            f":event_id, :run_id, TIMESTAMP :event_ts, "
            f":event_type, :doc_version_id, "
            f":batch_id, :payload, :created_by)",
            parameters={
                "event_id": event_id,
                "run_id": run_id,
                "event_ts": event_ts,
                "event_type": event_type,
                "doc_version_id": document_version_id or "",
                "batch_id": batch_id or "",
                "payload": json.dumps(payload) if payload else "",
                "created_by": created_by or "",
            },
        )
        logger.debug("Event %s written for run %s", event_type, run_id)
        return event_id

    async def update_job_state(
        self,
        run_id: str,
        new_state: str,
        **extra_fields,
    ) -> None:
        """Update the state column (and optional extra fields) on ingestion_jobs."""
        settings = get_settings()
        set_parts = ["state = :new_state"]
        params: dict[str, str] = {"new_state": new_state, "run_id": run_id}

        field_map = {
            "databricks_run_id": "databricks_run_id",
            "started_at": "started_at",
            "completed_at": "completed_at",
            "completed_documents": "completed_documents",
            "failed_documents": "failed_documents",
            "error_summary": "error_summary",
            "actual_cost": "actual_cost",
        }

        for py_name, col_name in field_map.items():
            if py_name in extra_fields:
                val = extra_fields[py_name]
                param_key = f"ef_{py_name}"
                set_parts.append(f"{col_name} = :{param_key}")
                params[param_key] = str(val) if val is not None else ""

        sql = (
            f"UPDATE {settings.app_catalog}.{settings.app_schema}.ingestion_jobs "
            f"SET {', '.join(set_parts)} "
            f"WHERE run_id = :run_id"
        )
        await execute_sql(sql, parameters=params)

    async def get_job(self, run_id: str) -> dict | None:
        """Fetch a single ingestion job by run_id."""
        settings = get_settings()
        rows = await execute_sql(
            f"SELECT * FROM {settings.app_catalog}.{settings.app_schema}.ingestion_jobs "
            f"WHERE run_id = :run_id LIMIT 1",
            parameters={"run_id": run_id},
        )
        return rows[0] if rows else None

    async def get_events(
        self,
        run_id: str,
        after_event_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Fetch events for a run, optionally after a given event_id (for SSE replay)."""
        settings = get_settings()
        params: dict[str, str] = {"run_id": run_id}
        where = "WHERE run_id = :run_id"
        if after_event_id:
            params["after_event_id"] = after_event_id
            where += (
                f" AND event_ts > ("
                f"SELECT event_ts FROM {settings.app_catalog}.{settings.app_schema}.ingestion_job_events "
                f"WHERE event_id = :after_event_id)"
            )
        return await execute_sql(
            f"SELECT * FROM {settings.app_catalog}.{settings.app_schema}.ingestion_job_events "
            f"{where} ORDER BY event_ts ASC LIMIT {limit}",
            parameters=params,
        )


# Singleton
job_tracker = JobTracker()
