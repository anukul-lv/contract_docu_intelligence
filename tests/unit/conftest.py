"""Shared fixtures and mocks for unit tests."""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ---------------------------------------------------------------------------
# MockAIProvider — deterministic mock for AI function calls
# ---------------------------------------------------------------------------
MOCK_EXTRACTION_RESULTS = {
    "general_healthcare": {
        "contract_type": "Provider Agreement",
        "parties": [{"name": "Acme Health", "role": "payer"}, {"name": "Dr. Smith", "role": "provider"}],
        "state_jurisdiction": "California",
        "effective_date": "2024-01-01",
        "expiration_date": "2025-12-31",
        "term_months": 24,
        "auto_renewal": True,
        "governing_law": "California",
        "reimbursement_method": "fee-for-service",
        "confidence_scores": {"contract_type": 0.95, "parties": 0.88, "effective_date": 0.92},
    },
}

MOCK_PARSED_DOCUMENTS = {
    "test.pdf": {
        "content": "This Provider Agreement is entered into...",
        "page_count": 15,
        "quality_score": 0.92,
        "has_errors": False,
    },
}

MOCK_CLASSIFICATIONS = {
    "This Provider Agreement": "Provider Agreement",
    "BUSINESS ASSOCIATE AGREE": "BAA",
}


class MockAIProvider:
    """Deterministic mock for AI function calls in unit tests."""

    def ai_extract(self, content, schema, **kwargs):
        return MOCK_EXTRACTION_RESULTS.get(schema, MOCK_EXTRACTION_RESULTS["general_healthcare"])

    def ai_parse_document(self, path, config):
        return MOCK_PARSED_DOCUMENTS.get(path, MOCK_PARSED_DOCUMENTS["test.pdf"])

    def ai_classify(self, text, categories):
        return MOCK_CLASSIFICATIONS.get(text[:25], "Other")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_ai():
    """Return a MockAIProvider instance."""
    return MockAIProvider()


@pytest.fixture
def mock_execute_sql():
    """Patch execute_sql to return canned results."""
    with patch("backend.dependencies.execute_sql", new_callable=AsyncMock) as mock:
        mock.return_value = []
        yield mock


@pytest.fixture
def mock_workspace_client():
    """Patch get_workspace_client to return a MagicMock."""
    with patch("backend.dependencies.get_workspace_client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def settings_env(monkeypatch):
    """Set environment variables for Settings."""
    monkeypatch.setenv("APP_CATALOG", "test")
    monkeypatch.setenv("APP_SCHEMA", "test_schema")
    monkeypatch.setenv("CUSTOMER_CATALOG", "test")
    monkeypatch.setenv("CUSTOMER_SCHEMA", "test_schema")
    monkeypatch.setenv("VOLUME_PATH", "/Volumes/test/test_schema/test_vol")


@pytest.fixture
def sample_review_item():
    """A sample review queue row for testing."""
    return {
        "review_id": "rev-001",
        "document_version_id": "doc-v-001",
        "field_name": "effective_date",
        "ai_extracted_value": "2024-01-01",
        "human_corrected_value": None,
        "ai_confidence": 0.89,
        "field_class": "important_structural",
        "review_status": "PENDING",
        "version_number": 1,
        "assigned_to": None,
        "source_citation": "Page 2, Section 3",
        "confidence_explanation": None,
    }
