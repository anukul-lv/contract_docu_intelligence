"""FastAPI dependency injection providers."""
import logging
from functools import lru_cache
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState
from fastapi import Request

from backend.config import get_settings
from backend.models.domain import UserRole
from backend.services.circuit_breaker import sql_warehouse_breaker

logger = logging.getLogger("healthcontracts")


async def get_current_user(request: Request) -> dict:
    """FastAPI dependency that extracts user info from request state.

    AuthMiddleware must run first and populate request.state with:
      user_id, user_name, user_role, user_groups.

    Returns dict with email, role, and OAuth token (if present).
    """
    token_header = request.headers.get("Authorization", "")
    token = token_header.replace("Bearer ", "") if token_header.startswith("Bearer ") else None
    return {
        "email": getattr(request.state, "user_id", "anonymous"),
        "name": getattr(request.state, "user_name", "anonymous"),
        "role": getattr(request.state, "user_role", UserRole.VIEWER),
        "groups": getattr(request.state, "user_groups", []),
        "token": token,
    }


@lru_cache()
def get_workspace_client() -> WorkspaceClient:
    """Singleton WorkspaceClient. Databricks App provides auth automatically."""
    return WorkspaceClient()


async def execute_sql(
    statement: str,
    parameters: dict[str, Any] | None = None,
    catalog: str | None = None,
    schema: str | None = None,
) -> list[dict]:
    """Execute a SQL statement via the Statement Execution API.

    Uses the serverless SQL warehouse configured for the app.
    Returns rows as list of dicts.
    """
    if not sql_warehouse_breaker.can_execute():
        raise RuntimeError("SQL warehouse circuit breaker is OPEN — service unavailable")

    settings = get_settings()
    w = get_workspace_client()

    try:
        # Use the serverless SQL warehouse
        response = w.statement_execution.execute_statement(
            warehouse_id=settings.sql_warehouse_id,
            statement=statement,
            catalog=catalog or settings.app_catalog,
            schema=schema or settings.app_schema,
            parameters=[
                StatementParameterListItem(name=k, value=str(v))
                for k, v in (parameters or {}).items()
            ] or None,
        )

        if response.status and response.status.state == StatementState.FAILED:
            error_msg = (
                response.status.error.message
                if response.status.error
                else "Unknown SQL error"
            )
            sql_warehouse_breaker.record_failure()
            raise RuntimeError(f"SQL execution failed: {error_msg}")

        sql_warehouse_breaker.record_success()

        # Convert result to list of dicts
        if not response.result or not response.result.data_array:
            return []

        columns = [
            col.name for col in (response.manifest.schema.columns if response.manifest else [])
        ]
        return [
            dict(zip(columns, row))
            for row in response.result.data_array
        ]

    except RuntimeError:
        raise
    except Exception as exc:
        sql_warehouse_breaker.record_failure()
        logger.error("SQL execution error: %s", exc)
        raise RuntimeError(f"SQL execution error: {exc}") from exc
