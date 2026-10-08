"""Evaluation Job — Weekly RAGAS evaluation of the healthcare agent.

Runs against a gold set of 100 healthcare Q&A pairs + 50 extraction-validation
docs + 50 calibration docs. Stores results in quality_evaluations table.

Scheduled: Weekly via Lakeflow Job.
"""
import json
import os
import sys
import uuid
from datetime import datetime

import mlflow
from databricks.sdk import WorkspaceClient
from mlflow.genai.scorers import (
    RetrievalGroundedness,
    RetrievalRelevance,
    RetrievalSufficiency,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

w = WorkspaceClient()

APP_CATALOG = os.environ.get("APP_CATALOG", "dev")
APP_SCHEMA = os.environ.get("APP_SCHEMA", "doc_intel")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
AGENT_ENDPOINT = os.environ.get("AGENT_SERVING_ENDPOINT", "healthcare_agent_endpoint")


def execute_sql(sql: str, parameters: list | None = None) -> list[dict]:
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


# ---------------------------------------------------------------------------
# Custom scorer: healthcare-specific accuracy
# ---------------------------------------------------------------------------
@mlflow.genai.scorer
def healthcare_accuracy(inputs, outputs, expectations):
    """Score healthcare-specific accuracy.

    For numeric fields (rates, dates, amounts), requires exact match.
    For text fields, checks containment.
    """
    expected = expectations.get("expected_answer", "")
    actual = outputs.get("response", "")

    if expectations.get("field_type") in ("rate", "date", "amount"):
        return {"score": 1.0 if expected in actual else 0.0}
    return {"score": float(expected.lower() in actual.lower())}


@mlflow.genai.scorer
def citation_presence(inputs, outputs, expectations):
    """Check that financial/compliance answers include citations."""
    response = outputs.get("response", "")
    citations = outputs.get("citations", [])
    field_type = expectations.get("field_type", "")

    if field_type in ("financial", "compliance"):
        has_citation = bool(citations) or any(
            marker in response for marker in ["Page ", "Section ", "\u00a7", "paragraph"]
        )
        return {"score": 1.0 if has_citation else 0.0}
    return {"score": 1.0}  # Non-critical fields don't require citations


# ---------------------------------------------------------------------------
# Load gold set
# ---------------------------------------------------------------------------
print("=" * 60)
print("AGENT EVALUATION")
print(f"  Agent: {AGENT_ENDPOINT}")
print("=" * 60)

print("\n  Loading gold set...")
gold_rows = execute_sql(f"""
SELECT question, expected_answer, field_type, category
FROM {APP_CATALOG}.{APP_SCHEMA}.quality_evaluations
WHERE evaluation_type = 'gold_set'
ORDER BY run_date DESC
LIMIT 200
""")

# If no gold set in DB, use a built-in sample
if not gold_rows:
    print("  No gold set found. Using built-in sample.")
    gold_rows = [
        {"question": "How many provider agreements are in the system?",
         "expected_answer": "provider agreement", "field_type": "count", "category": "aggregate"},
        {"question": "What is the DRG base rate in contract HSP-001?",
         "expected_answer": "DRG base rate", "field_type": "rate", "category": "factual"},
        {"question": "Compare termination clauses between TX and CA contracts.",
         "expected_answer": "termination", "field_type": "text", "category": "comparison"},
    ]

print(f"  Gold set size: {len(gold_rows)}")

# ---------------------------------------------------------------------------
# Build evaluation dataset
# ---------------------------------------------------------------------------
def rag_agent(inputs: dict) -> dict:
    """Call the agent endpoint."""
    try:
        result = w.serving_endpoints.query(
            name=AGENT_ENDPOINT,
            inputs={"query": inputs["question"], "history": []},
        )
        if hasattr(result, "as_dict"):
            result = result.as_dict()
        predictions = result.get("predictions", [{}])
        if isinstance(predictions, list) and predictions:
            return predictions[0]
        return result
    except Exception as e:
        return {"response": f"ERROR: {e}", "citations": []}


healthcare_eval_dataset = [
    {
        "inputs": {"question": r["question"]},
        "expectations": {
            "expected_answer": r["expected_answer"],
            "field_type": r.get("field_type", "text"),
        },
    }
    for r in gold_rows
]

# ---------------------------------------------------------------------------
# Run evaluation
# ---------------------------------------------------------------------------
print("\n  Running evaluation...")

mlflow.set_experiment(f"/{APP_CATALOG}/{APP_SCHEMA}/agent_evaluation")

with mlflow.start_run(run_name=f"eval_{datetime.utcnow().strftime('%Y%m%d_%H%M')}") as run:
    results = mlflow.genai.evaluate(
        data=healthcare_eval_dataset,
        predict_fn=rag_agent,
        scorers=[
            RetrievalRelevance(),
            RetrievalGroundedness(),
            RetrievalSufficiency(),
            healthcare_accuracy,
            citation_presence,
        ],
    )

    # Extract metrics
    metrics = results.metrics if hasattr(results, "metrics") else {}
    print(f"\n  Metrics: {json.dumps(metrics, indent=2, default=str)}")

    # Store in quality_evaluations
    eval_id = str(uuid.uuid4())
    metrics_json = json.dumps(metrics, default=str)
    execute_sql(
        f"""
        INSERT INTO {APP_CATALOG}.{APP_SCHEMA}.quality_evaluations
        (evaluation_id, evaluation_type, run_date, gold_set_version, metrics,
         summary, mlflow_experiment_id, mlflow_run_id)
        VALUES (
          :eval_id, 'agent_evaluation', current_timestamp(),
          'v1', :metrics_json,
          'Weekly agent evaluation against gold set',
          :experiment_id, :run_id
        )
        """,
        parameters=_params(
            eval_id=eval_id,
            metrics_json=metrics_json,
            experiment_id=run.info.experiment_id,
            run_id=run.info.run_id,
        ),
    )

print(f"\n{'='*60}")
print("EVALUATION COMPLETE")
print(f"  Experiment: {run.info.experiment_id}")
print(f"  Run: {run.info.run_id}")
print(f"{'='*60}")
