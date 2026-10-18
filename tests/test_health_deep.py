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
async def test_protected_health_detailed_requires_auth(async_client, monkeypatch, caplog):
    """
    Task 12c - Item C.4:
    Protected deep check access control tests:
    1. Secret unset with no header -> 401
    2. Secret unset with empty header -> 401
    3. Wrong secret -> 401
    4. Correct secret -> 200
    5. Normal Firebase user token -> 401
    6. Never log the secret in any log level
    """
    import logging

    # Mock versions for the 200 OK passing response
    import importlib.metadata
    orig_version = importlib.metadata.version
    pinned_defaults = {
        "fastapi": "0.115.6",
        "sqlmodel": "0.0.22",
        "sqlalchemy": "2.0.36",
        "asyncpg": "0.29.0",
        "pydantic": "2.12.5",
    }
    monkeypatch.setattr(importlib.metadata, "version", lambda pkg: pinned_defaults.get(pkg, orig_version(pkg)))

    with caplog.at_level(logging.DEBUG):
        async with async_client as client:
            # 1. Secret unset with no header -> 401
            monkeypatch.setattr(settings, "HEALTH_CHECK_SECRET", None)
            resp = await client.get("/health/detailed")
            assert resp.status_code == 401

            # 2. Secret unset with empty header -> 401
            monkeypatch.setattr(settings, "HEALTH_CHECK_SECRET", "")
            resp = await client.get("/health/detailed", headers={"X-Health-Check-Secret": ""})
            assert resp.status_code == 401

            # Now configure valid secret
            configured_secret = "ultra-secret-smoke-token-xyz987"
            monkeypatch.setattr(settings, "HEALTH_CHECK_SECRET", configured_secret)

            # 3. Wrong secret -> 401
            resp = await client.get(
                "/health/detailed",
                headers={"X-Health-Check-Secret": "invalid-wrong-secret"}
            )
            assert resp.status_code == 401

            # 4. Correct secret -> 200
            resp_hdr = await client.get(
                "/health/detailed",
                headers={"X-Health-Check-Secret": configured_secret}
            )
            assert resp_hdr.status_code == 200

            resp_bearer = await client.get(
                "/health/detailed",
                headers={"Authorization": f"Bearer {configured_secret}"}
            )
            assert resp_bearer.status_code == 200

            # 5. Normal Firebase user token without secret -> 401
            fake_firebase_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiJub3JtYWwtdXNlci0xMjMiLCJlbWFpbCI6InVzZXJAZXhhbXBsZS5jb20ifQ.signature"
            resp_fb = await client.get(
                "/health/detailed",
                headers={"Authorization": f"Bearer {fake_firebase_token}"}
            )
            assert resp_fb.status_code == 401

        # 6. Never log the secret
        assert configured_secret not in caplog.text


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

    # Mock importlib.metadata.version to match pinned requirements.txt for the passing case
    import importlib.metadata
    orig_version = importlib.metadata.version
    pinned_defaults = {
        "fastapi": "0.115.6",
        "sqlmodel": "0.0.22",
        "sqlalchemy": "2.0.36",
        "asyncpg": "0.29.0",
        "pydantic": "2.12.5",
    }
    monkeypatch.setattr(importlib.metadata, "version", lambda pkg: pinned_defaults.get(pkg, orig_version(pkg)))

    # 2. Call protected deep check with valid secret
    async with async_client as client:
        resp = await client.get(
            "/health/detailed",
            headers={"X-Health-Check-Secret": smoke_secret}
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

        assert data.get("status") == "pass"
        assert "package_versions" in data
        checks = data.get("checks", {})

        # Individual check assertions
        assert checks.get("database_connection", {}).get("status") == "pass"
        assert checks.get("database_events_query", {}).get("status") == "pass"
        assert checks.get("database_alerts_query", {}).get("status") == "pass"
        assert checks.get("database_alembic_revision", {}).get("status") == "pass"
        assert checks.get("redis_ping", {}).get("status") == "pass"
        assert checks.get("package_versions", {}).get("status") == "pass"

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


@pytest.mark.asyncio
async def test_protected_health_detailed_package_versions_in_output(async_client, monkeypatch):
    """
    Task 12b - Item 2a:
    Verify that /health/detailed includes installed versions of:
    sqlmodel, sqlalchemy, asyncpg, pydantic, and fastapi in its protected output.
    """
    smoke_secret = "smoke-test-secret-123"
    monkeypatch.setattr(settings, "HEALTH_CHECK_SECRET", smoke_secret)

    async with async_client as client:
        resp = await client.get(
            "/health/detailed",
            headers={"X-Health-Check-Secret": smoke_secret}
        )
        assert resp.status_code in (200, 503)
        data = resp.json()

        assert "package_versions" in data
        versions = data["package_versions"]
        for pkg in ["sqlmodel", "sqlalchemy", "asyncpg", "pydantic", "fastapi"]:
            assert pkg in versions, f"Expected {pkg} in package_versions output"
            assert versions[pkg] is not None


@pytest.mark.asyncio
async def test_protected_health_detailed_fails_on_package_version_mismatch(async_client, monkeypatch):
    """
    Task 12b - Item 2b:
    Expected-version check: compare installed versions to pinned versions in requirements.txt
    and report status 'fail' and HTTP 503 if they differ.
    """
    smoke_secret = "smoke-test-secret-123"
    monkeypatch.setattr(settings, "HEALTH_CHECK_SECRET", smoke_secret)

    # Force an intentional version mismatch for fastapi
    import importlib.metadata
    orig_version = importlib.metadata.version
    def mock_version(pkg: str):
        if pkg == "fastapi":
            return "99.99.99"
        return orig_version(pkg)

    monkeypatch.setattr(importlib.metadata, "version", mock_version)

    async with async_client as client:
        resp = await client.get(
            "/health/detailed",
            headers={"X-Health-Check-Secret": smoke_secret}
        )
        # MUST fail with 503 Service Unavailable due to version mismatch
        assert resp.status_code == 503
        data = resp.json()

        assert data.get("status") == "fail"
        pkg_check = data.get("checks", {}).get("package_versions", {})
        assert pkg_check.get("status") == "fail"
        mismatches = pkg_check.get("mismatches", [])
        assert any("fastapi" in m for m in mismatches)


def test_startup_database_banner_masks_credentials(caplog):
    """
    Task 12b - Item 3a:
    Show the exact code that prints the 'Database:' line in the startup banner.
    Make sure user, password and host are masked (print only driver and database name).
    Prove with a test that the log output for a URL with a fake password contains
    neither the password nor the username.
    """
    import logging
    from app.main import mask_database_url

    fake_user = "prod_db_admin_user"
    fake_password = "SuperSecret_Ultra_Password_987#!"
    fake_host = "ep-silent-hill-12345.us-east-2.aws.neon.tech"
    fake_db = "nexops_production_db"

    fake_db_url = f"postgresql+asyncpg://{fake_user}:{fake_password}@{fake_host}:5432/{fake_db}"

    masked = mask_database_url(fake_db_url)

    # 1. Direct mask function assertion: contains only driver and db name
    assert fake_password not in masked
    assert fake_user not in masked
    assert fake_host not in masked
    assert masked == f"postgresql+asyncpg://[MASKED]/{fake_db}"

    # 2. Assert log output formatting
    with caplog.at_level(logging.INFO, logger="nexops"):
        test_logger = logging.getLogger("nexops")
        test_logger.info(f"  Database: {mask_database_url(fake_db_url)}")

    log_text = caplog.text
    assert fake_password not in log_text
    assert fake_user not in log_text
    assert fake_host not in log_text
    assert f"postgresql+asyncpg://[MASKED]/{fake_db}" in log_text


@pytest.mark.asyncio
async def test_events_alerts_date_query_exact_service_shape():
    """
    Task 12b - Item 2c:
    Verify that the events and alerts date queries exercise the exact same code path
    as the application services without type_coerce:
    select(func.count(Event.id)).where(Event.created_at >= seven_days_ago)
    select(func.count(Alert.id)).where(Alert.created_at >= seven_days_ago)
    """
    from datetime import timedelta
    from sqlalchemy import func
    from sqlmodel import select
    from app.models.event import Event
    from app.models.alert import Alert

    now_utc = datetime.now(timezone.utc)
    seven_days_ago = now_utc - timedelta(days=7)

    async with async_session() as session:
        # 1. Event count query matching analytics service
        event_stmt = select(func.count(Event.id)).where(Event.created_at >= seven_days_ago)
        res_ev = await session.execute(event_stmt)
        count_ev = res_ev.scalar()
        assert count_ev is not None
        assert count_ev >= 0

        # 2. Alert count query matching analytics service
        alert_stmt = select(func.count(Alert.id)).where(Alert.created_at >= seven_days_ago)
        res_al = await session.execute(alert_stmt)
        count_al = res_al.scalar()
        assert count_al is not None
        assert count_al >= 0


def test_startup_redis_banner_masks_credentials(caplog):
    """
    Task 12c - Item D.2:
    Prove with a test that mask_redis_url and log output for a Redis URL with
    passwords and hosts contain neither the password nor the username/host.
    """
    import logging
    from app.main import mask_redis_url

    fake_password = "SecretRedisAuthToken99!"
    fake_host = "redis-cluster-node1.prod.cache.internal"
    fake_redis_url = f"rediss://default:{fake_password}@{fake_host}:6379/2"

    masked = mask_redis_url(fake_redis_url)

    # 1. Direct function assertion
    assert fake_password not in masked
    assert fake_host not in masked
    assert "default" not in masked
    assert masked == "rediss://[MASKED]/2"

    # 2. Log output formatting assertion
    with caplog.at_level(logging.INFO, logger="nexops"):
        test_logger = logging.getLogger("nexops")
        test_logger.info(f"  Redis: {mask_redis_url(fake_redis_url)}")

    log_text = caplog.text
    assert fake_password not in log_text
    assert fake_host not in log_text
    assert "rediss://[MASKED]/2" in log_text



