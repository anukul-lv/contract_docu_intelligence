"""Per-run cost estimation and tracking.

Estimates DBU and token costs before extraction starts and records
actual costs after completion. Writes to cost_tracking table.
"""
import logging
import uuid
from datetime import date

from backend.config import get_settings
from backend.dependencies import execute_sql

logger = logging.getLogger("healthcontracts")

# ---------------------------------------------------------------------------
# Cost model constants (Azure pricing, approximate)
# ---------------------------------------------------------------------------
# ai_parse_document: ~0.02 DBU per page, ~$0.07 per DBU
_PARSE_DBU_PER_PAGE = 0.02
# ai_extract: ~500 tokens per field × ~40 fields = 20K tokens per doc
_EXTRACT_TOKENS_PER_DOC = 20_000
# ai_classify: ~200 tokens per doc
_CLASSIFY_TOKENS_PER_DOC = 200
# Token pricing (input tokens for GPT-4o equivalent)
_USD_PER_1K_TOKENS = 0.005
# DBU pricing
_USD_PER_DBU = 0.07
# Average pages per document (for estimation before actual count is known)
_AVG_PAGES_PER_DOC = 25


class CostTracker:
    """Estimate and track extraction costs."""

    def estimate_run_cost(
        self,
        num_documents: int,
        avg_pages: int | None = None,
    ) -> dict:
        """Return pre-run cost estimate shown to user before extraction starts."""
        pages = (avg_pages or _AVG_PAGES_PER_DOC) * num_documents

        parse_dbu = pages * _PARSE_DBU_PER_PAGE
        parse_usd = parse_dbu * _USD_PER_DBU

        extract_tokens = num_documents * _EXTRACT_TOKENS_PER_DOC
        classify_tokens = num_documents * _CLASSIFY_TOKENS_PER_DOC
        total_tokens = extract_tokens + classify_tokens
        token_usd = (total_tokens / 1000) * _USD_PER_1K_TOKENS

        total_usd = parse_usd + token_usd
        # Estimated duration: ~8 seconds per doc (parse + extract + classify)
        est_duration_min = round((num_documents * 8) / 60, 1)

        return {
            "estimated_cost_usd": round(total_usd, 2),
            "estimated_dbu": round(parse_dbu, 2),
            "estimated_tokens": total_tokens,
            "estimated_duration_min": est_duration_min,
            "breakdown": {
                "parse_usd": round(parse_usd, 2),
                "ai_tokens_usd": round(token_usd, 2),
                "num_documents": num_documents,
                "est_total_pages": pages,
            },
        }

    async def record_cost(
        self,
        run_id: str,
        cost_category: str,
        dbu_consumed: float | None = None,
        token_count: int | None = None,
        model_used: str | None = None,
        estimated_usd: float | None = None,
    ) -> None:
        """Write an actual cost record to the cost_tracking table."""
        settings = get_settings()
        cost_id = str(uuid.uuid4())

        await execute_sql(
            f"INSERT INTO {settings.app_catalog}.{settings.app_schema}.cost_tracking "
            f"(cost_id, run_id, cost_category, dbu_consumed, token_count, "
            f"model_used, estimated_usd, tracking_date, created_at) VALUES ("
            f":cost_id, :run_id, :cost_category, "
            f":dbu_consumed, :token_count, :model_used, "
            f":estimated_usd, CURRENT_DATE(), current_timestamp())",
            parameters={
                "cost_id": cost_id,
                "run_id": run_id,
                "cost_category": cost_category,
                "dbu_consumed": str(dbu_consumed) if dbu_consumed is not None else "",
                "token_count": str(token_count) if token_count is not None else "",
                "model_used": model_used or "",
                "estimated_usd": str(estimated_usd) if estimated_usd is not None else "",
            },
        )


# Singleton
cost_tracker = CostTracker()
