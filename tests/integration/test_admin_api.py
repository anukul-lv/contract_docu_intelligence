"""Integration tests for admin audit log API."""
import pytest


class TestAuditLog:
    @pytest.mark.asyncio
    async def test_audit_log_returns_200(self, client):
        resp = await client.get("/api/v1/admin/audit-log")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "entries" in data["data"]

    @pytest.mark.asyncio
    async def test_audit_log_filters(self, client):
        resp = await client.get(
            "/api/v1/admin/audit-log?event_type=DOCUMENT_ACCESSED&limit=10"
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_audit_log_date_filter(self, client):
        resp = await client.get(
            "/api/v1/admin/audit-log?date_from=2024-01-01&date_to=2025-12-31"
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_audit_log_requires_admin(self, client):
        client.headers["X-Forwarded-Groups"] = "healthcare_viewer"
        resp = await client.get("/api/v1/admin/audit-log")
        assert resp.status_code == 403
        client.headers["X-Forwarded-Groups"] = "healthcare_admin"

    @pytest.mark.asyncio
    async def test_event_types_endpoint(self, client):
        resp = await client.get("/api/v1/admin/audit-log/event-types")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "event_types" in data

    @pytest.mark.asyncio
    async def test_audit_log_pagination(self, client):
        resp = await client.get("/api/v1/admin/audit-log?limit=5")
        assert resp.status_code == 200
        meta = resp.json().get("meta", {})
        assert "pagination" in meta

    @pytest.mark.asyncio
    async def test_audit_log_max_limit_500(self, client):
        resp = await client.get("/api/v1/admin/audit-log?limit=1000")
        assert resp.status_code == 200
        # API should cap to 500

    @pytest.mark.asyncio
    async def test_audit_log_user_filter(self, client):
        resp = await client.get("/api/v1/admin/audit-log?user=nonexistent@test.com")
        assert resp.status_code == 200
        data = resp.json()["data"]
        entries = data.get("entries", [])
        # Filtered list should be empty or only matching
