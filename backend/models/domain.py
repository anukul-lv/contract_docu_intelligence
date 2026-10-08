"""Domain value objects and enums."""
from enum import Enum


class UserRole(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    REVIEWER = "reviewer"
    ADMIN = "admin"


# Ordered hierarchy for RBAC comparisons (higher index = more privilege)
ROLE_HIERARCHY = [UserRole.VIEWER, UserRole.OPERATOR, UserRole.REVIEWER, UserRole.ADMIN]


class JobState(str, Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    PENDING = "PENDING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    SUBMIT_FAILED = "SUBMIT_FAILED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INVALID_REQUEST = "INVALID_REQUEST"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    CORRECTED = "CORRECTED"
    FLAGGED = "FLAGGED"


class VerificationStatus(str, Enum):
    AI_EXTRACTED = "AI_EXTRACTED"
    VERIFIED = "VERIFIED"
    CORRECTED = "CORRECTED"
    FLAGGED = "FLAGGED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    ANOMALY = "ANOMALY"


class FieldClass(str, Enum):
    CRITICAL_FINANCIAL = "critical_financial"
    CRITICAL_COMPLIANCE = "critical_compliance"
    IMPORTANT_STRUCTURAL = "important_structural"
    LOW_RISK_METADATA = "low_risk_metadata"
