"""Integration test fixtures — test SQL warehouse and FastAPI test client."""
import os
import sys

import pytest
from httpx import ASGITransport, AsyncClient

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def test_app():
    """Create a FastAPI test application."""
    # Set test environment
    os.environ.setdefault("APP_CATALOG", "dev")
    os.environ.setdefault("APP_SCHEMA", "doc_intel")
    os.environ.setdefault("CUSTOMER_CATALOG", "dev")
    os.environ.setdefault("CUSTOMER_SCHEMA", "doc_intel")
    os.environ.setdefault("VOLUME_PATH", "/Volumes/dev/doc_intel/prvdr_contracts")

    from app import app
    return app


@pytest.fixture
async def client(test_app):
    """Async HTTP client for integration tests.

    Injects test auth headers to bypass AuthMiddleware.
    """
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Inject mock auth headers (simulates Databricks proxy)
        ac.headers.update({
            "X-Forwarded-Email": "integration-test@healthcontracts.ai",
            "X-Forwarded-Preferred-Username": "integration-test",
            "X-Forwarded-Groups": "healthcare_admin",
        })
        yield ac


@pytest.fixture
def test_volume_path():
    """Path to the test document corpus."""
    return "/Volumes/dev/doc_intel/prvdr_contracts"


@pytest.fixture
def sample_upload_file():
    """Return a minimal PDF-like file tuple for upload testing."""
    content = b"%PDF-1.4 test content for integration testing"
    return ("test_contract.pdf", content, "application/pdf")
