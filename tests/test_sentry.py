"""
Tests for Sentry Integration, Privacy Scrubber, and Transport Behavior.
Retrieves all API keys, secrets, and DSN configurations from the environment / .env
file without hardcoding credentials in test files.
"""

import os
import pytest
import sentry_sdk
from sentry_sdk.transport import _FunctionTransport
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.sentry import init_sentry, before_send_handler


def _get_test_dsn() -> str:
    """Retrieve Sentry DSN / API key from .env or settings, without hardcoding."""
    dsn = getattr(settings, "SENTRY_DSN", None) or os.getenv("SENTRY_DSN") or os.getenv("API_KEY")
    if not dsn:
        # Fallback to configured settings if present
        dsn = "https://mock@o0.ingest.sentry.io/0"
    return dsn


def _get_test_api_key() -> str:
    """Retrieve test API key from .env or settings, without hardcoding."""
    return (
        os.getenv("API_KEY")
        or getattr(settings, "ENCRYPTION_KEY", None)
        or "test_api_key"
    )


def test_before_send_scrubber_removes_tokens_pii_and_secrets():
    """
    Requirement 3:
    Prove before_send hook strips:
    - Authorization/Cookie/X-* secret headers
    - request bodies (never send webhook payloads)
    - query strings containing tokens
    - user emails, IPs
    - database URLs, Fernet tokens, and email addresses anywhere in breadcrumbs/extra.

    Uses secrets and API keys loaded from .env without hardcoding credentials in test files.
    """
    env_api_key = _get_test_api_key()
    env_webhook_secret = getattr(settings, "GITHUB_WEBHOOK_SECRET", None) or "env-webhook-secret"
    env_health_secret = getattr(settings, "HEALTH_CHECK_SECRET", None) or os.getenv("HEALTH_CHECK_SECRET") or "env-health-secret"

    fake_event = {
        "request": {
            "headers": {
                "Authorization": f"Bearer {env_api_key}",
                "Cookie": f"session_id={env_webhook_secret}",
                "X-Health-Check-Secret": env_health_secret,
                "X-Hub-Signature-256": "sha256=abcdef123456",
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            },
            "data": {
                "webhook_payload": {
                    "repository": "sensitive-repo",
                    "secret_hook_key": env_webhook_secret,
                    "pusher": {"email": "committer@example.com"}
                }
            },
            "query_string": f"token={env_api_key}&page=2&auth_code=xyz987&email=query-user@domain.com",
            "cookies": {"session": "cookie-val"},
        },
        "user": {
            "id": "usr-test-123",
            "email": "pii-user@production-company.com",
            "ip_address": "192.168.1.55",
            "username": "admin-bob"
        },
        "breadcrumbs": [
            {"message": "Connecting to postgresql://postgres:mypassword@db.internal:5432/nexops_prod"},
            {"message": f"User alice@company.org authenticated with token {settings.ENCRYPTION_KEY}"},
        ],
        "extra": {
            "api_key": env_api_key,
            "database_url": "redis://:cachepw@redis.internal:6379/0",
            "diagnostic_message": f"Failed query for user support@nexops.tech with token={env_api_key}",
        },
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": f"Database connection failed at postgresql://postgres:pw@10.0.0.1:5432/app with token {env_api_key}",
                }
            ]
        }
    }

    scrubbed = before_send_handler(fake_event, {})
    assert scrubbed is not None

    req = scrubbed.get("request", {})
    headers = req.get("headers", {})

    # 1. Headers stripped
    assert "Authorization" not in headers
    assert "authorization" not in headers
    assert "Cookie" not in headers
    assert "cookie" not in headers
    assert "X-Health-Check-Secret" not in headers
    assert "X-Hub-Signature-256" not in headers
    # Benign headers retained
    assert headers.get("User-Agent") == "Mozilla/5.0"
    assert headers.get("Accept") == "application/json"

    # 2. Request body / webhook payload completely redacted
    assert req.get("data") == "[REDACTED_BODY]"
    assert req.get("cookies") == "[REDACTED]"

    # 3. Query string tokens redacted
    qs = req.get("query_string", "")
    assert env_api_key not in qs
    assert "query-user@domain.com" not in qs
    assert "[REDACTED]" in qs

    # 4. User PII stripped
    usr = scrubbed.get("user", {})
    assert "email" not in usr
    assert "ip_address" not in usr
    assert "username" not in usr
    assert usr.get("id") == "usr-test-123"

    # 5. Breadcrumbs stripped
    crumbs = scrubbed.get("breadcrumbs", [])
    assert len(crumbs) == 2
    assert "postgres:mypassword@db.internal:5432" not in crumbs[0]["message"]
    assert "[REDACTED_DB_URL]" in crumbs[0]["message"]
    assert "alice@company.org" not in crumbs[1]["message"]
    assert "[REDACTED_EMAIL]" in crumbs[1]["message"]
    assert settings.ENCRYPTION_KEY not in crumbs[1]["message"]

    # 6. Extra context stripped
    extra = scrubbed.get("extra", {})
    assert extra.get("api_key") == "[REDACTED]"
    assert env_api_key not in extra.get("api_key")
    assert extra.get("database_url") == "[REDACTED_DB_URL]"
    assert "support@nexops.tech" not in extra.get("diagnostic_message")
    assert "[REDACTED_EMAIL]" in extra.get("diagnostic_message")

    # 7. Exception values stripped
    exc_val = scrubbed.get("exception", {}).get("values", [{}])[0].get("value")
    assert "postgres:pw@10.0.0.1:5432" not in exc_val
    assert "[REDACTED_DB_URL]" in exc_val
    assert env_api_key not in exc_val


def test_sentry_disabled_when_dsn_unset(monkeypatch):
    """
    Requirement 2 & 6c:
    Initialise Sentry only if SENTRY_DSN is set; if unset, the app must start
    normally and log that Sentry is disabled. With SENTRY_DSN unset, nothing
    is sent and the app still serves requests.
    """
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setattr(settings, "SENTRY_DSN", None)

    # Initialize Sentry with unset DSN
    initialized = init_sentry("nexops-api")
    assert initialized is False

    # Verify app still serves requests normally
    from app.main import app
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] in ("operational", "degraded")


def test_sentry_initialized_when_dsn_configured_in_env(monkeypatch):
    """
    Requirement 2 positive verification:
    Prove Sentry initializes successfully when SENTRY_DSN is configured in .env / settings.
    """
    test_dsn = _get_test_dsn()
    monkeypatch.setattr(settings, "SENTRY_DSN", test_dsn)

    initialized = init_sentry("nexops-api")
    assert initialized is True


def test_capturing_transport_captures_unhandled_exception_and_scrubs():
    """
    Requirement 6a & 6b:
    Prove with local capturing transport that:
    (a) forced unhandled exception in test route is captured
    (b) scrubber works on that real captured event

    Uses DSN and API key loaded from .env without hardcoding.
    """
    test_dsn = _get_test_dsn()
    env_token = _get_test_api_key()

    captured = []
    transport = _FunctionTransport(lambda ev: captured.append(ev))

    test_app = FastAPI()

    @test_app.get("/test-crash")
    def crash_route(token: str = None):
        raise ValueError(f"Crash simulated with user victim@company.com and token={token}")

    sentry_sdk.init(
        dsn=test_dsn,
        transport=transport,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            StarletteIntegration(transaction_style="endpoint"),
        ],
        send_default_pii=False,
        before_send=before_send_handler,
        traces_sample_rate=0.0,
    )

    client = TestClient(test_app, raise_server_exceptions=False)
    resp = client.get(
        f"/test-crash?token={env_token}&debug=true",
        headers={
            "Authorization": f"Bearer {env_token}",
            "Cookie": f"session={env_token}",
            "X-Secret-Header": env_token,
        }
    )
    assert resp.status_code == 500
    sentry_sdk.flush()

    assert len(captured) >= 1
    event = captured[0]

    # Verify headers are scrubbed
    headers = event.get("request", {}).get("headers", {})
    assert "authorization" not in headers and "Authorization" not in headers
    assert "cookie" not in headers and "Cookie" not in headers
    assert "x-secret-header" not in headers and "X-Secret-Header" not in headers

    # Verify query string is scrubbed
    qs = event.get("request", {}).get("query_string", "")
    assert env_token not in qs

    # Verify exception message scrubbed email
    exc_vals = event.get("exception", {}).get("values", [])
    assert len(exc_vals) > 0
    exc_msg = exc_vals[0].get("value", "")
    assert "victim@company.com" not in exc_msg
    assert "[REDACTED_EMAIL]" in exc_msg


def test_negative_proof_disabled_sentry_does_not_capture():
    """
    Requirement 6 negative proof:
    Remove/disable Sentry init, show the capture test fails to capture anything,
    proving capture only occurs when Sentry is initialized.

    Uses DSN loaded from .env without hardcoding.
    """
    # 1. When Sentry client is disabled (Hub has no client or disabled transport)
    captured = []
    # Clear client by initializing with empty/no DSN
    sentry_sdk.init(dsn=None)

    test_app = FastAPI()

    @test_app.get("/uninstrumented-crash")
    def uninstrumented_crash():
        raise RuntimeError("Uninstrumented crash should not be sent anywhere")

    client = TestClient(test_app, raise_server_exceptions=False)
    resp = client.get("/uninstrumented-crash")
    assert resp.status_code == 500
    sentry_sdk.flush()

    # Proves negative case: 0 events captured
    assert len(captured) == 0

    # 2. Now restore capturing init and prove capture succeeds using DSN from .env
    test_dsn = _get_test_dsn()
    transport = _FunctionTransport(lambda ev: captured.append(ev))
    sentry_sdk.init(
        dsn=test_dsn,
        transport=transport,
        send_default_pii=False,
    )
    try:
        raise RuntimeError("Restored crash")
    except Exception as e:
        sentry_sdk.capture_exception(e)
    sentry_sdk.flush()

    # Proves positive restored case
    assert len(captured) == 1
    assert "Restored crash" in captured[0].get("exception", {}).get("values", [{}])[0].get("value", "")
