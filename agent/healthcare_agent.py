"""Healthcare Contract Agent — MLflow pyfunc agent definition.

Deployed as an MLflow pyfunc model on Model Serving, routed through AI Gateway.
Receives pre-assembled context from the FastAPI retrieval pipeline (agent_service.py)
and uses LLM tool-calling for dynamic follow-up queries.

Input contract:
    query: str              -- user's question
    history: list[dict]     -- conversation history [{role, content}]
    context: str            -- pre-assembled context from R2_02 retrieval pipeline
    route: str              -- "A", "B", or "C" from route_classifier
    metadata: dict          -- scope, chunk_count, rewrite info
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import mlflow
from databricks.sdk import WorkspaceClient

from agent_config import (
    AI_GATEWAY_CHAT_ENDPOINT,
    GROUNDEDNESS_ENABLED_FIELD_CLASSES,
    GROUNDEDNESS_THRESHOLD,
    MODEL_ROUTING,
    SYSTEM_PROMPT_TEMPLATE,
    TOOL_DEFINITIONS,
)
from agent_tools import execute_tool

logger = logging.getLogger(__name__)


class HealthcareContractAgent(mlflow.pyfunc.PythonModel):
    """MLflow pyfunc agent for healthcare contract analysis."""

    def load_context(self, context: mlflow.pyfunc.PythonModelContext) -> None:
        """Load system prompt, tool definitions, model config."""
        self._client = WorkspaceClient()
        self._warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
        self._system_prompt = self._build_system_prompt()
        self._tools = TOOL_DEFINITIONS
        self._max_tool_rounds = 5

    def _build_system_prompt(self) -> str:
        """Build system prompt with live corpus statistics."""
        try:
            cc = os.environ.get("CUSTOMER_CATALOG", "dev")
            cs = os.environ.get("CUSTOMER_SCHEMA", "doc_intel")
            result = self._client.statement_execution.execute_statement(
                warehouse_id=self._warehouse_id,
                statement=f"""
                SELECT
                  COUNT(*) AS cnt,
                  COUNT(DISTINCT doc_category) AS type_count,
                  MIN(effective_date) AS earliest,
                  MAX(effective_date) AS latest,
                  COLLECT_SET(state_jurisdiction) AS states
                FROM {cc}.{cs}.contracts_current
                """,
                wait_timeout="30s",
            )
            if result.result and result.result.data_array:
                row = result.result.data_array[0]
                return SYSTEM_PROMPT_TEMPLATE.format(
                    contract_count=row[0] or 0,
                    schema_summary="contracts_current, contracts_parsed, document_chunks",
                    type_breakdown=f"{row[1] or 0} types",
                    earliest_date=row[2] or "N/A",
                    latest_date=row[3] or "N/A",
                    states_list=str(row[4] or []),
                )
        except Exception as e:
            logger.warning("Failed to build dynamic prompt: %s", e)

        return SYSTEM_PROMPT_TEMPLATE.format(
            contract_count="N/A",
            schema_summary="contracts_current, contracts_parsed, document_chunks",
            type_breakdown="N/A",
            earliest_date="N/A",
            latest_date="N/A",
            states_list="N/A",
        )

    def _call_llm(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
    ) -> dict:
        """Call LLM via AI Gateway."""
        endpoint = model or AI_GATEWAY_CHAT_ENDPOINT
        payload: dict[str, Any] = {
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.1,
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]

        response = self._client.serving_endpoints.query(
            name=endpoint,
            **payload,
        )
        return response.as_dict() if hasattr(response, "as_dict") else response

    def _select_model(self, route: str) -> str:
        """Select the appropriate LLM based on route."""
        if route == "C":
            return MODEL_ROUTING["complex_reasoning"]["primary"]
        elif route == "A":
            return MODEL_ROUTING["simple_response"]["primary"]
        return MODEL_ROUTING["simple_response"]["primary"]

    def predict(
        self,
        context: mlflow.pyfunc.PythonModelContext,
        model_input: dict,
        params: dict | None = None,
    ) -> dict:
        """Process a chat message with pre-assembled context.

        The retrieval pipeline (route → rewrite → decompose → retrieve →
        rerank → assemble) runs in agent_service.py BEFORE this is called.
        This method receives the assembled context and:
        1. Builds messages with system prompt + context
        2. Calls LLM with tools for dynamic follow-up
        3. Determines trust badge
        """
        start_time = time.time()

        # Extract input
        query = model_input.get("query", "")
        conversation_history = model_input.get("history", [])
        retrieved_context = model_input.get("context", "")
        route = model_input.get("route", "B")
        metadata = model_input.get("metadata", {})
        model = self._select_model(route)

        # Build messages with retrieved context injected into system prompt
        system_content = self._system_prompt
        if retrieved_context:
            system_content += (
                "\n\n--- Retrieved Contract Context ---\n"
                f"{retrieved_context}\n"
                "--- End Context ---\n"
            )

        messages = [
            {"role": "system", "content": system_content},
            *conversation_history,
            {"role": "user", "content": query},
        ]

        # Step 3-4: LLM call with tool use loop
        tool_calls_made: list[dict] = []
        tool_results: list[dict] = []
        final_response = ""

        for round_num in range(self._max_tool_rounds):
            response = self._call_llm(messages, model=model, tools=self._tools)

            choices = response.get("choices", [{}])
            if not choices:
                break

            message = choices[0].get("message", {})
            finish_reason = choices[0].get("finish_reason", "stop")

            if finish_reason == "tool_calls" and message.get("tool_calls"):
                # Execute each tool call
                messages.append(message)
                for tc in message["tool_calls"]:
                    fn = tc.get("function", {})
                    tool_name = fn.get("name", "")
                    arguments = json.loads(fn.get("arguments", "{}"))

                    result = execute_tool(tool_name, arguments)
                    tool_calls_made.append({"tool": tool_name, "args": arguments})
                    tool_results.append({"tool": tool_name, "result": result})

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(result),
                    })
            else:
                final_response = message.get("content", "")
                break
        else:
            # Max rounds reached — get final response without tools
            response = self._call_llm(messages, model=model)
            choices = response.get("choices", [{}])
            if choices:
                final_response = choices[0].get("message", {}).get("content", "")

        # Step 5: Token usage
        usage = response.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        # Step 6: Determine trust badge
        trust_badge = self._determine_trust_badge(tool_results)

        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "response": final_response,
            "route_used": route,
            "model_used": model,
            "trust_badge": trust_badge,
            "tool_calls": tool_calls_made,
            "tool_results": tool_results,
            "token_count_input": input_tokens,
            "token_count_output": output_tokens,
            "latency_ms": elapsed_ms,
        }

    def _determine_trust_badge(self, tool_results: list[dict]) -> str:
        """Determine the trust badge based on verification status of data used."""
        has_verified = False
        has_ai_only = False

        for tr in tool_results:
            result = tr.get("result", {})
            status = result.get("review_status", "")
            if status in ("APPROVED", "CORRECTED", "VERIFIED"):
                has_verified = True
            elif status in ("PENDING", "AI_EXTRACTED", ""):
                has_ai_only = True

        if has_verified and has_ai_only:
            return "MIXED"
        elif has_verified:
            return "VERIFIED"
        return "AI_EXTRACTED"
