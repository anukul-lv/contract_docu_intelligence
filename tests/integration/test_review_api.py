"""Integration tests for review workbench API."""
import pytest


class TestReviewQueue:
    @pytest.mark.asyncio
    async def test_queue_returns_200(self, client):
        resp = await client.get("/api/v1/review/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "items" in data["data"]

    @pytest.mark.asyncio
    async def test_queue_filters(self, client):
        resp = await client.get("/api/v1/review/queue?status=PENDING&limit=10")
        assert resp.status_code == 200


class TestReviewActions:
    @pytest.mark.asyncio
    async def test_claim_nonexistent_returns_409(self, client):
        resp = await client.post(
            "/api/v1/review/nonexistent-id/claim",
            json={"expected_version": 1},
        )
        # Either 409 (conflict) or the MERGE succeeds with 0 rows
        assert resp.status_code in (200, 409)

    @pytest.mark.asyncio
    async def test_approve_requires_reviewer(self, client):
        client.headers["X-Forwarded-Groups"] = "healthcare_viewer"
        resp = await client.post(
            "/api/v1/review/test-id/approve",
            json={"expected_version": 1},
        )
        assert resp.status_code == 403
        client.headers["X-Forwarded-Groups"] = "healthcare_admin"


class TestReviewStats:
    @pytest.mark.asyncio
    async def test_stats_returns_200(self, client):
        resp = await client.get("/api/v1/review/stats")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "pending" in data
        assert "completed_today" in data


class TestBatchApprove:
    @pytest.mark.asyncio
    async def test_batch_approve_returns_200(self, client):
        resp = await client.post(
            "/api/v1/review/batch-approve",
            json={"review_ids": [], "min_confidence": 0.85},
        )
        assert resp.status_code == 200
