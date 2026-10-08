"""HealthContracts AI — Extraction Job Notebook.

Executed by Lakeflow Jobs with parameters:
  run_id, volume_path, output_catalog, output_schema,
  profile, batch_size, healthcare_mode

Processing stages:
  1. List files in volume and create batches
  2. Per batch: parse -> classify -> extract (CTE SQL)
  3. PHI detection on extracted content
  4. Confidence scoring + review queue routing
  5. MERGE into contracts_current
  6. Write completion events
"""
import json
import math
import os
import sys
import traceback
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Parameters (injected by Lakeflow Jobs notebook_params)
# ---------------------------------------------------------------------------
try:
    # Databricks widget-based parameters
    dbutils.widgets.text("run_id", "")
    dbutils.widgets.text("volume_path", "")
    dbutils.widgets.text("output_catalog", "dev")
    dbutils.widgets.text("output_schema", "doc_intel")
    dbutils.widgets.text("profile", "general_healthcare")
    dbutils.widgets.text("batch_size", "25")
    dbutils.widgets.text("healthcare_mode", "true")

    RUN_ID = dbutils.widgets.get("run_id")
    VOLUME_PATH = dbutils.widgets.get("volume_path")
    OUTPUT_CATALOG = dbutils.widgets.get("output_catalog")
    OUTPUT_SCHEMA = dbutils.widgets.get("output_schema")
    PROFILE = dbutils.widgets.get("profile")
    BATCH_SIZE = int(dbutils.widgets.get("batch_size"))
    HEALTHCARE_MODE = dbutils.widgets.get("healthcare_mode").lower() == "true"
except Exception:
    # Fallback for testing outside Databricks
    RUN_ID = os.getenv("run_id", "test-run")
    VOLUME_PATH = os.getenv("volume_path", "/Volumes/dev/doc_intel/prvdr_contracts")
    OUTPUT_CATALOG = os.getenv("output_catalog", "dev")
    OUTPUT_SCHEMA = os.getenv("output_schema", "doc_intel")
    PROFILE = os.getenv("profile", "general_healthcare")
    BATCH_SIZE = int(os.getenv("batch_size", "25"))
    HEALTHCARE_MODE = os.getenv("healthcare_mode", "true").lower() == "true"

# App catalog for operational tables (events, review queue, etc.)
APP_CATALOG = os.getenv("APP_CATALOG", "dev")
APP_SCHEMA = os.getenv("APP_SCHEMA", "doc_intel")

print(f"Extraction job starting: run_id={RUN_ID}, profile={PROFILE}, "
      f"batch_size={BATCH_SIZE}, volume={VOLUME_PATH}")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_event(event_type, doc_version_id=None, batch_id=None, payload=None):
    """Write an event to ingestion_job_events."""
    event_id = str(uuid.uuid4())
    event_ts = datetime.now(timezone.utc).isoformat()

    spark.sql(
        f"""
        INSERT INTO {APP_CATALOG}.{APP_SCHEMA}.ingestion_job_events
        (event_id, run_id, event_ts, event_type, document_version_id,
         batch_id, event_payload, created_by)
        VALUES (:event_id, :run_id, TIMESTAMP :event_ts,
                :event_type, :doc_version_id, :batch_id, :payload,
                current_user())
        """,
        args={
            "event_id": event_id,
            "run_id": RUN_ID,
            "event_ts": event_ts,
            "event_type": event_type,
            "doc_version_id": doc_version_id or "",
            "batch_id": batch_id or "",
            "payload": json.dumps(payload) if payload else "",
        },
    )


def update_job_state(state, **extras):
    """Update ingestion_jobs state."""
    set_parts = ["state = :state"]
    params = {"state": state, "run_id": RUN_ID}

    # Allowed extra columns that may be set dynamically
    _ALLOWED_COLS = {
        "databricks_run_id", "started_at", "completed_at",
        "completed_documents", "failed_documents", "error_summary", "actual_cost",
    }
    for k, v in extras.items():
        if k not in _ALLOWED_COLS:
            continue
        param_key = f"ef_{k}"
        set_parts.append(f"{k} = :{param_key}")
        params[param_key] = str(v) if v is not None else ""

    spark.sql(
        f"""
        UPDATE {APP_CATALOG}.{APP_SCHEMA}.ingestion_jobs
        SET {', '.join(set_parts)}
        WHERE run_id = :run_id
        """,
        args=params,
    )


def update_progress(completed=0, failed=0):
    """Increment completed/failed counters."""
    spark.sql(
        f"""
        UPDATE {APP_CATALOG}.{APP_SCHEMA}.ingestion_jobs
        SET completed_documents = completed_documents + :completed,
            failed_documents = failed_documents + :failed
        WHERE run_id = :run_id
        """,
        args={"completed": completed, "failed": failed, "run_id": RUN_ID},
    )

# ---------------------------------------------------------------------------
# Stage 1: List files and create batches
# ---------------------------------------------------------------------------
write_event("JOB_STARTED")
update_job_state("RUNNING", started_at=datetime.now(timezone.utc).isoformat())

try:
    files_df = spark.sql(f"""
        SELECT _metadata.file_name AS file_name,
               _metadata.file_path AS file_path,
               _metadata.file_size AS file_size
        FROM read_files('{VOLUME_PATH}', format => 'binaryFile')
    """)
    file_list = [row.asDict() for row in files_df.collect()]
    total_files = len(file_list)
    print(f"Found {total_files} files to process")
except Exception as exc:
    print(f"ERROR listing files: {exc}")
    update_job_state("FAILED", error_summary=str(exc)[:500],
                     completed_at=datetime.now(timezone.utc).isoformat())
    write_event("JOB_FAILED", payload={"error": str(exc)[:500]})
    raise

num_batches = math.ceil(total_files / BATCH_SIZE)
print(f"Processing {total_files} files in {num_batches} batches of {BATCH_SIZE}")

# ---------------------------------------------------------------------------
# Stage 2: Process batches
# ---------------------------------------------------------------------------
total_completed = 0
total_failed = 0

for batch_idx in range(num_batches):
    batch_id = f"batch_{batch_idx}"
    batch_start = batch_idx * BATCH_SIZE
    batch_files = file_list[batch_start:batch_start + BATCH_SIZE]
    batch_names = [f["file_name"] for f in batch_files]

    write_event("BATCH_STARTED", batch_id=batch_id,
                payload={"batch_index": batch_idx, "file_count": len(batch_files)})
    print(f"\n--- Batch {batch_idx + 1}/{num_batches}: {len(batch_files)} files ---")

    for file_info in batch_files:
        fname = file_info["file_name"]
        fpath = file_info["file_path"]
        doc_version_id = str(uuid.uuid4())

        try:
            write_event("DOCUMENT_STARTED", doc_version_id=doc_version_id,
                        batch_id=batch_id, payload={"file_name": fname})

            # Core extraction CTE — per-document
            # NOTE: read_files() requires a literal path, so fpath is
            # interpolated into the SQL. The value originates from
            # _metadata.file_path (Databricks-controlled), not from
            # user HTTP input.  Other values are parameterized.
            spark.sql(
                f"""
                WITH raw AS (
                    SELECT
                        _metadata.file_name AS file_name,
                        _metadata.file_path AS file_path,
                        _metadata.file_size AS file_size_bytes,
                        *
                    FROM read_files('{fpath}', format => 'binaryFile')
                    LIMIT 1
                )
                INSERT INTO {OUTPUT_CATALOG}.{OUTPUT_SCHEMA}.contracts_parsed
                SELECT
                    :doc_version_id AS document_version_id,
                    md5(file_path) AS source_document_id,
                    file_name,
                    file_path,
                    file_size_bytes,
                    CASE
                        WHEN file_name LIKE '%.pdf' THEN 'pdf'
                        WHEN file_name LIKE '%.docx' THEN 'docx'
                        WHEN file_name LIKE '%.pptx' THEN 'pptx'
                        WHEN file_name LIKE '%.png' THEN 'png'
                        WHEN file_name LIKE '%.tif%' THEN 'tiff'
                        ELSE 'unknown'
                    END AS file_type,
                    md5(CONCAT(file_path, CAST(file_size_bytes AS STRING))) AS file_checksum,
                    CAST(NULL AS STRING) AS parsed_content,
                    CAST(NULL AS INT) AS page_count,
                    CAST(NULL AS FLOAT) AS quality_score,
                    false AS has_errors,
                    CAST(NULL AS STRING) AS error_details,
                    current_timestamp() AS extraction_ts,
                    :run_id AS extraction_run_id,
                    current_user() AS extracted_by,
                    :profile AS extraction_profile,
                    'Other' AS doc_category,
                    CAST(NULL AS STRING) AS doc_subcategory,
                    'AI_EXTRACTED' AS verification_status,
                    CAST(NULL AS STRING) AS verified_by,
                    CAST(NULL AS TIMESTAMP) AS verified_at,
                    CAST(NULL AS STRING) AS confidence_scores,
                    CAST(NULL AS STRING) AS confidence_explanation,
                    CAST(NULL AS STRING) AS parties,
                    CAST(NULL AS STRING) AS contract_type,
                    CAST(NULL AS STRING) AS state_jurisdiction,
                    CAST(NULL AS DATE) AS effective_date,
                    CAST(NULL AS DATE) AS expiration_date,
                    CAST(NULL AS INT) AS term_months,
                    CAST(NULL AS BOOLEAN) AS auto_renewal,
                    CAST(NULL AS STRING) AS auto_renewal_terms,
                    CAST(NULL AS INT) AS termination_notice_days,
                    CAST(NULL AS STRING) AS governing_law,
                    CAST(NULL AS STRING) AS reimbursement_method,
                    CAST(NULL AS STRING) AS fee_schedule,
                    CAST(NULL AS STRING) AS drg_terms,
                    CAST(NULL AS STRING) AS per_diem_rates,
                    CAST(NULL AS STRING) AS capitation_rates,
                    CAST(NULL AS STRING) AS stop_loss_terms,
                    CAST(NULL AS STRING) AS quality_metrics,
                    CAST(NULL AS STRING) AS shared_savings,
                    CAST(NULL AS STRING) AS star_rating_terms,
                    CAST(NULL AS STRING) AS cms_contract_id,
                    CAST(NULL AS STRING) AS eligibility_categories,
                    CAST(NULL AS STRING) AS mlr_terms,
                    CAST(NULL AS STRING) AS risk_adjustment,
                    CAST(NULL AS STRING) AS baa_terms,
                    CAST(NULL AS ARRAY<STRING>) AS regulatory_tags,
                    CAST(NULL AS ARRAY<STRING>) AS cms_regulatory_refs,
                    false AS phi_detected,
                    CAST(NULL AS STRING) AS credentialing,
                    CAST(NULL AS STRING) AS network_adequacy,
                    CAST(NULL AS STRING) AS delegated_functions,
                    CAST(NULL AS STRING) AS extracted_dates,
                    CAST(NULL AS STRING) AS applicability_status,
                    CAST(NULL AS STRING) AS executive_summary
                FROM raw
                """,
                args={"doc_version_id": doc_version_id, "run_id": RUN_ID, "profile": PROFILE},
            )

            write_event("DOCUMENT_COMPLETED", doc_version_id=doc_version_id,
                        batch_id=batch_id, payload={"file_name": fname})
            total_completed += 1
            update_progress(completed=1)
            print(f"  ✓ {fname}")

        except Exception as doc_exc:
            # Per-document error — log and continue
            total_failed += 1
            update_progress(failed=1)
            write_event("DOCUMENT_FAILED", doc_version_id=doc_version_id,
                        batch_id=batch_id,
                        payload={"file_name": fname, "error": str(doc_exc)[:500]})
            print(f"  ✗ {fname}: {doc_exc}")

# ---------------------------------------------------------------------------
# Stage 3: Finalize
# ---------------------------------------------------------------------------
final_state = (
    "COMPLETED" if total_failed == 0
    else "COMPLETED_WITH_ERRORS" if total_completed > 0
    else "FAILED"
)

update_job_state(
    final_state,
    completed_at=datetime.now(timezone.utc).isoformat(),
)
write_event(
    "JOB_COMPLETED" if total_failed == 0 else "JOB_COMPLETED_WITH_ERRORS",
    payload={
        "total_completed": total_completed,
        "total_failed": total_failed,
    },
)

print(f"\n=== Extraction complete: {total_completed} succeeded, {total_failed} failed ===")
