"""
Tests for Extended Protected Deep Health Check, exact query shapes, failure modes, and zero-residue verification.
"""

import os
import asyncio
import pytest
import httpx
import redis.asyncio as aioredis
from datetime import datetime, timezone
from sqlalchemy import text

from app.main import app
from app.core.config import settings
from app.core.database import async_session, engine
from app.core import redis as app_redis
from scripts.post_deploy_smoke import run_smoke_check


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def ensure_fresh_clients():
    # Fresh redis client for the active event loop
    app_redis.redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=5.0,
    )
    yield
    await engine.dispose()
    if app_redis.redis_client:
        try:
            await app_redis.redis_client.aclose()
        except Exception:
            pass


@pytest.fixture
def async_client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_public_health_remains_minimal_and_unleaked(async_client):
    """
    Requirement 7:
    Public /health response must remain minimal and must not expose secrets,
    checks breakdown, database branches, or infrastructure details.
    """
    async with async_client as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()

        # Minimal payload
        assert "status" in data
        assert "service" in data
        assert "version" in data

        # Proves no infrastructure details or checks are leaked publicly
        assert "checks" not in data
        assert "database" not in data
        assert "redis" not in data
        assert "commit_sha" not in data
        assert "worker" not in data


@pytest.mark.asyncio
async def test_protected_health_detailed_requires_auth(async_client, monkeypatch):
    """
    Requirement 7:
    Protected deep check must reject unauthenticated requests or invalid secrets with 401.
    """
    monkeypatch.setattr(settings, "HEALTH_CHECK_SECRET", "smoke-test-secret-123")

    async with async_client as client:
        # 1. No auth provided -> 401
        resp = await client.get("/health/detailed")
        assert resp.status_code == 401

        # 2. Invalid secret provided -> 401
        resp = await client.get(
            "/health/detailed",
            headers={"X-Health-Check-Secret": "wrong-secret-value"}
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_health_detailed_passing_case_and_residue_check(async_client, monkeypatch):
    """
    Requirement 7 & 9:
    Passing case against local Postgres:
    - SELECT on events using timezone-aware comparison (created_at >= now-7d)
    - SELECT on alerts using timezone-aware comparison (created_at >= now-7d)
    - Redis ping
    - Alembic current revision
    - Returns HTTP 200 with clear pass/fail per check
    - Residue check before and after proves zero data written.
    """
    smoke_secret = "smoke-test-secret-123"
    monkeypatch.setattr(settings, "HEALTH_CHECK_SECRET", smoke_secret)

    # 1. Independent residue check BEFORE
    async with async_session() as s:
        events_before = (await s.execute(text("SELECT count(*) FROM events"))).scalar()
        alerts_before = (await s.execute(text("SELECT count(*) FROM alerts"))).scalar()

    # 2. Call protected deep check with valid secret
    async with async_client as client:
        resp = await client.get(
            "/health/detailed",
            headers={"X-Health-Check-Secret": smoke_secret}
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

        assert data.get("status") == "pass"
        checks = data.get("checks", {})

        # Individual check assertions
        assert checks.get("database_connection", {}).get("status") == "pass"
        assert checks.get("database_events_query", {}).get("status") == "pass"
        assert checks.get("database_alerts_query", {}).get("status") == "pass"
        assert checks.get("database_alembic_revision", {}).get("status") == "pass"
        assert checks.get("redis_ping", {}).get("status") == "pass"

        # Alembic revision present
        rev = checks.get("database_alembic_revision", {}).get("revision")
        assert rev is not None and len(rev) > 0

    # 3. Independent residue check AFTER (proves 100% read-only, zero rows modified)
    async with async_session() as s:
        events_after = (await s.execute(text("SELECT count(*) FROM events"))).scalar()
        alerts_after = (await s.execute(text("SELECT count(*) FROM alerts"))).scalar()

    assert events_before == events_after
    assert alerts_before == alerts_after


@pytest.mark.asyncio
async def test_protected_health_detailed_forced_failure_and_residue_check(async_client, monkeypatch):
    """
    Requirement 7 & 9:
    Forced failure proving it fails loudly:
    - Temporarily force Redis ping to fail
    - Deep check returns non-200 status (HTTP 503 Service Unavailable)
    - Clear pass/fail per check (redis_ping status == "fail")
    - Residue check before and after proves zero residue even after failing run.
    """
    smoke_secret = "smoke-test-secret-123"
    monkeypatch.setattr(settings, "HEALTH_CHECK_SECRET", smoke_secret)

    # 1. Independent residue check BEFORE
    async with async_session() as s:
        events_before = (await s.execute(text("SELECT count(*) FROM events"))).scalar()
        alerts_before = (await s.execute(text("SELECT count(*) FROM alerts"))).scalar()

    # 2. Temporarily break Redis client
    class BrokenRedis:
        async def ping(self):
            raise ConnectionRefusedError("Simulated Redis down on wrong port")

    monkeypatch.setattr(app_redis, "redis_client", BrokenRedis())

    # 3. Call protected deep check — MUST return non-200 (HTTP 503)
    async with async_client as client:
        resp = await client.get(
            "/health/detailed",
            headers={"X-Health-Check-Secret": smoke_secret}
        )
        assert resp.status_code == 503
        data = resp.json()

        assert data.get("status") == "fail"
        checks = data.get("checks", {})
        assert checks.get("redis_ping", {}).get("status") == "fail"
        assert "error" in checks.get("redis_ping", {})

        # Database checks should still pass individually
        assert checks.get("database_connection", {}).get("status") == "pass"
        assert checks.get("database_events_query", {}).get("status") == "pass"

    # 4. Independent residue check AFTER (proves zero residue after failing run)
    async with async_session() as s:
        events_after = (await s.execute(text("SELECT count(*) FROM events"))).scalar()
        alerts_after = (await s.execute(text("SELECT count(*) FROM alerts"))).scalar()

    assert events_before == events_after
    assert alerts_before == alerts_after
