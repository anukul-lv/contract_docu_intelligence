"""R2 Migration — Create all 7 R2 tables for the Intelligence Layer.

Run this notebook as a DABs pre-deploy step or manually after R1 tables exist.

Tables created:
  Chat:         chat_sessions, chat_messages, chat_cache
  Retrieval:    document_chunks
  Relationship: contracts_relationships
  Quality:      contracts_quality_metrics, quality_evaluations
"""
import os

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

APP_CATALOG = os.environ.get("APP_CATALOG", "dev")
APP_SCHEMA = os.environ.get("APP_SCHEMA", "doc_intel")
CUSTOMER_CATALOG = os.environ.get("CUSTOMER_CATALOG", "dev")
CUSTOMER_SCHEMA = os.environ.get("CUSTOMER_SCHEMA", "doc_intel")


def _exec(sql: str, description: str) -> None:
    """Execute SQL via statement execution API."""
    print(f"\n{'='*60}\n{description}\n{'='*60}")
    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
    result = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=sql,
        wait_timeout="120s",
    )
    print(f"  Status: {result.status.state.value if result.status else 'UNKNOWN'}")


# ---------------------------------------------------------------------------
# 1. chat_sessions
# ---------------------------------------------------------------------------
_exec(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.chat_sessions (
  conversation_id        STRING        NOT NULL,
  scope_type             STRING        DEFAULT 'all',
  scope_id               STRING,
  table_name             STRING,
  title                  STRING,
  context_summary        STRING,
  message_count          INT           DEFAULT 0,
  created_by             STRING        NOT NULL,
  created_at             TIMESTAMP     DEFAULT current_timestamp(),
  last_message_at        TIMESTAMP
) USING DELTA
TBLPROPERTIES (
  'delta.feature.allowColumnDefaults' = 'supported',
  'delta.enableChangeDataFeed' = 'true'
)""", "Creating chat_sessions")

# ---------------------------------------------------------------------------
# 2. chat_messages
# ---------------------------------------------------------------------------
_exec(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.chat_messages (
  message_id             STRING        NOT NULL,
  conversation_id        STRING        NOT NULL,
  role                   STRING        NOT NULL,
  content                STRING        NOT NULL,
  tool_calls             STRING,
  tool_results           STRING,
  citations              STRING,
  trust_badge            STRING,
  route_used             STRING,
  model_used             STRING,
  token_count_input      INT,
  token_count_output     INT,
  latency_ms             INT,
  feedback_rating        STRING,
  feedback_comment       STRING,
  created_at             TIMESTAMP     DEFAULT current_timestamp()
) USING DELTA
TBLPROPERTIES (
  'delta.feature.allowColumnDefaults' = 'supported',
  'delta.enableChangeDataFeed' = 'true'
)""", "Creating chat_messages")

# ---------------------------------------------------------------------------
# 3. chat_cache (semantic cache with vector invalidation)
# ---------------------------------------------------------------------------
_exec(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.chat_cache (
  cache_id               STRING        NOT NULL,
  normalized_question    STRING        NOT NULL,
  question_embedding     ARRAY<FLOAT>,
  scope_type             STRING,
  scope_id               STRING,
  corpus_version         STRING        NOT NULL,
  trust_policy_version   STRING        NOT NULL,
  answer_payload         STRING        NOT NULL,
  created_at             TIMESTAMP     DEFAULT current_timestamp(),
  last_hit_at            TIMESTAMP,
  hit_count              INT           DEFAULT 0
) USING DELTA
TBLPROPERTIES (
  'delta.feature.allowColumnDefaults' = 'supported'
)""", "Creating chat_cache")

# ---------------------------------------------------------------------------
# 4. document_chunks (RAG retrieval — source for AI Search Delta Sync)
# ---------------------------------------------------------------------------
_exec(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.document_chunks (
  chunk_id               STRING        NOT NULL,
  document_version_id    STRING        NOT NULL,
  chunk_index            INT           NOT NULL,
  chunk_to_embed         STRING        NOT NULL,
  chunk_to_retrieve      STRING        NOT NULL,
  page_numbers           ARRAY<INT>,
  section_header         STRING,
  contract_type          STRING,
  state_jurisdiction     STRING,
  effective_date         DATE,
  expiration_date        DATE,
  reimbursement_method   STRING,
  contains_table         BOOLEAN       DEFAULT false,
  embedding              ARRAY<FLOAT>,
  created_at             TIMESTAMP     DEFAULT current_timestamp()
) USING DELTA
TBLPROPERTIES (
  'delta.feature.allowColumnDefaults' = 'supported',
  'delta.enableChangeDataFeed' = 'true'
)""", "Creating document_chunks")

# ---------------------------------------------------------------------------
# 5. contracts_relationships (amendment/supersession graph)
# ---------------------------------------------------------------------------
_exec(f"""
CREATE TABLE IF NOT EXISTS {CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_relationships (
  relationship_id        STRING        NOT NULL,
  parent_document_id     STRING        NOT NULL,
  child_document_id      STRING        NOT NULL,
  relationship_type      STRING        NOT NULL,
  applicability_status   STRING        DEFAULT 'ACTIVE',
  effective_date         DATE,
  expiration_date        DATE,
  supersession_notes     STRING,
  created_at             TIMESTAMP     DEFAULT current_timestamp(),
  created_by             STRING
) USING DELTA
TBLPROPERTIES (
  'delta.feature.allowColumnDefaults' = 'supported',
  'delta.enableChangeDataFeed' = 'true'
)""", "Creating contracts_relationships")

# ---------------------------------------------------------------------------
# 6. contracts_quality_metrics
# ---------------------------------------------------------------------------
_exec(f"""
CREATE TABLE IF NOT EXISTS {CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_quality_metrics (
  metric_id              STRING        NOT NULL,
  evaluation_date        DATE          NOT NULL,
  metric_type            STRING        NOT NULL,
  scope                  STRING,
  field_name             STRING,
  contract_type          STRING,
  metric_value           FLOAT         NOT NULL,
  sample_size            INT,
  baseline_value         FLOAT,
  delta_from_baseline    FLOAT,
  alert_triggered        BOOLEAN       DEFAULT false
) USING DELTA
TBLPROPERTIES (
  'delta.feature.allowColumnDefaults' = 'supported'
)""", "Creating contracts_quality_metrics")

# ---------------------------------------------------------------------------
# 7. quality_evaluations
# ---------------------------------------------------------------------------
_exec(f"""
CREATE TABLE IF NOT EXISTS {APP_CATALOG}.{APP_SCHEMA}.quality_evaluations (
  evaluation_id          STRING        NOT NULL,
  evaluation_type        STRING        NOT NULL,
  run_date               TIMESTAMP     NOT NULL,
  gold_set_version       STRING,
  metrics                STRING        NOT NULL,
  summary                STRING,
  baseline_comparison    STRING,
  triggered_by           STRING,
  mlflow_experiment_id   STRING,
  mlflow_run_id          STRING
) USING DELTA
TBLPROPERTIES (
  'delta.feature.allowColumnDefaults' = 'supported'
)""", "Creating quality_evaluations")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
R2_TABLES = [
    f"{APP_CATALOG}.{APP_SCHEMA}.chat_sessions",
    f"{APP_CATALOG}.{APP_SCHEMA}.chat_messages",
    f"{APP_CATALOG}.{APP_SCHEMA}.chat_cache",
    f"{APP_CATALOG}.{APP_SCHEMA}.document_chunks",
    f"{CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_relationships",
    f"{CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_quality_metrics",
    f"{APP_CATALOG}.{APP_SCHEMA}.quality_evaluations",
]

print(f"\n{'='*60}")
print(f"R2 MIGRATION COMPLETE — {len(R2_TABLES)} tables created")
print(f"{'='*60}")
for t in R2_TABLES:
    print(f"  ✓ {t}")
