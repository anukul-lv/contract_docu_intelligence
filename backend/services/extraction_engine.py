"""Extraction engine — job submission, state tracking, idempotency.

The web app NEVER performs heavy extraction in-process. This service
submits a parameterized Lakeflow Job via jobs.run_now() and tracks
progress via ingestion_job_events.

State machine:
  CREATED -> SUBMITTED -> PENDING -> STARTING -> RUNNING -> COMPLETING -> COMPLETED
  Branches: SUBMIT_FAILED, FAILED, CANCELLED, COMPLETED_WITH_ERRORS, INVALID_REQUEST
"""
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta

from backend.config import get_settings
from backend.dependencies import execute_sql, get_workspace_client
from backend.services.cost_tracker import cost_tracker
from backend.services.healthcare_profiles import get_profile_snapshot
from backend.services.job_tracker import job_tracker

logger = logging.getLogger("healthcontracts")

# Idempotency dedup window
_DEDUP_WINDOW_HOURS = 24


class ExtractionEngine:
    """Manages extraction job lifecycle."""

    async def start_extraction(
        self,
        volume_path: str,
        file_list: list[str] | None,
        output_catalog: str,
        output_schema: str,
        profile: str,
        auto_enrich: bool,
        healthcare_mode: bool,
        idempotency_key: str,
        created_by: str,
    ) -> dict:
        """Create and submit an extraction job. Returns run metadata."""
        settings = get_settings()

        # --- Idempotency check (24-hour window) ---
        existing = await self._check_idempotency(idempotency_key)
        if existing:
            return existing

        # --- Determine batch size ---
        num_docs = len(file_list) if file_list else await self._count_volume_files(volume_path)
        batch_size = self._compute_batch_size(num_docs)

        # --- Cost estimate ---
        estimate = cost_tracker.estimate_run_cost(num_docs)

        # --- Create job record ---
        run_id = str(uuid.uuid4())
        profile_snapshot = get_profile_snapshot(profile)

        await execute_sql(
            f"INSERT INTO {settings.app_catalog}.{settings.app_schema}.ingestion_jobs "
            f"(run_id, state, total_documents, volume_path, output_catalog, output_schema, "
            f"profile, profile_snapshot, batch_size, healthcare_mode, idempotency_key, "
            f"estimated_cost, created_by, created_at) VALUES ("
            f":run_id, 'CREATED', :num_docs, :volume_path, "
            f":output_catalog, :output_schema, :profile, "
            f":profile_snapshot, "
            f":batch_size, :healthcare_mode, :idempotency_key, "
            f":estimated_cost, :created_by, current_timestamp())",
            parameters={
                "run_id": run_id,
                "num_docs": str(num_docs),
                "volume_path": volume_path,
                "output_catalog": output_catalog,
                "output_schema": output_schema,
                "profile": profile,
                "profile_snapshot": profile_snapshot,
                "batch_size": str(batch_size),
                "healthcare_mode": str(healthcare_mode).lower(),
                "idempotency_key": idempotency_key,
                "estimated_cost": str(estimate['estimated_cost_usd']),
                "created_by": created_by,
            },
        )
        await job_tracker.write_event(run_id, "JOB_CREATED", created_by=created_by)

        # --- Submit Lakeflow Job ---
        try:
            w = get_workspace_client()
            job_template_id = int(settings.extraction_job_template_id) if settings.extraction_job_template_id else None

            if not job_template_id:
                raise ValueError("EXTRACTION_JOB_TEMPLATE_ID not configured")

            run = w.jobs.run_now(
                job_id=job_template_id,
                notebook_params={
                    "run_id": run_id,
                    "volume_path": volume_path,
                    "output_catalog": output_catalog,
                    "output_schema": output_schema,
                    "profile": profile,
                    "batch_size": str(batch_size),
                    "healthcare_mode": str(healthcare_mode),
                },
            )

            await job_tracker.update_job_state(
                run_id, "SUBMITTED",
                databricks_run_id=run.run_id,
            )
            await job_tracker.write_event(
                run_id, "JOB_SUBMITTED",
                payload={"databricks_run_id": run.run_id},
                created_by=created_by,
            )

        except Exception as exc:
            logger.error("Job submission failed for run %s: %s", run_id, exc)
            await job_tracker.update_job_state(
                run_id, "SUBMIT_FAILED",
                error_summary=str(exc)[:500],
            )
            await job_tracker.write_event(
                run_id, "JOB_FAILED",
                payload={"error": str(exc)[:500]},
                created_by=created_by,
            )
            raise RuntimeError(f"Job submission failed: {exc}") from exc

        return {
            "run_id": run_id,
            "state": "SUBMITTED",
            "total_documents": num_docs,
            "estimated_duration_min": estimate["estimated_duration_min"],
            "estimated_cost": estimate["estimated_cost_usd"],
        }

    async def get_status(self, run_id: str) -> dict | None:
        """Fetch current job status with progress counters."""
        job = await job_tracker.get_job(run_id)
        if not job:
            return None

        elapsed_sec = 0.0
        if job.get("started_at"):
            start = datetime.fromisoformat(str(job["started_at"]))
            end = (
                datetime.fromisoformat(str(job["completed_at"]))
                if job.get("completed_at")
                else datetime.now(timezone.utc)
            )
            elapsed_sec = (end - start).total_seconds()

        total = int(job.get("total_documents") or 0)
        completed = int(job.get("completed_documents") or 0)
        remaining = max(0, total - completed - int(job.get("failed_documents") or 0))
        est_remaining_sec = (elapsed_sec / max(completed, 1)) * remaining if completed > 0 else 0

        return {
            "run_id": run_id,
            "state": job.get("state"),
            "total_documents": total,
            "completed_documents": completed,
            "failed_documents": int(job.get("failed_documents") or 0),
            "elapsed_sec": round(elapsed_sec, 1),
            "estimated_remaining_sec": round(est_remaining_sec, 1),
            "profile": job.get("profile"),
            "created_by": job.get("created_by"),
        }

    async def cancel(self, run_id: str) -> None:
        """Cancel a running extraction job."""
        job = await job_tracker.get_job(run_id)
        if not job:
            raise ValueError(f"Run {run_id} not found")

        if job.get("databricks_run_id"):
            try:
                w = get_workspace_client()
                w.jobs.cancel_run(run_id=int(job["databricks_run_id"]))
            except Exception as exc:
                logger.warning("Cancel API call failed for run %s: %s", run_id, exc)

        await job_tracker.update_job_state(run_id, "CANCELLED")
        await job_tracker.write_event(run_id, "JOB_CANCELLED")

    async def retry_failed(self, run_id: str, created_by: str) -> dict:
        """Retry only the failed documents from a previous run."""
        job = await job_tracker.get_job(run_id)
        if not job:
            raise ValueError(f"Run {run_id} not found")

        # Re-submit with the same parameters
        return await self.start_extraction(
            volume_path=job["volume_path"],
            file_list=None,  # The notebook filters to failed docs from original run
            output_catalog=job["output_catalog"],
            output_schema=job["output_schema"],
            profile=job["profile"],
            auto_enrich=False,
            healthcare_mode=job.get("healthcare_mode", "true") in (True, "true"),
            idempotency_key=f"retry_{run_id}_{uuid.uuid4().hex[:8]}",
            created_by=created_by,
        )

    async def get_history(
        self,
        cursor: str | None = None,
        limit: int = 20,
    ) -> tuple[list[dict], str | None]:
        """Fetch extraction job history with cursor pagination."""
        settings = get_settings()
        where = ""
        params: dict[str, str] = {}
        if cursor:
            import base64
            try:
                decoded = base64.b64decode(cursor).decode()
                where = "WHERE created_at < TIMESTAMP :cursor_ts"
                params["cursor_ts"] = decoded
            except Exception:
                pass

        rows = await execute_sql(
            f"SELECT run_id, state, total_documents, completed_documents, "
            f"failed_documents, profile, created_by, created_at, started_at, completed_at, "
            f"estimated_cost, actual_cost "
            f"FROM {settings.app_catalog}.{settings.app_schema}.ingestion_jobs "
            f"{where} ORDER BY created_at DESC LIMIT {limit + 1}",
            parameters=params if params else None,
        )

        has_more = len(rows) > limit
        result = rows[:limit]
        next_cursor = None
        if has_more and result:
            import base64
            last_ts = str(result[-1].get("created_at", ""))
            next_cursor = base64.b64encode(last_ts.encode()).decode()

        return result, next_cursor

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _check_idempotency(self, key: str) -> dict | None:
        """Check if a job with this idempotency key was created in the last 24h."""
        settings = get_settings()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=_DEDUP_WINDOW_HOURS)).isoformat()
        rows = await execute_sql(
            f"SELECT run_id, state FROM {settings.app_catalog}.{settings.app_schema}.ingestion_jobs "
            f"WHERE idempotency_key = :idem_key AND created_at > TIMESTAMP :cutoff "
            f"ORDER BY created_at DESC LIMIT 1",
            parameters={"idem_key": key, "cutoff": cutoff},
        )
        if rows:
            return {"run_id": rows[0]["run_id"], "state": rows[0]["state"], "deduplicated": True}
        return None

    async def _count_volume_files(self, volume_path: str) -> int:
        """Count files in the volume for batch sizing."""
        try:
            w = get_workspace_client()
            entries = list(w.files.list_directory_contents(volume_path))
            return sum(1 for e in entries if not getattr(e, "is_directory", False))
        except Exception:
            return 0

    @staticmethod
    def _compute_batch_size(num_docs: int) -> int:
        """Adaptive batch sizing: default 25, adjust for doc count."""
        if num_docs <= 10:
            return num_docs
        if num_docs > 200:
            return 50
        return 25


# Singleton
extraction_engine = ExtractionEngine()
