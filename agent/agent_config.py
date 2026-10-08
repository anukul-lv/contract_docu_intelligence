"""Agent configuration — System prompt, model routing, and tool definitions.

Version-controlled via DABs. Prompt changes require RAGAS re-evaluation
before production deployment.
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
APP_CATALOG = os.environ.get("APP_CATALOG", "dev")
APP_SCHEMA = os.environ.get("APP_SCHEMA", "doc_intel")
CUSTOMER_CATALOG = os.environ.get("CUSTOMER_CATALOG", "dev")
CUSTOMER_SCHEMA = os.environ.get("CUSTOMER_SCHEMA", "doc_intel")
AI_GATEWAY_CHAT_ENDPOINT = os.environ.get("AI_GATEWAY_CHAT_ENDPOINT", "databricks-claude-sonnet-4")
AI_GATEWAY_EMBEDDING_ENDPOINT = os.environ.get("AI_GATEWAY_EMBEDDING_ENDPOINT", "databricks-gte-large-en")
AI_SEARCH_ENDPOINT = os.environ.get("AI_SEARCH_ENDPOINT", "dev_healthcare_search_endpoint")

# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """You are a healthcare contract analysis assistant for a US health insurance company.
You have access to {contract_count} healthcare contracts stored in Delta tables.

Table schema:
{schema_summary}

Key statistics:
- {contract_count} total contracts ({type_breakdown})
- Date range: {earliest_date} to {latest_date}
- States covered: {states_list}

Rules:
1. ALWAYS cite the specific document, page, and passage for every factual claim.
2. ALWAYS check verification_status — distinguish AI-extracted vs. human-verified data.
3. NEVER fabricate contract terms, dollar amounts, dates, or regulatory citations.
4. For financial questions, specify the reimbursement methodology (DRG, per diem, capitation, etc.).
5. For regulatory questions, cite the specific CFR section or state regulation.
6. If data is insufficient, say so and suggest specific actions (enrichment, upload, rephrase).
7. Use healthcare terminology: PMPM, DRG, MLR, HEDIS, Star Rating, BAA, etc.
8. SQL queries are READ-ONLY. Never generate INSERT, UPDATE, DELETE, DROP, or DDL.
9. Always include a trust badge: VERIFIED (human-reviewed), AI_EXTRACTED (AI-only), or MIXED.
10. For amendment questions, trace the full supersession chain to find current-in-force values.
"""

# ---------------------------------------------------------------------------
# Model routing
# ---------------------------------------------------------------------------
MODEL_ROUTING = {
    "complex_reasoning": {
        "primary": "databricks-claude-sonnet-4",
        "fallback": "databricks-gemini-flash",
    },
    "query_rewriting": {
        "primary": "databricks-claude-haiku-4-5",
        "fallback": "databricks-gemini-flash",
    },
    "simple_response": {
        "primary": "databricks-gemini-flash",
        "fallback": "databricks-claude-haiku-4-5",
    },
    "embeddings": {
        "primary": "databricks-gte-large-en",
        "fallback": None,
    },
}

# ---------------------------------------------------------------------------
# Tool definitions (for MLflow agent)
# ---------------------------------------------------------------------------
TOOL_DEFINITIONS = [
    {
        "name": "sql_query",
        "description": (
            "Execute a READ-ONLY SQL query against the contracts_current table. "
            "Use for aggregate questions (totals, counts, averages), KPIs, and "
            "structured data lookups. The query MUST be a SELECT statement only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A SQL SELECT statement against contracts_current.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "ai_search_tool",
        "description": (
            "Search contract document chunks using hybrid retrieval (BM25 + vector). "
            "Use for factual lookups, clause searches, and finding specific contract terms. "
            "Supports metadata filters: contract_type, state_jurisdiction, date ranges, "
            "reimbursement_method, and contains_table."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
                "filters": {
                    "type": "object",
                    "description": "Optional metadata filters.",
                    "properties": {
                        "contract_type": {"type": "string"},
                        "state_jurisdiction": {"type": "string"},
                        "contains_table": {"type": "boolean"},
                    },
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "ai_extract_on_demand",
        "description": (
            "Extract a specific field from a document's parsed content on-demand. "
            "Use when the base extraction profile didn't capture a needed field."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "document_version_id": {
                    "type": "string",
                    "description": "The document to extract from.",
                },
                "extraction_prompt": {
                    "type": "string",
                    "description": "What to extract (e.g., 'termination for convenience clause details').",
                },
            },
            "required": ["document_version_id", "extraction_prompt"],
        },
    },
    {
        "name": "review_status_check",
        "description": (
            "Check the review/verification status of a specific extracted value. "
            "Use to determine if a value is VERIFIED (human-reviewed) or AI_EXTRACTED."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "document_version_id": {
                    "type": "string",
                    "description": "The document to check.",
                },
                "field_name": {
                    "type": "string",
                    "description": "The field to check status for.",
                },
            },
            "required": ["document_version_id", "field_name"],
        },
    },
]

# ---------------------------------------------------------------------------
# Groundedness thresholds
# ---------------------------------------------------------------------------
GROUNDEDNESS_THRESHOLD = 0.7  # Below this, append warning badge
GROUNDEDNESS_ENABLED_FIELD_CLASSES = {
    "critical_financial",
    "critical_compliance",
}

# ---------------------------------------------------------------------------
# Guardrail policy
# ---------------------------------------------------------------------------
GUARDRAIL_POLICY = {
    "safety_filtering": True,
    "pii_detection": {
        "block": ["SSN", "credit_card"],
        "mask": ["email", "phone"],
    },
    "topic_containment": "healthcare_contracts_only",
    "citation_requirement": ["financial", "compliance"],
}
