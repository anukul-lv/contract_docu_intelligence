"""Nightly table maintenance — OPTIMIZE + VACUUM for all R1 tables.

Scheduled via Lakeflow Jobs to run nightly at 2 AM.
RETAIN 168 HOURS (7 days) for time-travel support.
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
RETAIN_HOURS = 168  # 7 days

# All 12 R1 tables
APP_TABLES = [
    "feature_flags",
    "confidence_thresholds",
    "guardrail_policy",
    "cost_tracking",
    "ingestion_jobs",
    "ingestion_job_events",
    "review_queue",
    "review_actions",
    "hipaa_audit_log",
    "phi_vault",
]

CUSTOMER_TABLES = [
    "contracts_parsed",
    "contracts_current",
]

# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------
start_ts = datetime.now(timezone.utc)
print(f"=== Table maintenance started at {start_ts.isoformat()} ===")

succeeded = 0
failed = 0


def maintain_table(catalog: str, schema: str, table: str) -> None:
    """Run OPTIMIZE and VACUUM on a single table."""
    global succeeded, failed
    fqn = f"{catalog}.{schema}.{table}"
    try:
        print(f"\n--- {fqn} ---")
        print(f"  OPTIMIZE...")
        spark.sql(f"OPTIMIZE {fqn}")
        print(f"  VACUUM RETAIN {RETAIN_HOURS} HOURS...")
        spark.sql(f"VACUUM {fqn} RETAIN {RETAIN_HOURS} HOURS")
        print(f"  Done.")
        succeeded += 1
    except Exception as exc:
        print(f"  ERROR: {exc}")
        failed += 1


# App schema tables
for table in APP_TABLES:
    maintain_table(APP_CATALOG, APP_SCHEMA, table)

# Customer schema tables
for table in CUSTOMER_TABLES:
    maintain_table(CUSTOMER_CATALOG, CUSTOMER_SCHEMA, table)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
end_ts = datetime.now(timezone.utc)
elapsed = (end_ts - start_ts).total_seconds()

print(f"\n=== Maintenance complete ===")
print(f"  Succeeded: {succeeded}")
print(f"  Failed:    {failed}")
print(f"  Duration:  {elapsed:.1f}s")

if failed > 0:
    raise RuntimeError(f"{failed} table(s) failed maintenance")
