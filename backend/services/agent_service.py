"""Agent service — FastAPI → Model Serving proxy with RAG retrieval pipeline.

Integrates the R2_02 retrieval pipeline before calling the agent endpoint:
  route classify → query rewrite → decompose → retrieve → rerank → assemble → agent.

Proxies the user's delegated OAuth token for UC row-filter evaluation.
All SQL uses parameterized queries to prevent injection.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

from databricks.sdk import WorkspaceClient

from backend.dependencies import execute_sql
from backend.config import get_settings
from backend.services.circuit_breaker import CircuitBreaker
from backend.services.context_assembler import assemble_context
from backend.services.feature_flag_cache import flag_cache
from backend.services.groundedness_checker import check_groundedness
from backend.services.hipaa_audit import audit_service
from backend.services.query_rewriter import decompose_query, rewrite_query
from backend.services.reranker import rerank_chunks
from backend.services.route_classifier import Route, RouteResult, classify_route
from backend.services.vector_service import VectorService

logger = logging.getLogger(__name__)

AGENT_ENDPOINT = os.environ.get("AGENT_SERVING_ENDPOINT", "healthcare_agent_endpoint")


@dataclass
class ChatResponse:
    message_id: str
    conversation_id: str
    content: str
    citations: list[dict]
    trust_badge: str
    route_used: str
    model_used: str
    token_count_input: int
    token_count_output: int
    latency_ms: int
    groundedness_score: float | None = None
    groundedness_warning: str | None = None


class AgentService:
    """Proxy between FastAPI and the agent Model Serving endpoint."""

    def __init__(self) -> None:
        self._client = WorkspaceClient()
        self._circuit = CircuitBreaker(
            name="agent_serving",
            failure_threshold=3,
            recovery_timeout_sec=60,
        )
        self._vector_service = VectorService()

    async def _get_or_create_session(
        self,
        conversation_id: str | None,
        user_email: str,
        scope_type: str = "all",
        scope_id: str | None = None,
    ) -> str:
        """Get existing session or create a new one. Uses parameterized SQL."""
        if conversation_id:
            return conversation_id

        new_id = str(uuid.uuid4())
        settings = get_settings()
        await execute_sql(
            f"""
            INSERT INTO {settings.app_catalog}.{settings.app_schema}.chat_sessions
            (conversation_id, scope_type, scope_id, created_by)
            VALUES (:conv_id, :scope_type, :scope_id, :user_email)
            """,
            parameters={
                "conv_id": new_id,
                "scope_type": scope_type,
                "scope_id": scope_id or "",
                "user_email": user_email,
            },
        )
        return new_id

    async def _save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        tool_calls: list[dict] | None = None,
        tool_results: list[dict] | None = None,
        citations: list[dict] | None = None,
        trust_badge: str | None = None,
        route_used: str | None = None,
        model_used: str | None = None,
        token_count_input: int = 0,
        token_count_output: int = 0,
        latency_ms: int = 0,
    ) -> str:
        """Persist a message to chat_messages table. Uses parameterized SQL."""
        msg_id = str(uuid.uuid4())
        settings = get_settings()

        await execute_sql(
            f"""
            INSERT INTO {settings.app_catalog}.{settings.app_schema}.chat_messages
            (message_id, conversation_id, role, content, tool_calls, tool_results,
             citations, trust_badge, route_used, model_used,
             token_count_input, token_count_output, latency_ms)
            VALUES (
              :msg_id, :conv_id, :role, :content,
              :tool_calls, :tool_results, :citations,
              :trust_badge, :route_used, :model_used,
              :input_tokens, :output_tokens, :latency
            )
            """,
            parameters={
                "msg_id": msg_id,
                "conv_id": conversation_id,
                "role": role,
                "content": content,
                "tool_calls": json.dumps(tool_calls) if tool_calls else "",
                "tool_results": json.dumps(tool_results) if tool_results else "",
                "citations": json.dumps(citations) if citations else "",
                "trust_badge": trust_badge or "",
                "route_used": route_used or "",
                "model_used": model_used or "",
                "input_tokens": str(token_count_input),
                "output_tokens": str(token_count_output),
                "latency": str(latency_ms),
            },
        )

        # Update session message count
        await execute_sql(
            f"""
            UPDATE {settings.app_catalog}.{settings.app_schema}.chat_sessions
            SET message_count = message_count + 1,
                last_message_at = current_timestamp()
            WHERE conversation_id = :conv_id
            """,
            parameters={"conv_id": conversation_id},
        )

        return msg_id

    async def _load_history(self, conversation_id: str, limit: int = 20) -> list[dict]:
        """Load conversation history for context. Uses parameterized SQL."""
        settings = get_settings()
        rows = await execute_sql(
            f"""
            SELECT role, content
            FROM {settings.app_catalog}.{settings.app_schema}.chat_messages
            WHERE conversation_id = :conv_id
            ORDER BY created_at DESC
            LIMIT CAST(:lim AS INT)
            """,
            parameters={"conv_id": conversation_id, "lim": str(limit)},
        )
        # Reverse to chronological order
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    # ------------------------------------------------------------------
    # R2_02 Retrieval pipeline integration
    # ------------------------------------------------------------------

    async def _run_retrieval_pipeline(
        self,
        query: str,
        route: RouteResult,
        scope_type: str = "all",
        scope_id: str | None = None,
    ) -> dict:
        """Execute the full R2_02 retrieval pipeline.

        Pipeline: rewrite → decompose (Route C) → retrieve → rerank → assemble.

        Returns:
            dict with context string, chunk_count, document_ids, rewrite info.
        """
        # Step 1: Query rewriting (Routes B and C)
        rewrite_result = None
        search_query = query
        if route.route in (Route.B, Route.C):
            try:
                use_llm = route.route == Route.C
                rewrite_result = await rewrite_query(query, use_llm=use_llm)
                search_query = rewrite_result.rewritten_query
            except Exception as e:
                logger.warning("Query rewrite failed, using original: %s", e)

        # Step 2: Decompose complex queries (Route C only)
        sub_queries = [search_query]
        if route.route == Route.C:
            try:
                decomp = await decompose_query(query)
                if len(decomp.sub_queries) >= 2:
                    sub_queries = decomp.sub_queries
            except Exception as e:
                logger.warning("Query decomposition failed: %s", e)

        # Step 3: Build metadata filters from session scope
        filters: dict[str, Any] | None = None
        if scope_type == "document" and scope_id:
            filters = {"document_version_id": scope_id}
        elif scope_type == "contract_type" and scope_id:
            filters = {"contract_type": scope_id}

        # Step 4: Retrieve chunks (fan out sub-queries)
        all_chunks = []
        is_hybrid = flag_cache.is_enabled("enable_hybrid_search")
        query_type = "HYBRID" if is_hybrid else "ANN"
        results_per_query = max(5, 20 // len(sub_queries))

        for sq in sub_queries:
            try:
                response = await self._vector_service.search(
                    query=sq,
                    filters=filters,
                    num_results=results_per_query,
                    query_type=query_type,
                )
                all_chunks.extend(response.results)
            except Exception as e:
                logger.warning("Vector search failed for sub-query: %s", e)

        # Step 5: Rerank (feature-flagged)
        try:
            rerank_result = await rerank_chunks(search_query, all_chunks)
            all_chunks = rerank_result.results
        except Exception as e:
            logger.warning("Reranker failed, using original order: %s", e)

        # Step 6: Assemble context
        target_doc_ids = [scope_id] if scope_type == "document" and scope_id else None
        assembly = assemble_context(
            chunks=all_chunks,
            query=query,
            target_document_ids=target_doc_ids,
        )

        logger.info(
            "Retrieval pipeline: route=%s, sub_queries=%d, chunks=%d, tokens=~%d",
            route.route.value, len(sub_queries), assembly.chunk_count,
            assembly.estimated_tokens,
        )

        return {
            "context": assembly.context,
            "chunk_count": assembly.chunk_count,
            "estimated_tokens": assembly.estimated_tokens,
            "document_ids": assembly.document_ids,
            "rewrite": {
                "original": query,
                "rewritten": search_query,
                "expansions": rewrite_result.expansions_applied if rewrite_result else [],
            } if rewrite_result else None,
            "sub_queries": sub_queries if len(sub_queries) > 1 else None,
        }

    async def chat(
        self,
        query: str,
        conversation_id: str | None,
        user_email: str,
        user_token: str | None = None,
        scope_type: str = "all",
        scope_id: str | None = None,
    ) -> ChatResponse:
        """Send a message through the retrieval pipeline and agent.

        Full flow:
        1. Get/create session, save user message
        2. Classify route (A/B/C) via R2_02 route_classifier
        3. Run retrieval pipeline (rewrite → decompose → search → rerank → assemble)
        4. Call agent endpoint with pre-assembled context + user OAuth token
        5. Groundedness check (feature-flagged)
        6. Save assistant message, audit log
        """
        start_ms = int(time.time() * 1000)

        # Step 1: Session + save user message
        conv_id = await self._get_or_create_session(
            conversation_id, user_email, scope_type, scope_id
        )
        await self._save_message(conv_id, "user", query)
        history = await self._load_history(conv_id)

        # Step 2: Route classification (R2_02)
        route = classify_route(query)
        logger.info("Route: %s (%s)", route.route.value, route.reason)

        # Step 3: Retrieval pipeline (R2_02)
        retrieval = await self._run_retrieval_pipeline(
            query, route, scope_type, scope_id
        )

        # Step 4: Call agent endpoint with pre-assembled context
        agent_input = {
            "query": query,
            "history": history,
            "context": retrieval["context"],
            "route": route.route.value,
            "metadata": {
                "scope_type": scope_type,
                "scope_id": scope_id,
                "chunk_count": retrieval["chunk_count"],
                "rewrite": retrieval.get("rewrite"),
                "sub_queries": retrieval.get("sub_queries"),
            },
        }

        try:
            async def _call_agent() -> dict:
                extra_headers: dict[str, str] | None = None
                if user_token:
                    extra_headers = {"Authorization": f"Bearer {user_token}"}
                return self._client.serving_endpoints.query(
                    name=AGENT_ENDPOINT,
                    inputs=agent_input,
                    extra_headers=extra_headers,
                )

            result = await self._circuit.call(_call_agent)
            if hasattr(result, "as_dict"):
                result = result.as_dict()
            if isinstance(result, dict) and "predictions" in result:
                result = result["predictions"]
                if isinstance(result, list) and result:
                    result = result[0]
        except Exception as e:
            logger.error("Agent endpoint call failed: %s", e)
            elapsed = int(time.time() * 1000) - start_ms
            error_msg = "I'm sorry, I'm unable to process your request right now. Please try again."
            await self._save_message(conv_id, "assistant", error_msg, latency_ms=elapsed)
            return ChatResponse(
                message_id=str(uuid.uuid4()),
                conversation_id=conv_id,
                content=error_msg,
                citations=[],
                trust_badge="ERROR",
                route_used=route.route.value,
                model_used="",
                token_count_input=0,
                token_count_output=0,
                latency_ms=elapsed,
            )

        content = result.get("response", "")
        model_used = result.get("model_used", "")
        trust_badge = result.get("trust_badge", "AI_EXTRACTED")
        tool_calls = result.get("tool_calls", [])
        tool_results = result.get("tool_results", [])
        citations = result.get("citations", [])
        input_tokens = result.get("token_count_input", 0)
        output_tokens = result.get("token_count_output", 0)

        # Step 5: Groundedness check (feature-flagged)
        groundedness_score = None
        groundedness_warning = None
        if flag_cache.is_enabled("enable_inline_groundedness"):
            gs = await check_groundedness(query, content, tool_results)
            groundedness_score = gs.score
            if gs.score < 0.7:
                groundedness_warning = "This answer may contain unsupported claims."

        elapsed = int(time.time() * 1000) - start_ms

        # Save assistant message
        msg_id = await self._save_message(
            conv_id, "assistant", content,
            tool_calls=tool_calls,
            tool_results=tool_results,
            citations=citations,
            trust_badge=trust_badge,
            route_used=route.route.value,
            model_used=model_used,
            token_count_input=input_tokens,
            token_count_output=output_tokens,
            latency_ms=elapsed,
        )

        # Audit
        await audit_service.log_event(
            event_type="CHAT_MESSAGE",
            user_identity=user_email,
            user_role="VIEWER",
            resource_type="chat",
            resource_id=conv_id,
            action="query",
        )

        return ChatResponse(
            message_id=msg_id,
            conversation_id=conv_id,
            content=content,
            citations=citations,
            trust_badge=trust_badge,
            route_used=route.route.value,
            model_used=model_used,
            token_count_input=input_tokens,
            token_count_output=output_tokens,
            latency_ms=elapsed,
            groundedness_score=groundedness_score,
            groundedness_warning=groundedness_warning,
        )
