"""Chunking Pipeline — Populate document_chunks from contracts_parsed.

Runs as a post-extraction step in the Lakeflow Job or as a standalone backfill.
Uses ai_prep_search for intelligent chunking with overlap, then inserts into
the document_chunks table which feeds the AI Search Delta Sync index.

Modes:
  - Incremental (default): Only chunks documents not yet in document_chunks
  - Backfill: Re-chunks all documents (set BACKFILL=true)

After insert, triggers AI Search index sync for near-real-time retrieval.
"""
import os
import time

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

APP_CATALOG = os.environ.get("APP_CATALOG", "dev")
APP_SCHEMA = os.environ.get("APP_SCHEMA", "doc_intel")
CUSTOMER_CATALOG = os.environ.get("CUSTOMER_CATALOG", "dev")
CUSTOMER_SCHEMA = os.environ.get("CUSTOMER_SCHEMA", "doc_intel")
BACKFILL = os.environ.get("BACKFILL", "false").lower() == "true"
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


def execute_sql(sql: str, description: str = "") -> dict:
    """Execute SQL and return result."""
    if description:
        print(f"  {description}...")
    result = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=sql,
        wait_timeout="300s",
    )
    return result


def get_row_count(table: str) -> int:
    """Return row count for a table."""
    result = execute_sql(f"SELECT COUNT(*) AS cnt FROM {table}")
    if result.result and result.result.data_array:
        return int(result.result.data_array[0][0])
    return 0


# ---------------------------------------------------------------------------
# Step 1: Identify documents to chunk
# ---------------------------------------------------------------------------
print("=" * 60)
print("CHUNKING PIPELINE")
print(f"  Mode: {'BACKFILL' if BACKFILL else 'INCREMENTAL'}")
print(f"  Chunk size: {CHUNK_SIZE}, Overlap: {CHUNK_OVERLAP}")
print("=" * 60)

chunks_table = f"{APP_CATALOG}.{APP_SCHEMA}.document_chunks"
parsed_table = f"{CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_parsed"

pre_count = get_row_count(chunks_table)
print(f"\n  Existing chunks: {pre_count}")

if BACKFILL:
    # Full backfill: delete existing chunks and re-chunk everything
    print("  Backfill mode: truncating existing chunks...")
    execute_sql(f"DELETE FROM {chunks_table}", "Truncating document_chunks")
    new_docs_cte = f"""
    new_documents AS (
      SELECT DISTINCT document_version_id
      FROM {parsed_table}
      WHERE parsed_content IS NOT NULL
    )"""
else:
    # Incremental: only chunk documents not yet processed
    new_docs_cte = f"""
    new_documents AS (
      SELECT DISTINCT cp.document_version_id
      FROM {parsed_table} cp
      LEFT JOIN {chunks_table} dc
        ON cp.document_version_id = dc.document_version_id
      WHERE dc.document_version_id IS NULL
        AND cp.parsed_content IS NOT NULL
    )"""

# Check how many new documents to process
count_result = execute_sql(f"""
  WITH {new_docs_cte}
  SELECT COUNT(*) AS cnt FROM new_documents
""")

new_doc_count = 0
if count_result.result and count_result.result.data_array:
    new_doc_count = int(count_result.result.data_array[0][0])

print(f"  Documents to chunk: {new_doc_count}")

if new_doc_count == 0:
    print("\n  No new documents to chunk. Exiting.")
else:
    # ---------------------------------------------------------------------------
    # Step 2: Chunk documents using ai_prep_search
    # ---------------------------------------------------------------------------
    print(f"\n  Chunking {new_doc_count} documents...")
    start_time = time.time()

    chunk_sql = f"""
    WITH {new_docs_cte},
    chunks AS (
      SELECT
        cp.document_version_id,
        cp.doc_category AS contract_type,
        cp.state_jurisdiction,
        cp.effective_date,
        cp.expiration_date,
        cp.reimbursement_method,
        explode(
          ai_prep_search(
            cp.parsed_content,
            '{{{"chunk_size": {CHUNK_SIZE}, "overlap": {CHUNK_OVERLAP}}}}'  
          )
        ) AS chunk
      FROM {parsed_table} cp
      WHERE cp.document_version_id IN (
        SELECT document_version_id FROM new_documents
      )
    )
    INSERT INTO {chunks_table}
    SELECT
      uuid() AS chunk_id,
      document_version_id,
      chunk.chunk_index,
      chunk.chunk_text AS chunk_to_embed,
      chunk.chunk_text AS chunk_to_retrieve,
      chunk.page_numbers,
      chunk.section_header,
      contract_type,
      state_jurisdiction,
      effective_date,
      expiration_date,
      reimbursement_method,
      chunk.contains_table,
      NULL AS embedding,
      current_timestamp() AS created_at
    FROM chunks
    """

    execute_sql(chunk_sql, "Inserting chunks")
    elapsed = time.time() - start_time

    post_count = get_row_count(chunks_table)
    new_chunks = post_count - (0 if BACKFILL else pre_count)

    print(f"\n  Chunks created: {new_chunks}")
    print(f"  Total chunks in table: {post_count}")
    print(f"  Time: {elapsed:.1f}s")
    print(f"  Avg chunks/doc: {new_chunks / max(new_doc_count, 1):.1f}")

    # ---------------------------------------------------------------------------
    # Step 3: Trigger AI Search index sync
    # ---------------------------------------------------------------------------
    index_name = f"{APP_CATALOG}.{APP_SCHEMA}.document_chunks_index"
    print(f"\n  Triggering AI Search index sync: {index_name}")

    try:
        w.vector_search_indexes.sync_index(index_name=index_name)
        print("  Index sync triggered successfully.")
    except Exception as e:
        # Index may not exist yet (setup_ai_search_index.py not run)
        print(f"  WARNING: Could not trigger index sync: {e}")
        print("  Run setup_ai_search_index.py first to create the index.")

print(f"\n{'='*60}")
print("CHUNKING PIPELINE COMPLETE")
print(f"{'='*60}")
