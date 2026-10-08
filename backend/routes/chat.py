"""Chat routes — AI Chat API with SSE streaming.

Endpoints:
  POST /api/v1/chat/conversations — Create a new conversation
  POST /api/v1/chat/conversations/{id}/messages — Send message (SSE stream)
  GET  /api/v1/chat/conversations — List conversations
  DELETE /api/v1/chat/conversations/{id} — Soft delete
  POST /api/v1/chat/messages/{id}/feedback — Rating + comment
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.dependencies import get_current_user
from backend.middleware.auth import require_role
from backend.middleware.rate_limiter import rate_limiter
from backend.models.domain import UserRole
from backend.models.requests import ChatCreateRequest, ChatFeedbackRequest, ChatMessageRequest
from backend.models.responses import APIResponse
from backend.services.agent_service import AgentService
from backend.services.cache_service import CacheService
from backend.services.chat_service import ChatService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.post("/conversations")
async def create_conversation(
    body: ChatCreateRequest,
    user: dict = Depends(get_current_user),
    _role: str = Depends(require_role(UserRole.VIEWER)),
) -> APIResponse:
    """Create a new chat conversation."""
    svc = ChatService()
    try:
        result = await svc.create_conversation(
            user_email=user["email"],
            scope_type=body.scope_type,
            scope_id=body.scope_id,
        )
        # Transform to camelCase for the React frontend
        return APIResponse(status="success", data={
            "conversation_id": result.get("conversation_id", ""),
            "conversationId": result.get("conversation_id", ""),
            "scopeType": result.get("scope_type", "all"),
        })
    except ValueError as e:
        raise HTTPException(status_code=429, detail=str(e))


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: ChatMessageRequest,
    user: dict = Depends(get_current_user),
    _role: str = Depends(require_role(UserRole.VIEWER)),
) -> StreamingResponse:
    """Send a message and receive SSE stream.

    SSE event types:
    - chunk: { text: "..." }
    - citation: { document, page, text, trust_badge }
    - tool_use: { tool_name, input, output }
    - metadata: { route_used, model_used, latency_ms, trust_badge }
    - done: { message_id }
    """
    # Rate limit check
    allowed, retry_after = rate_limiter.check(user["email"], "chat_messages")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Chat rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    async def event_stream():
        cache_svc = CacheService()
        agent_svc = AgentService()

        # Step 1: Check semantic cache
        cached = await cache_svc.lookup(
            query=body.content,
            scope_type="all",
            scope_id=None,
        )

        if cached:
            # Cache hit — stream cached answer
            yield f"event: chunk\ndata: {json.dumps({'text': cached.get('content', '')})}\n\n"
            for cit in cached.get("citations", []):
                yield f"event: citation\ndata: {json.dumps(cit)}\n\n"
            yield f"event: metadata\ndata: {json.dumps({'route_used': 'cache', 'trust_badge': cached.get('trust_badge', 'AI_EXTRACTED')})}\n\n"
            yield f"event: done\ndata: {json.dumps({'message_id': 'cached', 'cached': True})}\n\n"
            return

        # Step 2: Call agent with scope from conversation
        # Extract OAuth token for UC row-filter passthrough
        response = await agent_svc.chat(
            query=body.content,
            conversation_id=conversation_id,
            user_email=user["email"],
            user_token=user.get("token"),
        )

        # Stream response
        yield f"event: chunk\ndata: {json.dumps({'text': response.content})}\n\n"

        for cit in response.citations:
            yield f"event: citation\ndata: {json.dumps(cit)}\n\n"

        yield f"event: metadata\ndata: {json.dumps({'route_used': response.route_used, 'model_used': response.model_used, 'latency_ms': response.latency_ms, 'trust_badge': response.trust_badge, 'token_count_input': response.token_count_input, 'token_count_output': response.token_count_output, 'groundedness_score': response.groundedness_score, 'groundedness_warning': response.groundedness_warning})}\n\n"

        yield f"event: done\ndata: {json.dumps({'message_id': response.message_id})}\n\n"

        # Step 3: Cache the answer
        await cache_svc.store(
            query=body.content,
            answer_payload={
                "content": response.content,
                "citations": response.citations,
                "trust_badge": response.trust_badge,
            },
            scope_type="all",
            scope_id=None,
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations")
async def list_conversations(
    cursor: str | None = None,
    limit: int = 20,
    user: dict = Depends(get_current_user),
    _role: str = Depends(require_role(UserRole.VIEWER)),
) -> APIResponse:
    """List user's chat conversations."""
    svc = ChatService()
    result = await svc.list_conversations(
        user_email=user["email"],
        cursor=cursor,
        limit=min(limit, 50),
    )
    # Transform items to camelCase for the React frontend
    camel_items = [
        {
            "conversationId": item.get("conversation_id", ""),
            "scopeType": item.get("scope_type", "all"),
            "scopeId": item.get("scope_id"),
            "title": item.get("title"),
            "messageCount": int(item.get("message_count") or 0),
            "createdAt": item.get("created_at") or "",
            "lastMessageAt": item.get("last_message_at"),
        }
        for item in result.get("items", [])
    ]
    return APIResponse(
        status="success",
        data={"items": camel_items, "pagination": result.get("pagination", {})},
    )


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: dict = Depends(get_current_user),
    _role: str = Depends(require_role(UserRole.VIEWER)),
) -> APIResponse:
    """Soft delete a conversation."""
    svc = ChatService()
    await svc.delete_conversation(conversation_id, user["email"])
    return APIResponse(status="success", data={"deleted": True})


@router.post("/messages/{message_id}/feedback")
async def submit_feedback(
    message_id: str,
    body: ChatFeedbackRequest,
    user: dict = Depends(get_current_user),
    _role: str = Depends(require_role(UserRole.VIEWER)),
) -> APIResponse:
    """Submit feedback on a chat message."""
    svc = ChatService()
    await svc.save_feedback(message_id, body.rating, body.comment)
    return APIResponse(status="success", data={"message_id": message_id, "rating": body.rating})
