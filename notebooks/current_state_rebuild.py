"""Nightly full MERGE rebuild of contracts_current.

Scheduled via Lakeflow Jobs to run nightly at 1 AM.
Rebuilds the trusted current-state view by combining:
  - Latest extraction from contracts_parsed (per document family)
  - Review overrides from review_queue (approved/corrected values)

MERGE key: (document_family_id, field_name)
"""
import os
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_CATALOG = os.getenv("APP_CATALOG", "dev")
APP_SCHEMA = os.getenv("APP_SCHEMA", "doc_intel")
CUSTOMER_CATALOG = os.getenv("CUSTOMER_CATALOG", "dev")
CUSTOMER_SCHEMA = os.getenv("CUSTOMER_SCHEMA", "doc_intel")

start_ts = datetime.now(timezone.utc)
print(f"=== contracts_current rebuild started at {start_ts.isoformat()} ===")

# ---------------------------------------------------------------------------
# Step 1: Build resolved current state view (CTE)
# ---------------------------------------------------------------------------
# For each (source_document_id, field), take the latest extraction,
# then overlay any review corrections.

rebuild_sql = f"""
MERGE INTO {CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_current t
USING (
    WITH latest_parsed AS (
        -- Latest extraction per document family
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY source_document_id
                ORDER BY extraction_ts DESC
            ) AS rn
        FROM {CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_parsed
        WHERE has_errors = false OR has_errors IS NULL
    ),
    base_docs AS (
        SELECT * FROM latest_parsed WHERE rn = 1
    ),
    -- Unpivot key fields into (doc_id, field_name, value) rows
    unpivoted AS (
        SELECT source_document_id, document_version_id, 'contract_type' AS field_name,
               CAST(contract_type AS STRING) AS raw_value, extraction_profile,
               confidence_scores, confidence_explanation, effective_date, expiration_date
        FROM base_docs
        UNION ALL
        SELECT source_document_id, document_version_id, 'state_jurisdiction',
               CAST(state_jurisdiction AS STRING), extraction_profile,
               confidence_scores, confidence_explanation, effective_date, expiration_date
        FROM base_docs
        UNION ALL
        SELECT source_document_id, document_version_id, 'effective_date',
               CAST(effective_date AS STRING), extraction_profile,
               confidence_scores, confidence_explanation, effective_date, expiration_date
        FROM base_docs
        UNION ALL
        SELECT source_document_id, document_version_id, 'expiration_date',
               CAST(expiration_date AS STRING), extraction_profile,
               confidence_scores, confidence_explanation, effective_date, expiration_date
        FROM base_docs
        UNION ALL
        SELECT source_document_id, document_version_id, 'parties',
               CAST(parties AS STRING), extraction_profile,
               confidence_scores, confidence_explanation, effective_date, expiration_date
        FROM base_docs
        UNION ALL
        SELECT source_document_id, document_version_id, 'governing_law',
               CAST(governing_law AS STRING), extraction_profile,
               confidence_scores, confidence_explanation, effective_date, expiration_date
        FROM base_docs
        UNION ALL
        SELECT source_document_id, document_version_id, 'reimbursement_method',
               CAST(reimbursement_method AS STRING), extraction_profile,
               confidence_scores, confidence_explanation, effective_date, expiration_date
        FROM base_docs
        UNION ALL
        SELECT source_document_id, document_version_id, 'fee_schedule',
               CAST(fee_schedule AS STRING), extraction_profile,
               confidence_scores, confidence_explanation, effective_date, expiration_date
        FROM base_docs
        UNION ALL
        SELECT source_document_id, document_version_id, 'term_months',
               CAST(term_months AS STRING), extraction_profile,
               confidence_scores, confidence_explanation, effective_date, expiration_date
        FROM base_docs
        UNION ALL
        SELECT source_document_id, document_version_id, 'auto_renewal',
               CAST(auto_renewal AS STRING), extraction_profile,
               confidence_scores, confidence_explanation, effective_date, expiration_date
        FROM base_docs
        UNION ALL
        SELECT source_document_id, document_version_id, 'baa_terms',
               CAST(baa_terms AS STRING), extraction_profile,
               confidence_scores, confidence_explanation, effective_date, expiration_date
        FROM base_docs
    ),
    -- Overlay review corrections
    resolved AS (
        SELECT
            u.source_document_id,
            u.document_version_id,
            u.field_name,
            COALESCE(rq.human_corrected_value, u.raw_value) AS trusted_value,
            'string' AS value_type,
            COALESCE(rq.review_status, 'AI_EXTRACTED') AS review_status,
            rq.reviewed_by,
            rq.reviewed_at,
            rq.source_citation,
            rq.ai_confidence AS confidence_score,
            u.confidence_explanation,
            u.effective_date,
            u.expiration_date
        FROM unpivoted u
        LEFT JOIN {APP_CATALOG}.{APP_SCHEMA}.review_queue rq
            ON rq.document_version_id = u.document_version_id
            AND rq.field_name = u.field_name
            AND rq.review_status IN ('APPROVED', 'CORRECTED')
        WHERE u.raw_value IS NOT NULL
    )
    SELECT
        md5(source_document_id || field_name) AS record_id,
        source_document_id AS document_family_id,
        source_document_id,
        document_version_id AS source_document_version_id,
        field_name,
        trusted_value,
        value_type,
        review_status,
        reviewed_by,
        reviewed_at,
        CAST(NULL AS STRING) AS source_citation,
        confidence_score,
        confidence_explanation,
        effective_date,
        expiration_date,
        CAST(NULL AS STRING) AS supersession_context,
        'ACTIVE' AS applicability_status,
        current_timestamp() AS last_updated_at,
        'nightly_rebuild' AS last_updated_by
    FROM resolved
) s
ON t.document_family_id = s.document_family_id AND t.field_name = s.field_name
WHEN MATCHED THEN UPDATE SET
    source_document_version_id = s.source_document_version_id,
    trusted_value = s.trusted_value,
    review_status = s.review_status,
    reviewed_by = s.reviewed_by,
    reviewed_at = s.reviewed_at,
    confidence_score = s.confidence_score,
    confidence_explanation = s.confidence_explanation,
    effective_date = s.effective_date,
    expiration_date = s.expiration_date,
    applicability_status = s.applicability_status,
    last_updated_at = s.last_updated_at,
    last_updated_by = s.last_updated_by
WHEN NOT MATCHED THEN INSERT *
"""

print("Running full MERGE rebuild...")
result = spark.sql(rebuild_sql)
print(f"MERGE complete.")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
count_rows = spark.sql(
    f"SELECT COUNT(*) AS cnt FROM {CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_current"
).collect()
total = count_rows[0]["cnt"] if count_rows else 0

end_ts = datetime.now(timezone.utc)
elapsed = (end_ts - start_ts).total_seconds()

print(f"\n=== Rebuild complete ===")
print(f"  Total records in contracts_current: {total}")
print(f"  Duration: {elapsed:.1f}s")
