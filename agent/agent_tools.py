"""Agent tools — 4 tool implementations for the healthcare contract agent.

Tools:
  1. sql_query — READ-ONLY SQL against contracts_current (Route A)
  2. ai_search_tool — Hybrid retrieval via AI Search (Route B)
  3. ai_extract_on_demand — On-demand field extraction (Routes A, C)
  4. review_status_check — Verification status lookup (all routes)
"""
from __future__ import annotations

import json
import logging
import os
import re

from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)

APP_CATALOG = os.environ.get("APP_CATALOG", "dev")
APP_SCHEMA = os.environ.get("APP_SCHEMA", "doc_intel")
CUSTOMER_CATALOG = os.environ.get("CUSTOMER_CATALOG", "dev")
CUSTOMER_SCHEMA = os.environ.get("CUSTOMER_SCHEMA", "doc_intel")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

# Strip SQL comments before safety checks to prevent bypass via /* DELETE */
_SQL_LINE_COMMENT = re.compile(r"--[^\n]*")
_SQL_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

_client: WorkspaceClient | None = None


def _get_client() -> WorkspaceClient:
    global _client
    if _client is None:
        _client = WorkspaceClient()
    return _client


def _execute_sql(
    sql: str,
    parameters: list[dict] | None = None,
) -> list[dict]:
    """Execute SQL and return rows as list of dicts.

    Args:
        sql: SQL statement. Use :param_name for parameterized values.
        parameters: List of {"name": ..., "value": ..., "type": ...} dicts
            for parameterized queries (Statement Execution API format).
    """
    w = _get_client()
    result = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=sql,
        parameters=parameters or None,
        wait_timeout="120s",
    )
    if not result.result or not result.result.data_array:
        return []
    columns = [c.name for c in result.manifest.columns] if result.manifest else []
    return [dict(zip(columns, row)) for row in result.result.data_array]


# ---------------------------------------------------------------------------
# Tool 1: sql_query
# ---------------------------------------------------------------------------
def sql_query(query: str) -> dict:
    """Execute a READ-ONLY SQL query against contracts_current.

    The query must be a SELECT statement only. Rejects any DML/DDL.
    Comments are stripped before safety checks to prevent bypass.

    Returns:
        {"columns": [...], "rows": [...], "row_count": int}
    """
    query_stripped = query.strip()

    # Strip comments BEFORE safety checks to prevent bypass via:
    #   SELECT /* DELETE FROM t; */ 1
    #   SELECT 1 -- DROP TABLE t
    query_no_comments = _SQL_BLOCK_COMMENT.sub(" ", query_stripped)
    query_no_comments = _SQL_LINE_COMMENT.sub(" ", query_no_comments).strip()

    # Safety: reject non-SELECT
    if not query_no_comments.upper().startswith("SELECT"):
        return {"error": "Only SELECT queries are allowed.", "rows": [], "row_count": 0}

    if _FORBIDDEN_KEYWORDS.search(query_no_comments):
        return {"error": "Query contains forbidden keywords.", "rows": [], "row_count": 0}

    # Reject semicolons (prevents statement chaining)
    if ";" in query_no_comments:
        return {"error": "Multi-statement queries are not allowed.", "rows": [], "row_count": 0}

    try:
        rows = _execute_sql(query_stripped)
        columns = list(rows[0].keys()) if rows else []
        return {
            "columns": columns,
            "rows": rows[:100],  # Cap at 100 rows for agent context
            "row_count": len(rows),
        }
    except Exception as e:
        logger.error("sql_query tool error: %s", e)
        return {"error": str(e), "rows": [], "row_count": 0}


# ---------------------------------------------------------------------------
# Tool 2: ai_search_tool
# ---------------------------------------------------------------------------
def ai_search_tool(query: str, filters: dict | None = None) -> dict:
    """Search document chunks via AI Search hybrid retrieval.

    Returns:
        {"chunks": [{"chunk_text": ..., "document_name": ..., "page": ..., "score": ..., "contract_type": ...}]}
    """
    try:
        w = _get_client()
        index_name = f"{APP_CATALOG}.{APP_SCHEMA}.document_chunks_index"

        result = w.vector_search_indexes.query_index(
            index_name=index_name,
            columns=[
                "chunk_id", "document_version_id", "chunk_to_retrieve",
                "page_numbers", "section_header", "contract_type",
                "state_jurisdiction", "contains_table",
            ],
            query_text=query,
            num_results=15,
            query_type="HYBRID",
            filters_json=filters,
        )

        chunks = []
        if hasattr(result, "result") and result.result:
            cols = [c.name for c in (result.manifest.columns if result.manifest else [])]
            for row in (result.result.data_array or []):
                row_dict = dict(zip(cols, row))
                chunks.append({
                    "chunk_text": row_dict.get("chunk_to_retrieve", ""),
                    "document_id": row_dict.get("document_version_id", ""),
                    "page": row_dict.get("page_numbers"),
                    "section": row_dict.get("section_header"),
                    "contract_type": row_dict.get("contract_type"),
                    "state": row_dict.get("state_jurisdiction"),
                    "has_table": row_dict.get("contains_table", False),
                    "score": float(row_dict.get("score", 0)),
                })

        return {"chunks": chunks, "count": len(chunks)}
    except Exception as e:
        logger.error("ai_search_tool error: %s", e)
        return {"error": str(e), "chunks": [], "count": 0}


# ---------------------------------------------------------------------------
# Tool 3: ai_extract_on_demand
# ---------------------------------------------------------------------------
def ai_extract_on_demand(document_version_id: str, extraction_prompt: str) -> dict:
    """Extract a specific field from a document's parsed content on-demand.

    Used when the base extraction profile didn't capture a needed field.
    Uses parameterized SQL to prevent injection.

    Returns:
        {"extracted_value": ..., "confidence": ..., "citation": ...}
    """
    try:
        sql = f"""
        SELECT ai_query(
          'databricks-claude-haiku-4-5',
          CONCAT(
            'Extract the following from this healthcare contract text. ',
            'Return the value, your confidence (0.0-1.0), and the exact source text. ',
            'Field to extract: ', :extraction_prompt, '\n\n',
            'Document text: ', SUBSTR(parsed_content, 1, 50000)
          ),
          responseFormat => '{{"extracted_value": "STRING", "confidence": "FLOAT", "citation": "STRING"}}'
        ) AS result
        FROM {CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_parsed
        WHERE document_version_id = :doc_version_id
        """
        rows = _execute_sql(sql, parameters=[
            {"name": "doc_version_id", "value": document_version_id, "type": "STRING"},
            {"name": "extraction_prompt", "value": extraction_prompt[:500], "type": "STRING"},
        ])
        if rows:
            return json.loads(rows[0]["result"])
        return {"error": "Document not found", "extracted_value": None}
    except Exception as e:
        logger.error("ai_extract_on_demand error: %s", e)
        return {"error": str(e), "extracted_value": None}


# ---------------------------------------------------------------------------
# Tool 4: review_status_check
# ---------------------------------------------------------------------------
def review_status_check(document_version_id: str, field_name: str) -> dict:
    """Check the review/verification status of a specific extracted value.

    Uses parameterized SQL to prevent injection.

    Returns:
        {"review_status": ..., "reviewed_by": ..., "reviewed_at": ..., "corrections": [...]}
    """
    params = [
        {"name": "doc_version_id", "value": document_version_id, "type": "STRING"},
        {"name": "field_name", "value": field_name, "type": "STRING"},
    ]

    try:
        # Get current status from review_queue
        status_sql = f"""
        SELECT
          status AS review_status,
          assigned_to AS reviewed_by,
          CAST(updated_at AS STRING) AS reviewed_at,
          composite_score AS confidence
        FROM {APP_CATALOG}.{APP_SCHEMA}.review_queue
        WHERE document_version_id = :doc_version_id
          AND field_name = :field_name
        LIMIT 1
        """
        status_rows = _execute_sql(status_sql, parameters=params)

        # Get correction history from review_actions
        actions_sql = f"""
        SELECT
          action_type,
          previous_value,
          new_value,
          performed_by,
          CAST(performed_at AS STRING) AS performed_at
        FROM {APP_CATALOG}.{APP_SCHEMA}.review_actions
        WHERE document_version_id = :doc_version_id
          AND field_name = :field_name
        ORDER BY performed_at DESC
        LIMIT 10
        """
        action_rows = _execute_sql(actions_sql, parameters=params)

        result = {
            "review_status": "UNKNOWN",
            "reviewed_by": None,
            "reviewed_at": None,
            "confidence": None,
            "corrections": action_rows,
        }

        if status_rows:
            result.update(status_rows[0])

        return result
    except Exception as e:
        logger.error("review_status_check error: %s", e)
        return {"error": str(e), "review_status": "ERROR"}


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------
TOOL_MAP = {
    "sql_query": sql_query,
    "ai_search_tool": ai_search_tool,
    "ai_extract_on_demand": ai_extract_on_demand,
    "review_status_check": review_status_check,
}


def execute_tool(tool_name: str, arguments: dict) -> dict:
    """Dispatch a tool call by name."""
    fn = TOOL_MAP.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    return fn(**arguments)
