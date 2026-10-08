"""HealthContracts AI — Bootstrap Tables & Seed Data.

Creates all 12 R1 Delta tables and inserts seed data.
Run this notebook against a SQL warehouse or cluster with CREATE TABLE permissions.

Environment variables (or defaults for dev):
  APP_CATALOG / APP_SCHEMA       -> dev.doc_intel
  CUSTOMER_CATALOG / CUSTOMER_SCHEMA -> dev.doc_intel
"""
import os
from databricks.sdk import WorkspaceClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_CATALOG = os.getenv("APP_CATALOG", "dev")
APP_SCHEMA = os.getenv("APP_SCHEMA", "doc_intel")
CUSTOMER_CATALOG = os.getenv("CUSTOMER_CATALOG", "dev")
CUSTOMER_SCHEMA = os.getenv("CUSTOMER_SCHEMA", "doc_intel")

w = WorkspaceClient()

def run_sql(statement: str) -> None:
    """Execute a SQL statement via the Databricks SDK statement execution API."""
    print(f"  Running: {statement[:80]}...")
    # When running inside a Databricks notebook/app, spark.sql is preferred:
    try:
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()
        spark.sql(statement)
    except Exception:
        # Fallback for non-Spark environments
        raise


# =========================================================================
# BATCH 1 — Operational Tables (app_catalog.app_schema)
# =========================================================================
print("=== Batch 1: Operational Tables ===")

# 1. feature_flags
run_sql(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.feature_flags (
  flag_name       STRING    NOT NULL,
  enabled         BOOLEAN   DEFAULT false,
  rollout_pct     INT       DEFAULT 0,
  user_allowlist  ARRAY<STRING>,
  description     STRING,
  created_at      TIMESTAMP DEFAULT current_timestamp(),
  updated_at      TIMESTAMP
) USING DELTA
TBLPROPERTIES ('delta.feature.allowColumnDefaults' = 'supported')
""")

# 2. confidence_thresholds
run_sql(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.confidence_thresholds (
  field_class            STRING        NOT NULL,
  field_pattern          STRING,
  auto_approve_threshold FLOAT         NOT NULL,
  review_threshold       FLOAT         NOT NULL,
  flag_threshold         FLOAT         NOT NULL,
  always_review          BOOLEAN       DEFAULT false,
  updated_at             TIMESTAMP     DEFAULT current_timestamp(),
  updated_by             STRING
) USING DELTA
TBLPROPERTIES ('delta.feature.allowColumnDefaults' = 'supported')
""")

# 3. guardrail_policy
run_sql(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.guardrail_policy (
  policy_name        STRING NOT NULL,
  enabled            BOOLEAN DEFAULT true,
  policy_type        STRING NOT NULL,
  policy_config      STRING,
  updated_at         TIMESTAMP DEFAULT current_timestamp()
) USING DELTA
TBLPROPERTIES ('delta.feature.allowColumnDefaults' = 'supported')
""")

# 4. cost_tracking
run_sql(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.cost_tracking (
  cost_id                STRING        NOT NULL,
  run_id                 STRING,
  cost_category          STRING        NOT NULL,
  dbu_consumed           FLOAT,
  token_count            INT,
  model_used             STRING,
  estimated_usd          FLOAT,
  tracking_date          DATE          NOT NULL,
  created_at             TIMESTAMP     DEFAULT current_timestamp()
) USING DELTA
TBLPROPERTIES ('delta.feature.allowColumnDefaults' = 'supported')
""")

print("Batch 1 complete.\n")

# =========================================================================
# BATCH 2 — Workflow Tables (app_catalog.app_schema)
# =========================================================================
print("=== Batch 2: Workflow Tables ===")

# 5. ingestion_jobs
run_sql(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.ingestion_jobs (
  run_id                 STRING        NOT NULL,
  job_id                 BIGINT,
  databricks_run_id      BIGINT,
  state                  STRING        NOT NULL DEFAULT 'CREATED',
  total_documents        INT,
  completed_documents    INT           DEFAULT 0,
  failed_documents       INT           DEFAULT 0,
  volume_path            STRING        NOT NULL,
  output_catalog         STRING        NOT NULL,
  output_schema          STRING        NOT NULL,
  profile                STRING        NOT NULL,
  profile_snapshot       STRING,
  batch_size             INT           DEFAULT 25,
  healthcare_mode        BOOLEAN       DEFAULT true,
  idempotency_key        STRING,
  estimated_cost         FLOAT,
  actual_cost            FLOAT,
  error_summary          STRING,
  created_by             STRING        NOT NULL,
  created_at             TIMESTAMP     DEFAULT current_timestamp(),
  started_at             TIMESTAMP,
  completed_at           TIMESTAMP
) USING DELTA
TBLPROPERTIES ('delta.feature.allowColumnDefaults' = 'supported')
""")

# 6. ingestion_job_events
run_sql(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.ingestion_job_events (
  event_id               STRING        NOT NULL,
  run_id                 STRING        NOT NULL,
  event_ts               TIMESTAMP     NOT NULL,
  event_type             STRING        NOT NULL,
  document_version_id    STRING,
  batch_id               STRING,
  event_payload          STRING,
  created_by             STRING
) USING DELTA
""")

# 7. review_queue
run_sql(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.review_queue (
  review_id              STRING        NOT NULL,
  document_version_id    STRING        NOT NULL,
  document_file_name     STRING        NOT NULL,
  field_name             STRING        NOT NULL,
  ai_extracted_value     STRING,
  ai_confidence          FLOAT,
  confidence_explanation STRING,
  source_citation        STRING,
  field_class            STRING,
  human_corrected_value  STRING,
  review_status          STRING        DEFAULT 'PENDING',
  assigned_to            STRING,
  reviewed_by            STRING,
  reviewed_at            TIMESTAMP,
  review_comment         STRING,
  correction_reason      STRING,
  priority               STRING        DEFAULT 'NORMAL',
  version_number         INT           DEFAULT 1,
  created_at             TIMESTAMP     DEFAULT current_timestamp(),
  extraction_run_id      STRING
) USING DELTA
TBLPROPERTIES ('delta.feature.allowColumnDefaults' = 'supported')
""")

# 8. review_actions
run_sql(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.review_actions (
  action_id              STRING        NOT NULL,
  review_id              STRING        NOT NULL,
  document_version_id    STRING        NOT NULL,
  field_name             STRING        NOT NULL,
  action_type            STRING        NOT NULL,
  previous_value         STRING,
  new_value              STRING,
  correction_reason      STRING,
  action_comment         STRING,
  performed_by           STRING        NOT NULL,
  performed_at           TIMESTAMP     DEFAULT current_timestamp(),
  version_before         INT,
  version_after          Int
) USING DELTA
TBLPROPERTIES ('delta.feature.allowColumnDefaults' = 'supported')
""")

print("Batch 2 complete.\n")

# =========================================================================
# BATCH 3 — Core Data Tables
# =========================================================================
print("=== Batch 3: Core Data Tables ===")

# 9. hipaa_audit_log (7-year retention)
run_sql(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.hipaa_audit_log (
  event_id               STRING        NOT NULL,
  event_timestamp        TIMESTAMP     NOT NULL,
  event_type             STRING        NOT NULL,
  user_identity          STRING        NOT NULL,
  user_role              STRING,
  resource_type          STRING,
  resource_id            STRING,
  action                 STRING        NOT NULL,
  phi_accessed           BOOLEAN       DEFAULT false,
  phi_fields_accessed    ARRAY<STRING>,
  source_ip              STRING,
  session_id             STRING,
  request_id             STRING,
  details                STRING,
  outcome                STRING        DEFAULT 'SUCCESS'
) USING DELTA
TBLPROPERTIES (
  'delta.feature.allowColumnDefaults' = 'supported',
  'delta.enableChangeDataFeed' = 'true',
  'delta.logRetentionDuration' = 'interval 2555 days',
  'delta.deletedFileRetentionDuration' = 'interval 2555 days'
)
""")

# 10. phi_vault (7-year retention)
run_sql(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.phi_vault (
  phi_id                 STRING        NOT NULL,
  document_version_id    STRING        NOT NULL,
  phi_type               STRING        NOT NULL,
  original_value         STRING        NOT NULL,
  masked_value           STRING,
  detection_layer        STRING,
  detection_confidence   FLOAT,
  page_number            INT,
  character_offset       INT,
  context_snippet        STRING,
  created_at             TIMESTAMP     DEFAULT current_timestamp(),
  created_by             STRING
) USING DELTA
TBLPROPERTIES (
  'delta.feature.allowColumnDefaults' = 'supported',
  'delta.logRetentionDuration' = 'interval 2555 days',
  'delta.deletedFileRetentionDuration' = 'interval 2555 days'
)
""")

# 11. contracts_parsed (CDF + column mapping)
run_sql(f"""
CREATE TABLE IF NOT EXISTS {CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_parsed (
  document_version_id      STRING        NOT NULL,
  source_document_id       STRING        NOT NULL,
  file_name                STRING        NOT NULL,
  file_path                STRING        NOT NULL,
  file_size_bytes          BIGINT,
  file_type                STRING,
  file_checksum            STRING        NOT NULL,
  parsed_content           STRING        NOT NULL,
  page_count               INT,
  quality_score            FLOAT,
  has_errors               BOOLEAN,
  error_details            STRING,
  extraction_ts            TIMESTAMP     NOT NULL,
  extraction_run_id        STRING        NOT NULL,
  extracted_by             STRING,
  extraction_profile       STRING,
  doc_category             STRING,
  doc_subcategory          STRING,
  verification_status      STRING        DEFAULT 'AI_EXTRACTED',
  verified_by              STRING,
  verified_at              TIMESTAMP,
  confidence_scores        STRING,
  confidence_explanation   STRING,
  parties                  STRING,
  contract_type            STRING,
  state_jurisdiction       STRING,
  effective_date           DATE,
  expiration_date          DATE,
  term_months              INT,
  auto_renewal             BOOLEAN,
  auto_renewal_terms       STRING,
  termination_notice_days  INT,
  governing_law            STRING,
  reimbursement_method     STRING,
  fee_schedule             STRING,
  drg_terms                STRING,
  per_diem_rates           STRING,
  capitation_rates         STRING,
  stop_loss_terms          STRING,
  quality_metrics          STRING,
  shared_savings           STRING,
  star_rating_terms        STRING,
  cms_contract_id          STRING,
  eligibility_categories   STRING,
  mlr_terms                STRING,
  risk_adjustment          STRING,
  baa_terms                STRING,
  regulatory_tags          ARRAY<STRING>,
  cms_regulatory_refs      ARRAY<STRING>,
  phi_detected             BOOLEAN       DEFAULT false,
  credentialing            STRING,
  network_adequacy         STRING,
  delegated_functions      STRING,
  extracted_dates          STRING,
  applicability_status     STRING,
  executive_summary        STRING
) USING DELTA
TBLPROPERTIES (
  'delta.feature.allowColumnDefaults' = 'supported',
  'delta.enableChangeDataFeed' = 'true',
  'delta.columnMapping.mode' = 'name',
  'delta.minReaderVersion' = '2',
  'delta.minWriterVersion' = '5'
)
""")

# 12. contracts_current (CDF enabled)
run_sql(f"""
CREATE TABLE IF NOT EXISTS {CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_current (
  record_id              STRING        NOT NULL,
  document_family_id     STRING        NOT NULL,
  source_document_id     STRING        NOT NULL,
  source_document_version_id STRING    NOT NULL,
  field_name             STRING        NOT NULL,
  trusted_value          STRING,
  value_type             STRING,
  review_status          STRING        NOT NULL,
  reviewed_by            STRING,
  reviewed_at            TIMESTAMP,
  source_citation        STRING,
  confidence_score       FLOAT,
  confidence_explanation STRING,
  effective_date         DATE,
  expiration_date        DATE,
  supersession_context   STRING,
  applicability_status   STRING,
  last_updated_at        TIMESTAMP     DEFAULT current_timestamp(),
  last_updated_by        STRING
) USING DELTA
TBLPROPERTIES (
  'delta.feature.allowColumnDefaults' = 'supported',
  'delta.enableChangeDataFeed' = 'true'
)
""")

print("Batch 3 complete.\n")

# =========================================================================
# SEED DATA
# =========================================================================
print("=== Inserting Seed Data ===")

# Feature flags (12 rows)
run_sql(f"""
INSERT INTO {APP_CATALOG}.{APP_SCHEMA}.feature_flags (flag_name, enabled, rollout_pct, description, created_at)
VALUES
  ('enable_dual_extraction', false, 0, 'Run two profiles in parallel for comparison', current_timestamp()),
  ('enable_auto_enrich', false, 0, 'Auto-enrich after extraction', current_timestamp()),
  ('enable_amendment_engine', false, 0, 'Activate amendment resolution (R2)', current_timestamp()),
  ('enable_active_learning', false, 0, 'Feed corrections back into profiles (R3)', current_timestamp()),
  ('enable_hybrid_search', true, 100, 'Hybrid BM25+vector retrieval (R2)', current_timestamp()),
  ('enable_llm_reranking', false, 0, 'LLM-based reranking for Route C (R2)', current_timestamp()),
  ('enable_ai_search_tool', true, 100, 'Enable ai_search agent tool (R2)', current_timestamp()),
  ('enable_notification_center', false, 0, 'In-app notifications (R3)', current_timestamp()),
  ('enable_semantic_cache', true, 100, 'Vector-indexed answer cache (R2)', current_timestamp()),
  ('enable_quality_dashboard', false, 0, 'Quality dashboard widgets (R3)', current_timestamp()),
  ('enable_inline_groundedness', true, 100, 'Post-generation groundedness check (R2)', current_timestamp()),
  ('enable_anomaly_detection', false, 0, '3-sigma anomaly flagging (R3)', current_timestamp())
""")

# Confidence thresholds (4 rows)
run_sql(f"""
INSERT INTO {APP_CATALOG}.{APP_SCHEMA}.confidence_thresholds
  (field_class, auto_approve_threshold, review_threshold, flag_threshold, always_review)
VALUES
  ('critical_financial',   0.0, 0.0, 0.0, true),
  ('critical_compliance',  0.0, 0.0, 0.0, true),
  ('important_structural', 0.92, 0.70, 0.70, false),
  ('low_risk_metadata',    0.85, 0.60, 0.60, false)
""")

print("Seed data complete.\n")
print("=== Bootstrap finished. All 12 tables created. ===")
