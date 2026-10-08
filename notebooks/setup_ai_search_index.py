"""Setup AI Search — Create Vector Search endpoint and Delta Sync index.

Creates:
  1. Vector Search endpoint (per-environment isolation)
  2. Delta Sync index on document_chunks with embedding via databricks-gte-large-en
  3. Validates index health after creation

Run once per environment. Idempotent — skips if endpoint/index already exists.
"""
import os
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.vectorsearch import (
    DeltaSyncVectorIndexSpecRequest,
    EmbeddingSourceColumn,
    EndpointType,
    VectorIndexType,
)

w = WorkspaceClient()

APP_CATALOG = os.environ.get("APP_CATALOG", "dev")
APP_SCHEMA = os.environ.get("APP_SCHEMA", "doc_intel")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")

ENDPOINT_NAME = f"{ENVIRONMENT}_healthcare_search_endpoint"
INDEX_NAME = f"{APP_CATALOG}.{APP_SCHEMA}.document_chunks_index"
SOURCE_TABLE = f"{APP_CATALOG}.{APP_SCHEMA}.document_chunks"
EMBEDDING_MODEL = "databricks-gte-large-en"

COLUMNS_TO_SYNC = [
    "chunk_id",
    "document_version_id",
    "chunk_index",
    "chunk_to_retrieve",
    "page_numbers",
    "section_header",
    "contract_type",
    "state_jurisdiction",
    "effective_date",
    "expiration_date",
    "reimbursement_method",
    "contains_table",
]


# ---------------------------------------------------------------------------
# Step 1: Create Vector Search endpoint
# ---------------------------------------------------------------------------
print("=" * 60)
print("AI SEARCH SETUP")
print(f"  Environment: {ENVIRONMENT}")
print(f"  Endpoint: {ENDPOINT_NAME}")
print(f"  Index: {INDEX_NAME}")
print(f"  Source: {SOURCE_TABLE}")
print(f"  Embedding model: {EMBEDDING_MODEL}")
print("=" * 60)

# Check if endpoint already exists
existing_endpoints = w.vector_search_endpoints.list_endpoints()
endpoint_exists = any(ep.name == ENDPOINT_NAME for ep in existing_endpoints)

if endpoint_exists:
    print(f"\n  Endpoint '{ENDPOINT_NAME}' already exists. Skipping creation.")
else:
    print(f"\n  Creating endpoint '{ENDPOINT_NAME}'...")
    w.vector_search_endpoints.create_endpoint(
        name=ENDPOINT_NAME,
        endpoint_type=EndpointType.STANDARD,
    )
    print("  Endpoint creation initiated.")

    # Wait for endpoint to become ready (up to 10 minutes)
    print("  Waiting for endpoint to become ONLINE...")
    for attempt in range(60):
        ep = w.vector_search_endpoints.get_endpoint(endpoint_name=ENDPOINT_NAME)
        status = ep.endpoint_status
        if status and status.state and status.state.value == "ONLINE":
            print(f"  Endpoint ONLINE after {(attempt + 1) * 10}s")
            break
        time.sleep(10)
    else:
        print("  WARNING: Endpoint not ONLINE after 10 minutes. Index creation may fail.")


# ---------------------------------------------------------------------------
# Step 2: Create Delta Sync index
# ---------------------------------------------------------------------------
try:
    existing_index = w.vector_search_indexes.get_index(index_name=INDEX_NAME)
    print(f"\n  Index '{INDEX_NAME}' already exists. Skipping creation.")
    print(f"  Status: {existing_index.status}")
except Exception:
    print(f"\n  Creating Delta Sync index '{INDEX_NAME}'...")
    w.vector_search_indexes.create_index(
        name=INDEX_NAME,
        endpoint_name=ENDPOINT_NAME,
        primary_key="chunk_id",
        index_type=VectorIndexType.DELTA_SYNC,
        delta_sync_index_spec=DeltaSyncVectorIndexSpecRequest(
            source_table=SOURCE_TABLE,
            pipeline_type="TRIGGERED",
            embedding_source_columns=[
                EmbeddingSourceColumn(
                    name="chunk_to_embed",
                    embedding_model_endpoint_name=EMBEDDING_MODEL,
                )
            ],
            columns_to_sync=COLUMNS_TO_SYNC,
        ),
    )
    print("  Index creation initiated.")

    # Wait for index to become ready (up to 15 minutes)
    print("  Waiting for index to become ONLINE...")
    for attempt in range(90):
        try:
            idx = w.vector_search_indexes.get_index(index_name=INDEX_NAME)
            status = idx.status
            if status and status.ready:
                print(f"  Index ONLINE after {(attempt + 1) * 10}s")
                break
        except Exception:
            pass
        time.sleep(10)
    else:
        print("  WARNING: Index not ready after 15 minutes.")
        print("  Check status later with:")
        print(f"    w.vector_search_indexes.get_index('{INDEX_NAME}')")


# ---------------------------------------------------------------------------
# Step 3: Validate
# ---------------------------------------------------------------------------
print(f"\n{'='*60}")
print("VALIDATION")
print(f"{'='*60}")

try:
    ep = w.vector_search_endpoints.get_endpoint(endpoint_name=ENDPOINT_NAME)
    ep_status = ep.endpoint_status.state.value if ep.endpoint_status and ep.endpoint_status.state else "UNKNOWN"
    print(f"  Endpoint: {ENDPOINT_NAME} → {ep_status}")
except Exception as e:
    print(f"  Endpoint check failed: {e}")

try:
    idx = w.vector_search_indexes.get_index(index_name=INDEX_NAME)
    idx_status = "READY" if idx.status and idx.status.ready else "NOT READY"
    print(f"  Index: {INDEX_NAME} → {idx_status}")
except Exception as e:
    print(f"  Index check failed: {e}")

print(f"\n{'='*60}")
print("AI SEARCH SETUP COMPLETE")
print(f"{'='*60}")
print(f"\nMetadata filters available for retrieval:")
print(f"  - contract_type (exact/IN)")
print(f"  - state_jurisdiction (exact/IN)")
print(f"  - effective_date / expiration_date (range)")
print(f"  - reimbursement_method (exact)")
print(f"  - contains_table (boolean)")
