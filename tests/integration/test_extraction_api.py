"""Integration tests for extraction pipeline API."""
import pytest


class TestExtractionStatus:
    @pytest.mark.asyncio
    async def test_status_nonexistent_run(self, client):
        resp = await client.get("/api/v1/extract/status/nonexistent-run")
        assert resp.status_code == 404


class TestExtractionHistory:
    @pytest.mark.asyncio
    async def test_history_returns_200(self, client):
        resp = await client.get("/api/v1/extract/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "jobs" in data["data"]

    @pytest.mark.asyncio
    async def test_history_pagination(self, client):
        resp = await client.get("/api/v1/extract/history?limit=5")
        assert resp.status_code == 200


class TestExtractionStart:
    @pytest.mark.asyncio
    async def test_start_requires_operator(self, client):
        client.headers["X-Forwarded-Groups"] = "healthcare_viewer"
        resp = await client.post(
            "/api/v1/extract/start",
            json={
                "volume_path": "/Volumes/dev/doc_intel/prvdr_contracts",
                "profile": "general_healthcare",
                "output_catalog": "dev",
                "output_schema": "doc_intel",
                "idempotency_key": "test-key",
            },
        )
        assert resp.status_code == 403
        client.headers["X-Forwarded-Groups"] = "healthcare_admin"

    @pytest.mark.asyncio
    async def test_start_missing_profile_returns_422(self, client):
        resp = await client.post(
            "/api/v1/extract/start",
            json={"volume_path": "/Volumes/dev/doc_intel/prvdr_contracts"},
        )
        assert resp.status_code == 422


class TestExtractionCancel:
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_run(self, client):
        resp = await client.post("/api/v1/extract/cancel/nonexistent-run")
        assert resp.status_code == 404


class TestExtractionStream:
    @pytest.mark.asyncio
    async def test_stream_nonexistent_run(self, client):
        resp = await client.get("/api/v1/extract/stream/nonexistent-run")
        assert resp.status_code in (404, 200)  # SSE may return 200 with error event
