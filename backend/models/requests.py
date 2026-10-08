"""Pydantic request models."""
from pydantic import BaseModel, Field
from typing import Optional, List


class ExtractionStartRequest(BaseModel):
    volume_path: str
    file_list: Optional[List[str]] = None
    output_catalog: str
    output_schema: str
    profile: str = "general_healthcare"
    auto_enrich: bool = False
    healthcare_mode: bool = True
    idempotency_key: str


class ReviewClaimRequest(BaseModel):
    expected_version: int


class ReviewApproveRequest(BaseModel):
    expected_version: int
    comment: Optional[str] = None


class ReviewCorrectRequest(BaseModel):
    expected_version: int
    corrected_value: str
    correction_reason: str = Field(
        pattern="^(Typo|Wrong Value|Wrong Field|Formatting|Other)$"
    )
    comment: Optional[str] = None


class ReviewFlagRequest(BaseModel):
    expected_version: int
    reason: str


class BatchApproveRequest(BaseModel):
    review_ids: List[str]
    min_confidence: float


class ReviewRevertRequest(BaseModel):
    reason: str


class DedupeCheckRequest(BaseModel):
    file_checksums: List[str]


class SettingsUpdateRequest(BaseModel):
    settings: dict


class FlagUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    rollout_pct: Optional[int] = None


# ---------------------------------------------------------------------------
# R2_04: Chat API request models
# ---------------------------------------------------------------------------


class ChatCreateRequest(BaseModel):
    """Create a new chat conversation."""
    scope_type: str = Field(
        default="all",
        pattern="^(all|document|contract_type)$",
        description="Scope: 'all' (portfolio), 'document' (single), 'contract_type' (filtered)",
    )
    scope_id: Optional[str] = Field(
        default=None,
        description="Document ID or contract type for scoped sessions.",
    )


class ChatMessageRequest(BaseModel):
    """Send a message in a conversation."""
    content: str = Field(
        min_length=1,
        max_length=10_000,
        description="The user's question or message.",
    )


class ChatFeedbackRequest(BaseModel):
    """Submit feedback on a chat message."""
    rating: str = Field(pattern="^(positive|negative)$")
    comment: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Optional feedback comment.",
    )
