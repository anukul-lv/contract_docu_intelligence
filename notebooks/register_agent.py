"""Register Agent — Register the healthcare agent as an MLflow model in Unity Catalog.

Registers the HealthcareContractAgent pyfunc model in the ML registry,
allowing it to be deployed as a Model Serving endpoint.

Run once after agent code is finalized, then deploy the endpoint.
"""
import os
import sys

import mlflow

# Ensure agent package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.healthcare_agent import HealthcareContractAgent

APP_CATALOG = os.environ.get("APP_CATALOG", "dev")
APP_SCHEMA = os.environ.get("APP_SCHEMA", "doc_intel")

REGISTERED_MODEL_NAME = f"{APP_CATALOG}.{APP_SCHEMA}.healthcare_agent"

print("=" * 60)
print("AGENT REGISTRATION")
print(f"  Model: {REGISTERED_MODEL_NAME}")
print("=" * 60)

# Set experiment
mlflow.set_experiment(f"/{APP_CATALOG}/{APP_SCHEMA}/healthcare_agent")

with mlflow.start_run(run_name="register_healthcare_agent") as run:
    # Log the pyfunc model
    mlflow.pyfunc.log_model(
        artifact_path="healthcare_agent",
        python_model=HealthcareContractAgent(),
        registered_model_name=REGISTERED_MODEL_NAME,
        pip_requirements=[
            "databricks-sdk>=0.30.0",
            "mlflow>=2.15.0",
        ],
        input_example={
            "query": "What is the average DRG base rate across all hospital contracts?",
            "history": [],
        },
    )

    # Log agent config as params
    mlflow.log_params({
        "model_type": "healthcare_contract_agent",
        "tool_count": 4,
        "max_tool_rounds": 5,
        "groundedness_threshold": 0.7,
    })

    print(f"\n  Run ID: {run.info.run_id}")
    print(f"  Model registered as: {REGISTERED_MODEL_NAME}")

print(f"\n{'='*60}")
print("AGENT REGISTRATION COMPLETE")
print(f"{'='*60}")
print(f"\nNext steps:")
print(f"  1. Deploy Model Serving endpoint:")
print(f"     databricks serving-endpoints create --json ...")
print(f"  2. Configure AI Gateway routing")
print(f"  3. Run evaluation_job.py against gold set")
