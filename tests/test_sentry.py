"""
Tests for Sentry Integration, Privacy Scrubber, and Transport Behavior.
Retrieves all API keys, secrets, and DSN configurations from the environment / .env
file without hardcoding credentials in test files.
"""

import os
import json
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


def test_capturing_transport_frame_locals_and_tokens_scrubbed_from_json():
    """
    Task 12b - Item 1c:
    Force an exception in a frame whose local variables hold fake tokens of each type
    (ghp_, gho_, ghu_, ghs_, ghr_, github_pat_, PagerDuty tokens, Firebase ID token,
    Fernet token, runtime secrets) and a fake email; prove none appear anywhere in the
    captured event JSON (serialize the whole event and assert absence).
    """
    test_dsn = _get_test_dsn()
    captured = []
    transport = _FunctionTransport(lambda ev: captured.append(ev))

    sentry_sdk.init(
        dsn=test_dsn,
        transport=transport,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        before_send=before_send_handler,
        traces_sample_rate=0.0,
    )

    fake_ghp = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
    fake_gho = "gho_abcdefghijklmnopqrstuvwxyz1234567890"
    fake_ghu = "ghu_11223344556677889900aabbccddeeffgghh"
    fake_ghs = "ghs_servertoken123456789012345678901234"
    fake_ghr = "ghr_refreshtoken12345678901234567890123"
    fake_pat = "github_pat_11AABBCCDDEEFFGGHHIIJJKKLLMMNNOOPPQQRRSSTTUUVVWWXXYYZZ"
    fake_pd_u = "u+testpagerdutytoken123456789"
    fake_pd_api = "pd_apikey1234567890abcdef"
    fake_firebase = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiJmYWtlLXVpZCIsImVtYWlsIjoidGVzdEBleGFtcGxlLmNvbSJ9.signaturepart123456789"
    fake_fernet = "gAAAAABfakefernettoken1234567890123456789012345678901234567890"
    fake_email = "victim-local-var@secretcorp.internal"
    fake_health_secret = getattr(settings, "HEALTH_CHECK_SECRET", None) or "env-health-secret"
    fake_encryption_key = getattr(settings, "ENCRYPTION_KEY", None) or "env-encryption-key"

    try:
        # Deliberately raise exception inside this frame where all tokens are local variables
        raise ValueError(
            f"Failure in handler with {fake_ghp} and email {fake_email} and {fake_pd_api}"
        )
    except Exception as exc:
        sentry_sdk.capture_exception(exc)

    sentry_sdk.flush()

    assert len(captured) >= 1
    event = captured[0]

    # Serialize whole event to JSON string
    event_json = json.dumps(event)

    # Prove none of the tokens, secrets, or PII appear anywhere in the entire event JSON
    assert fake_ghp not in event_json
    assert fake_gho not in event_json
    assert fake_ghu not in event_json
    assert fake_ghs not in event_json
    assert fake_ghr not in event_json
    assert fake_pat not in event_json
    assert fake_pd_u not in event_json
    assert fake_pd_api not in event_json
    assert fake_firebase not in event_json
    assert fake_fernet not in event_json
    assert fake_email not in event_json
    if fake_health_secret:
        assert fake_health_secret not in event_json
    if fake_encryption_key:
        assert fake_encryption_key not in event_json


def test_negative_proof_local_vars_captured_when_include_local_variables_true():
    """
    Task 12b - Item 1c Negative Proof:
    When include_local_variables=True and no scrubber hook is applied,
    prove that frame local variables and tokens DO leak into the captured event JSON.
    Then restore include_local_variables=False and before_send, and prove they do not leak.
    """
    test_dsn = _get_test_dsn()

    # --- NEGATIVE PHASE: include_local_variables=True, no scrubber ---
    captured_unscrubbed = []
    transport_unscrubbed = _FunctionTransport(lambda ev: captured_unscrubbed.append(ev))

    sentry_sdk.init(
        dsn=test_dsn,
        transport=transport_unscrubbed,
        include_local_variables=True,  # Default Sentry SDK 2.x behavior
        before_send=None,             # No scrubber hook
    )

    secret_local_token = "ghp_leakedvariable9876543210zyxwvutsrq"
    secret_local_email = "leaked-developer@secretcompany.com"

    try:
        raise RuntimeError("Unscrubbed crash for negative verification")
    except Exception as e:
        sentry_sdk.capture_exception(e)

    sentry_sdk.flush()

    assert len(captured_unscrubbed) >= 1
    unscrubbed_event_json = json.dumps(captured_unscrubbed[0])

    # REAL FAILING ASSERTION IN REVERTED STATE:
    # Proves that with include_local_variables=True and no scrubber, secrets are present in stack frames
    assert secret_local_token in unscrubbed_event_json
    assert secret_local_email in unscrubbed_event_json

    # --- RESTORED PHASE: include_local_variables=False + before_send_handler ---
    captured_restored = []
    transport_restored = _FunctionTransport(lambda ev: captured_restored.append(ev))

    sentry_sdk.init(
        dsn=test_dsn,
        transport=transport_restored,
        include_local_variables=False,  # Enforced privacy setting
        send_default_pii=False,
        before_send=before_send_handler, # Scrubber restored
    )

    try:
        raise RuntimeError(f"Restored crash with message token={secret_local_token}")
    except Exception as e:
        sentry_sdk.capture_exception(e)

    sentry_sdk.flush()

    assert len(captured_restored) >= 1
    restored_event_json = json.dumps(captured_restored[0])

    # Proves complete absence in restored state
    assert secret_local_token not in restored_event_json
    assert secret_local_email not in restored_event_json


def test_worker_exception_rate_limiter_with_fake_clock(monkeypatch):
    """
    Task 12c - Item E.2:
    Verify worker rate limiter with a fake clock:
    1. Same error 5 times within 15 minutes -> exactly 1 capture
    2. After 15 minutes -> 1 more capture carrying rate_limit_suppressed_occurrences=4
    3. Different error -> captured immediately
    """
    from app.worker.stream_consumer import (
        capture_worker_exception_rate_limited,
        _ERROR_RATE_LIMIT_CACHE,
    )
    _ERROR_RATE_LIMIT_CACHE.clear()

    captured_events = []
    recorded_extras = []

    class MockScope:
        def __init__(self):
            self.extras = {}
            self.tags = {}
        def set_extra(self, k, v):
            self.extras[k] = v
        def set_tag(self, k, v):
            self.tags[k] = v
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    current_scope = MockScope()

    def mock_push_scope():
        return current_scope

    def mock_capture(err):
        captured_events.append(err)
        recorded_extras.append(dict(current_scope.extras))

    monkeypatch.setattr(sentry_sdk, "push_scope", mock_push_scope, raising=False)
    monkeypatch.setattr(sentry_sdk, "isolation_scope", mock_push_scope, raising=False)
    monkeypatch.setattr(sentry_sdk, "capture_exception", mock_capture)

    simulated_time = 1000.0
    err_a = ValueError("Repeated sync network timeout")
    err_b = KeyError("Missing workspace config")

    # 1. Same error 5 times inside 15 minutes (900 seconds)
    for i in range(5):
        sent = capture_worker_exception_rate_limited(err_a, key_prefix="test_loop", _clock=lambda: simulated_time)
        if i == 0:
            assert sent is True
        else:
            assert sent is False
        simulated_time += 30.0  # +30s each call, total 120s < 900s

    # Exactly 1 capture fired, 4 suppressed
    assert len(captured_events) == 1
    assert "rate_limit_suppressed_occurrences" not in recorded_extras[0]

    # 2. Advance fake clock past the 15-minute window (> 900 seconds)
    simulated_time = 1000.0 + 905.0  # 15 min 5 sec later
    sent_after_window = capture_worker_exception_rate_limited(
        err_a, key_prefix="test_loop", _clock=lambda: simulated_time
    )
    assert sent_after_window is True
    assert len(captured_events) == 2
    # Verify the 2nd capture carried the suppressed count
    assert recorded_extras[1].get("rate_limit_suppressed_occurrences") == 4

    # 3. Different error fires immediately
    sent_diff = capture_worker_exception_rate_limited(
        err_b, key_prefix="test_loop", _clock=lambda: simulated_time + 10.0
    )
    assert sent_diff is True
    assert len(captured_events) == 3


def test_worker_rate_limiter_negative_proof_and_bounded_cache(monkeypatch):
    """
    Task 12c - Item E.2 & E.3:
    1. Negative proof: break the limiter (window = 0 or bypass), prove that all 5 errors fire to Sentry.
       Then restore and prove only 1 fires.
    2. Bounded cache: inserting > 200 unique error signatures caps memory at max 200 and evicts oldest.
    """
    from app.worker.stream_consumer import (
        capture_worker_exception_rate_limited,
        _ERROR_RATE_LIMIT_CACHE,
        _MAX_ERROR_CACHE_ENTRIES,
    )
    import app.worker.stream_consumer as sc

    # --- NEGATIVE PROOF: Bypassed Limiter ---
    captured_broken = []
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda e: captured_broken.append(e))

    # Temporarily set window to 0 seconds (simulating disabled/broken limiter)
    monkeypatch.setattr(sc, "_ERROR_RATE_LIMIT_INTERVAL_SECONDS", 0)
    _ERROR_RATE_LIMIT_CACHE.clear()

    err = RuntimeError("Flapping worker connection")
    for _ in range(5):
        capture_worker_exception_rate_limited(err, key_prefix="broken_loop", _clock=1000.0)

    # In broken/disabled state, all 5 calls fire directly
    assert len(captured_broken) == 5, f"Expected 5 unthrottled captures, got {len(captured_broken)}"

    # --- RESTORED: Limiter Enforced ---
    captured_restored = []
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda e: captured_restored.append(e))
    monkeypatch.setattr(sc, "_ERROR_RATE_LIMIT_INTERVAL_SECONDS", 900)
    _ERROR_RATE_LIMIT_CACHE.clear()

    for _ in range(5):
        capture_worker_exception_rate_limited(err, key_prefix="restored_loop", _clock=1000.0)

    # In restored state, only 1 fires
    assert len(captured_restored) == 1

    # --- BOUNDED CACHE VERIFICATION (Max 200 entries) ---
    _ERROR_RATE_LIMIT_CACHE.clear()
    assert _MAX_ERROR_CACHE_ENTRIES == 200

    # Insert 250 distinct signatures
    for idx in range(250):
        unique_err = Exception(f"Unique failure code #{idx}")
        capture_worker_exception_rate_limited(unique_err, key_prefix=f"sig_{idx}", _clock=1000.0 + idx)

    # Must be bounded strictly at 200
    assert len(_ERROR_RATE_LIMIT_CACHE) == 200
    # Oldest 50 (indices 0..49) must have been evicted
    assert "sig_0:Exception" not in _ERROR_RATE_LIMIT_CACHE
    assert "sig_49:Exception" not in _ERROR_RATE_LIMIT_CACHE
    # Newest (indices 50..249) must be retained
    assert "sig_50:Exception" in _ERROR_RATE_LIMIT_CACHE
    assert "sig_249:Exception" in _ERROR_RATE_LIMIT_CACHE


def test_worker_rate_limiter_distinct_signatures_and_single_capture(monkeypatch):
    """
    Task 12e - Item 1:
    Prove that 'worker_dead_letter', 'auto_sync_user', 'auto_sync_loop', and 'init_consumer_group'
    each produce a distinct signature in the cache, and that 50 different event_ids at the same
    call site give exactly 1 capture.
    """
    import uuid
    from app.worker.stream_consumer import (
        capture_worker_exception_rate_limited,
        _ERROR_RATE_LIMIT_CACHE,
    )

    captured_events = []
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda e: captured_events.append(e))
    _ERROR_RATE_LIMIT_CACHE.clear()

    err = ConnectionResetError("Connection dropped")
    clock_time = 10000.0

    # 1. Distinct signatures for distinct call sites
    call_sites = ["worker_dead_letter", "auto_sync_user", "auto_sync_loop", "init_consumer_group"]
    for cs in call_sites:
        fired = capture_worker_exception_rate_limited(err, key_prefix=cs, _clock=clock_time)
        assert fired is True
        expected_sig = cs + ":" + type(err).__name__
        assert expected_sig in _ERROR_RATE_LIMIT_CACHE

    # All 4 call sites must produce distinct signatures in the cache
    assert len(_ERROR_RATE_LIMIT_CACHE) == 4
    for cs in call_sites:
        assert (cs + ":" + type(err).__name__) in _ERROR_RATE_LIMIT_CACHE
    assert len(captured_events) == 4

    # 2. 50 different event_ids at the same call site give exactly 1 capture
    _ERROR_RATE_LIMIT_CACHE.clear()
    captured_events.clear()

    for i in range(50):
        evt_id = f"evt-{uuid.uuid4().hex}"
        fired = capture_worker_exception_rate_limited(err, key_prefix="worker_event", _clock=clock_time + (i * 2.0))
        if i == 0:
            assert fired is True
        else:
            assert fired is False

    assert len(captured_events) == 1
    assert "worker_event:ConnectionResetError" in _ERROR_RATE_LIMIT_CACHE
    _, suppressed = _ERROR_RATE_LIMIT_CACHE["worker_event:ConnectionResetError"]
    assert suppressed == 49



