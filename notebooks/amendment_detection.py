"""Amendment Detection — Detect amendment/supersession relationships during extraction.

Runs as a post-extraction step. For each newly extracted document, uses ai_extract
to identify references to existing contracts (amends, supersedes, restates).
Matches against existing documents using fuzzy name/ID matching and inserts
relationships into contracts_relationships.
"""
import json
import os
import uuid
from datetime import date

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

APP_CATALOG = os.environ.get("APP_CATALOG", "dev")
APP_SCHEMA = os.environ.get("APP_SCHEMA", "doc_intel")
CUSTOMER_CATALOG = os.environ.get("CUSTOMER_CATALOG", "dev")
CUSTOMER_SCHEMA = os.environ.get("CUSTOMER_SCHEMA", "doc_intel")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")

# New document IDs passed as job parameter
NEW_DOCUMENT_IDS = os.environ.get("NEW_DOCUMENT_IDS", "")  # comma-separated


def execute_sql(sql: str, parameters: list | None = None) -> list[dict]:
    """Execute SQL and return result rows.

    Parameters should be a list of
    databricks.sdk.service.sql.StatementParameterListItem when provided.
    """
    from databricks.sdk.service.sql import StatementParameterListItem

    result = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=sql,
        wait_timeout="120s",
        parameters=parameters,
    )
    if not result.result or not result.result.data_array:
        return []

    columns = [c.name for c in result.manifest.columns] if result.manifest else []
    return [dict(zip(columns, row)) for row in result.result.data_array]


def _params(**kwargs) -> list:
    """Build StatementParameterListItem list from keyword arguments."""
    from databricks.sdk.service.sql import StatementParameterListItem
    return [StatementParameterListItem(name=k, value=str(v)) for k, v in kwargs.items()]


def detect_references(document_version_id: str) -> list[dict]:
    """Use ai_extract to detect amendment references in a document."""
    sql = f"""
    SELECT ai_extract(
      parsed_content,
      '{{
        "amends_document_name": "STRING",
        "amends_document_id": "STRING",
        "supersedes_document_name": "STRING",
        "supersedes_document_id": "STRING",
        "restates_document_name": "STRING",
        "addendum_to_document_name": "STRING",
        "amendment_effective_date": "DATE",
        "amendment_relationship_type": "STRING"
      }}',
      enableConfidenceScores => true
    ) AS refs
    FROM {CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_parsed
    WHERE document_version_id = :doc_vid
    """
    rows = execute_sql(sql, parameters=_params(doc_vid=document_version_id))
    if not rows:
        return []

    refs = rows[0].get("refs")
    if isinstance(refs, str):
        refs = json.loads(refs)
    return [refs] if refs else []


def match_existing_document(reference_name: str | None, reference_id: str | None) -> str | None:
    """Fuzzy match an amendment reference against existing documents.

    Tries exact ID match first, then fuzzy name match.
    """
    if not reference_name and not reference_id:
        return None

    # Try exact ID match
    if reference_id:
        like_pattern = f"%{reference_id}%"
        rows = execute_sql(
            f"""
            SELECT document_version_id
            FROM {CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_parsed
            WHERE document_version_id = :ref_id
               OR file_name LIKE :ref_id_like
            LIMIT 1
            """,
            parameters=_params(ref_id=reference_id, ref_id_like=like_pattern),
        )
        if rows:
            return rows[0]["document_version_id"]

    # Try fuzzy name match
    if reference_name:
        name_pattern = f"%{reference_name}%"
        rows = execute_sql(
            f"""
            SELECT document_version_id, file_name
            FROM {CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_parsed
            WHERE LOWER(file_name) LIKE LOWER(:name_like)
               OR LOWER(doc_category) LIKE LOWER(:name_like)
            ORDER BY extraction_ts DESC
            LIMIT 1
            """,
            parameters=_params(name_like=name_pattern),
        )
        if rows:
            return rows[0]["document_version_id"]

    return None


def insert_relationship(
    parent_id: str,
    child_id: str,
    relationship_type: str,
    effective_date: str | None,
    notes: str | None,
    created_by: str,
) -> None:
    """Insert a new relationship into contracts_relationships."""
    rel_id = str(uuid.uuid4())

    execute_sql(
        f"""
        INSERT INTO {CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_relationships
        (relationship_id, parent_document_id, child_document_id, relationship_type,
         applicability_status, effective_date, supersession_notes, created_by)
        VALUES (
          :rel_id, :parent_id, :child_id, :rel_type,
          'ACTIVE', :eff_date, :notes, :created_by
        )
        """,
        parameters=_params(
            rel_id=rel_id,
            parent_id=parent_id,
            child_id=child_id,
            rel_type=relationship_type,
            eff_date=effective_date or "",
            notes=notes or "",
            created_by=created_by,
        ),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print("=" * 60)
print("AMENDMENT DETECTION")
print("=" * 60)

doc_ids = [d.strip() for d in NEW_DOCUMENT_IDS.split(",") if d.strip()]

if not doc_ids:
    # Process all documents not yet checked
    rows = execute_sql(f"""
    SELECT cp.document_version_id
    FROM {CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_parsed cp
    LEFT JOIN {CUSTOMER_CATALOG}.{CUSTOMER_SCHEMA}.contracts_relationships cr
      ON cp.document_version_id = cr.child_document_id
    WHERE cr.child_document_id IS NULL
    """)
    doc_ids = [r["document_version_id"] for r in rows]

print(f"  Documents to check: {len(doc_ids)}")

total_detected = 0
for doc_id in doc_ids:
    print(f"\n  Checking {doc_id}...")
    refs_list = detect_references(doc_id)

    for refs in refs_list:
        # Check each relationship type
        for ref_type, rel_type in [
            ("amends", "AMENDS"),
            ("supersedes", "SUPERSEDES"),
            ("restates", "RESTATES"),
            ("addendum_to", "ADDENDUM"),
        ]:
            ref_name = refs.get(f"{ref_type}_document_name")
            ref_id = refs.get(f"{ref_type}_document_id")

            if ref_name or ref_id:
                matched_id = match_existing_document(ref_name, ref_id)
                if matched_id:
                    print(f"    Found: {rel_type} → {matched_id}")
                    insert_relationship(
                        parent_id=matched_id,
                        child_id=doc_id,
                        relationship_type=rel_type,
                        effective_date=refs.get("amendment_effective_date"),
                        notes=f"Auto-detected: {ref_type} reference to '{ref_name or ref_id}'",
                        created_by="amendment_detection_pipeline",
                    )
                    total_detected += 1
                else:
                    print(f"    No match found for {rel_type}: {ref_name or ref_id}")

print(f"\n{'='*60}")
print(f"AMENDMENT DETECTION COMPLETE — {total_detected} relationships detected")
print(f"{'='*60}")
