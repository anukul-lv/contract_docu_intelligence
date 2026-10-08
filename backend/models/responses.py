"""Pydantic response models."""
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class APIResponse(BaseModel):
    """Standard API response envelope for all endpoints."""
    status: str  # "success" or "error"
    data: Optional[Any] = None
    error: Optional[dict] = None
    meta: dict = {}


class ExtractionStartResponse(BaseModel):
    run_id: str
    state: str = "SUBMITTED"
    estimated_duration_min: float
    estimated_cost: float


class PaginationMeta(BaseModel):
    next_cursor: Optional[str] = None
    has_more: bool = False
    total_count: Optional[int] = None


class HealthResponse(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    components: dict
    version: str
    environment: str


# ---------------------------------------------------------------------------
# R2_04: Chat API response / SSE models
# ---------------------------------------------------------------------------


class ChatStreamEvent(BaseModel):
    """Server-Sent Event payload for chat streaming.

    Event types:
      chunk     - incremental text fragment
      citation  - source reference
      tool_use  - tool invocation details
      metadata  - route, model, latency, trust badge
      done      - final message ID
    """
    type: str  # "chunk" | "citation" | "tool_use" | "metadata" | "done"
    data: Any


class ChatConversationResponse(BaseModel):
    """Response for conversation creation."""
    conversation_id: str
    created_at: str


class ChatConversationSummary(BaseModel):
    """Summary of a conversation for listing."""
    conversation_id: str
    title: Optional[str] = None
    scope_type: str = "all"
    message_count: int = 0
    last_message_at: Optional[str] = None
    created_at: str


class ChatMessageResponse(BaseModel):
    """Full chat message (for non-streaming or replay)."""
    message_id: str
    conversation_id: str
    role: str
    content: str
    citations: Optional[list] = None
    trust_badge: Optional[str] = None
    route_used: Optional[str] = None
    model_used: Optional[str] = None
    token_count_input: int = 0
    token_count_output: int = 0
    latency_ms: int = 0
    groundedness_score: Optional[float] = None
    groundedness_warning: Optional[str] = None
    feedback_rating: Optional[str] = None
    created_at: Optional[str] = None
