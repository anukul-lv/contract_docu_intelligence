"""Integration tests for settings and feature flag APIs."""
import pytest


class TestSettings:
    @pytest.mark.asyncio
    async def test_get_settings(self, client):
        resp = await client.get("/api/v1/settings")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "warehouse_config" in data
        assert "extraction_defaults" in data
        assert "environment" in data

    @pytest.mark.asyncio
    async def test_put_settings_requires_admin(self, client):
        client.headers["X-Forwarded-Groups"] = "healthcare_viewer"
        resp = await client.put("/api/v1/settings", json={"settings": {}})
        assert resp.status_code == 403
        client.headers["X-Forwarded-Groups"] = "healthcare_admin"


class TestFeatureFlags:
    @pytest.mark.asyncio
    async def test_get_flags(self, client):
        resp = await client.get("/api/v1/settings/flags")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "flags" in data

    @pytest.mark.asyncio
    async def test_update_nonexistent_flag(self, client):
        resp = await client.put(
            "/api/v1/settings/flags/nonexistent_flag",
            json={"enabled": True},
        )
        assert resp.status_code == 404


    @pytest.mark.asyncio
    async def test_put_flag_requires_admin(self, client):
        client.headers["X-Forwarded-Groups"] = "healthcare_viewer"
        resp = await client.put(
            "/api/v1/settings/flags/test_flag",
            json={"enabled": True, "rollout_pct": 100},
        )
        assert resp.status_code == 403
        client.headers["X-Forwarded-Groups"] = "healthcare_admin"


class TestProfiles:
    @pytest.mark.asyncio
    async def test_get_profiles(self, client):
        resp = await client.get("/api/v1/settings/profiles")
        assert resp.status_code == 200
        profiles = resp.json()["data"]["profiles"]
        assert len(profiles) == 5
        names = {p["name"] for p in profiles}
        assert "general_healthcare" in names
        assert "custom_json" in names

    @pytest.mark.asyncio
    async def test_profiles_have_descriptions(self, client):
        resp = await client.get("/api/v1/settings/profiles")
        profiles = resp.json()["data"]["profiles"]
        for p in profiles:
            assert "name" in p
            assert "description" in p
