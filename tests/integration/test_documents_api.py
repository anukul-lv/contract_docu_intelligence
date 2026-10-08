"""Integration tests for document upload and listing APIs."""
import pytest


class TestDocumentList:
    @pytest.mark.asyncio
    async def test_list_returns_200(self, client):
        resp = await client.get("/api/v1/documents/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "items" in data["data"]

    @pytest.mark.asyncio
    async def test_list_pagination(self, client):
        resp = await client.get("/api/v1/documents/list?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert "pagination" in data.get("meta", {})


class TestDocumentUpload:
    @pytest.mark.asyncio
    async def test_upload_rejects_invalid_extension(self, client):
        files = {"file": ("test.exe", b"fake content", "application/octet-stream")}
        resp = await client.post("/api/v1/documents/upload", files=files)
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_upload_requires_operator_role(self, client):
        # Override to viewer role
        client.headers["X-Forwarded-Groups"] = "healthcare_viewer"
        files = {"file": ("test.pdf", b"%PDF-1.4", "application/pdf")}
        resp = await client.post("/api/v1/documents/upload", files=files)
        assert resp.status_code == 403
        # Restore admin
        client.headers["X-Forwarded-Groups"] = "healthcare_admin"


class TestDedupeCheck:
    @pytest.mark.asyncio
    async def test_dedupe_check_returns_200(self, client):
        resp = await client.post(
            "/api/v1/documents/dedupe-check",
            json={"checksums": ["abc123"]},
        )
        assert resp.status_code == 200
