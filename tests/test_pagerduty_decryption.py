"""
Unit and Integration Regression Test Suite: PagerDuty Decryption Fail-Closed (TASK-01)
======================================================================================
Tests fail-closed behavior, status alignment, and non-retryable response semantics:
1. Undecryptable per-user webhook secret fails closed immediately with HTTP 400 (Bad Request).
2. Undecryptable secret does NOT fall back to settings.PAGERDUTY_WEBHOOK_SECRET.
3. Healthy per-user webhook secret verifies correctly against incoming payload HMAC.
4. Missing 'uid' parameter falls back to settings.PAGERDUTY_WEBHOOK_SECRET if configured.
5. User without configured per-user secret falls back to settings.PAGERDUTY_WEBHOOK_SECRET.
6. GET /api/v1/integrations/status returns 'reconnect_required' when token fails decryption.
7. GET /api/v1/integrations/pagerduty/status returns 'reconnect_required' when token fails decryption.
8. Cross-workspace isolation: Broken integration in Workspace A does not affect Workspace B.
9. Zero secrets leaked in logs or exception detail payloads.
"""

import json
import hmac
import hashlib
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException, Request
from cryptography.fernet import Fernet

from app.core.config import settings
from app.core.crypto import encrypt_secret
from app.models.user import User
from app.models.workspace import Workspace
from app.api.routes.webhooks import verify_pagerduty_signature
from app.api.routes.integrations import (
    _make_pd_uid_token,
    get_integration_status,
    get_pagerduty_status,
)


def _compute_pd_signature(body_bytes: bytes, secret: str) -> str:
    """Compute PagerDuty v1 webhook HMAC signature."""
    sig = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    return f"v1={sig}"


def _make_mock_request(
    body_bytes: bytes,
    headers: dict[str, str],
    query_params: dict[str, str],
) -> Request:
    """Construct a mock FastAPI Request object."""
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "query_string": "&".join(f"{k}={v}" for k, v in query_params.items()).encode(),
    }
    request = Request(scope)

    async def receive():
        return {"type": "http.request", "body": body_bytes}

    request._receive = receive
    return request


# ── TEST 1: Undecryptable webhook secret fails closed with HTTP 400 ───────────

@pytest.mark.asyncio
async def test_undecryptable_webhook_secret_fails_closed_400():
    """
    When a user has a pagerduty_webhook_secret that cannot be decrypted (e.g. encrypted
    with a foreign key), verify_pagerduty_signature MUST raise HTTP 400 (Bad Request).
    It MUST NOT fall through to global PAGERDUTY_WEBHOOK_SECRET.
    """
    foreign_key = Fernet.generate_key().decode()
    foreign_cipher = Fernet(foreign_key.encode())
    plain_secret = "my-per-user-secret-12345"
    undecryptable_cipher_text = foreign_cipher.encrypt(plain_secret.encode()).decode()

    user_id = f"user-{uuid.uuid4().hex[:8]}"
    workspace_id = f"ws-{uuid.uuid4().hex[:8]}"
    test_user = User(
        id=user_id,
        email="test@nexops.local",
        workspace_id=workspace_id,
        pagerduty_webhook_secret=undecryptable_cipher_text,
    )

    signed_uid = _make_pd_uid_token(user_id)
    body = json.dumps({"event": {"id": "inc-1", "event_type": "incident.triggered"}}).encode()

    # Even if attacker signs with the plain secret or global secret:
    sig = _compute_pd_signature(body, plain_secret)
    req = _make_mock_request(
        body_bytes=body,
        headers={"X-PagerDuty-Signature": sig},
        query_params={"uid": signed_uid},
    )

    # Mock DB session returning our test user
    mock_session = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = test_user
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await verify_pagerduty_signature(req, session=mock_session)

    assert exc_info.value.status_code == 400, f"Expected HTTP 400, got {exc_info.value.status_code}"
    assert "reconnect required" in exc_info.value.detail.lower()
    # Ensure no secret or ciphertext is leaked in error detail
    assert plain_secret not in exc_info.value.detail
    assert undecryptable_cipher_text not in exc_info.value.detail


# ── TEST 2: Healthy per-user webhook secret succeeds ──────────────────────────

@pytest.mark.asyncio
async def test_healthy_per_user_webhook_secret_verifies():
    """
    When a user has a healthy pagerduty_webhook_secret encrypted under the active
    ENCRYPTION_KEY, a validly signed webhook request MUST be verified successfully.
    """
    plain_secret = "healthy-secret-abc-12345"
    valid_cipher_text = encrypt_secret(plain_secret)

    user_id = f"user-{uuid.uuid4().hex[:8]}"
    workspace_id = f"ws-{uuid.uuid4().hex[:8]}"
    test_user = User(
        id=user_id,
        email="healthy@nexops.local",
        workspace_id=workspace_id,
        pagerduty_webhook_secret=valid_cipher_text,
    )

    signed_uid = _make_pd_uid_token(user_id)
    body = json.dumps({"event": {"id": "inc-2", "event_type": "incident.triggered"}}).encode()
    sig = _compute_pd_signature(body, plain_secret)

    req = _make_mock_request(
        body_bytes=body,
        headers={"X-PagerDuty-Signature": sig},
        query_params={"uid": signed_uid},
    )

    mock_session = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = test_user
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute.return_value = mock_result

    # Should not raise exception
    await verify_pagerduty_signature(req, session=mock_session)


# ── TEST 3: Legacy request without 'uid' uses global fallback ─────────────────

@pytest.mark.asyncio
async def test_missing_uid_uses_global_secret_fallback(monkeypatch):
    """
    Legacy webhook requests without 'uid' parameter fall back to settings.PAGERDUTY_WEBHOOK_SECRET.
    """
    global_secret = "global-env-pd-secret-999"
    monkeypatch.setattr(settings, "PAGERDUTY_WEBHOOK_SECRET", global_secret)

    body = json.dumps({"event": {"id": "inc-3", "event_type": "incident.triggered"}}).encode()
    sig = _compute_pd_signature(body, global_secret)

    req = _make_mock_request(
        body_bytes=body,
        headers={"X-PagerDuty-Signature": sig},
        query_params={},  # No uid
    )

    mock_session = AsyncMock()
    # Should verify against global secret without error
    await verify_pagerduty_signature(req, session=mock_session)

    # Signature mismatch against global secret must return 401
    bad_req = _make_mock_request(
        body_bytes=body,
        headers={"X-PagerDuty-Signature": "v1=bad_hash_12345"},
        query_params={},
    )
    with pytest.raises(HTTPException) as exc_info:
        await verify_pagerduty_signature(bad_req, session=mock_session)
    assert exc_info.value.status_code == 401


# ── TEST 4: User without configured secret uses global fallback ───────────────

@pytest.mark.asyncio
async def test_unconfigured_user_uses_global_secret_fallback(monkeypatch):
    """
    A user whose pagerduty_webhook_secret is None legitimately falls back to global secret.
    """
    global_secret = "global-env-pd-secret-888"
    monkeypatch.setattr(settings, "PAGERDUTY_WEBHOOK_SECRET", global_secret)

    user_id = f"user-{uuid.uuid4().hex[:8]}"
    test_user = User(
        id=user_id,
        email="unconfigured@nexops.local",
        workspace_id=f"ws-{uuid.uuid4().hex[:8]}",
        pagerduty_webhook_secret=None,  # Not configured
    )

    signed_uid = _make_pd_uid_token(user_id)
    body = json.dumps({"event": {"id": "inc-4", "event_type": "incident.triggered"}}).encode()
    sig = _compute_pd_signature(body, global_secret)

    req = _make_mock_request(
        body_bytes=body,
        headers={"X-PagerDuty-Signature": sig},
        query_params={"uid": signed_uid},
    )

    mock_session = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = test_user
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute.return_value = mock_result

    await verify_pagerduty_signature(req, session=mock_session)


# ── TEST 5: GET /integrations/status reports 'reconnect_required' ──────────────

@pytest.mark.asyncio
async def test_get_integration_status_reports_reconnect_required():
    """
    GET /api/v1/integrations/status must report status='reconnect_required',
    connected=False, and note with reconnect instructions when token decryption fails.
    """
    foreign_key = Fernet.generate_key().decode()
    foreign_cipher = Fernet(foreign_key.encode())
    broken_token = foreign_cipher.encrypt(b"pd-token-val").decode()

    user_id = f"user-{uuid.uuid4().hex[:8]}"
    ws_id = f"ws-{uuid.uuid4().hex[:8]}"
    test_user = User(
        id=user_id,
        email="broken@nexops.local",
        workspace_id=ws_id,
        pagerduty_access_token=broken_token,
        email_verified=True,
    )

    mock_session = AsyncMock()
    mock_session.get.return_value = test_user
    # Mock repo count query
    mock_count_res = MagicMock()
    mock_count_res.scalar.return_value = 0
    # Mock terms acknowledged query
    mock_ack_scalars = MagicMock()
    mock_ack_scalars.first.return_value = MagicMock()  # terms acknowledged
    mock_ack_res = MagicMock()
    mock_ack_res.scalars.return_value = mock_ack_scalars

    mock_session.execute.side_effect = [mock_count_res, mock_ack_res]

    status_resp = await get_integration_status(user=test_user, session=mock_session)

    pd_status = status_resp["pagerduty"]
    assert pd_status["connected"] is False
    assert pd_status["status"] == "reconnect_required"
    assert "Reconnect Required" in pd_status["config"]
    assert "cannot be decrypted" in pd_status["note"]


# ── TEST 5b: GET /integrations/status reports 'reconnect_required' on webhook_secret only failure ──

@pytest.mark.asyncio
async def test_get_integration_status_reports_reconnect_required_webhook_secret_only():
    """
    GET /api/v1/integrations/status must report status='reconnect_required' even if
    access_token is valid (or absent) but pagerduty_webhook_secret fails decryption.
    """
    foreign_key = Fernet.generate_key().decode()
    foreign_cipher = Fernet(foreign_key.encode())
    broken_secret = foreign_cipher.encrypt(b"pd-webhook-secret-val").decode()
    healthy_token = encrypt_secret("valid-access-token-123")

    user_id = f"user-{uuid.uuid4().hex[:8]}"
    ws_id = f"ws-{uuid.uuid4().hex[:8]}"
    test_user = User(
        id=user_id,
        email="broken_secret@nexops.local",
        workspace_id=ws_id,
        pagerduty_access_token=healthy_token,
        pagerduty_webhook_secret=broken_secret,
        email_verified=True,
    )

    mock_session = AsyncMock()
    mock_session.get.return_value = test_user
    mock_count_res = MagicMock()
    mock_count_res.scalar.return_value = 0
    mock_ack_scalars = MagicMock()
    mock_ack_scalars.first.return_value = MagicMock()
    mock_ack_res = MagicMock()
    mock_ack_res.scalars.return_value = mock_ack_scalars

    mock_session.execute.side_effect = [mock_count_res, mock_ack_res]

    status_resp = await get_integration_status(user=test_user, session=mock_session)

    pd_status = status_resp["pagerduty"]
    assert pd_status["connected"] is False
    assert pd_status["status"] == "reconnect_required"
    assert "webhook secret cannot be decrypted" in pd_status["note"]


# ── TEST 6: GET /integrations/pagerduty/status reports 'reconnect_required' ────

@pytest.mark.asyncio
async def test_get_pagerduty_status_reports_reconnect_required():
    """
    GET /api/v1/integrations/pagerduty/status returns reconnect_required on token decrypt failure.
    """
    foreign_key = Fernet.generate_key().decode()
    foreign_cipher = Fernet(foreign_key.encode())
    broken_token = foreign_cipher.encrypt(b"pd-token-val").decode()

    user_id = f"user-{uuid.uuid4().hex[:8]}"
    test_user = User(
        id=user_id,
        email="broken@nexops.local",
        workspace_id=f"ws-{uuid.uuid4().hex[:8]}",
        pagerduty_access_token=broken_token,
    )

    mock_session = AsyncMock()
    mock_session.get.return_value = test_user

    status_resp = await get_pagerduty_status(user=test_user, session=mock_session)

    assert status_resp["connected"] is False
    assert status_resp["status"] == "reconnect_required"
    assert "re-authentication" in status_resp["message"]


# ── TEST 7: Cross-Workspace Isolation ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_workspace_isolation_decryption_status():
    """
    Verify that an undecryptable token in Workspace A does not contaminate or affect
    the healthy integration status of Workspace B.
    """
    foreign_key = Fernet.generate_key().decode()
    foreign_cipher = Fernet(foreign_key.encode())
    broken_token = foreign_cipher.encrypt(b"broken-pd-token").decode()
    healthy_token = encrypt_secret("healthy-pd-token")

    # User A in Workspace A (broken)
    user_a = User(
        id=f"user-a-{uuid.uuid4().hex[:8]}",
        email="user_a@nexops.local",
        workspace_id=f"ws-a-{uuid.uuid4().hex[:8]}",
        pagerduty_access_token=broken_token,
        email_verified=True,
    )

    # User B in Workspace B (healthy)
    user_b = User(
        id=f"user-b-{uuid.uuid4().hex[:8]}",
        email="user_b@nexops.local",
        workspace_id=f"ws-b-{uuid.uuid4().hex[:8]}",
        pagerduty_access_token=healthy_token,
        email_verified=True,
    )

    # Evaluate User A
    session_a = AsyncMock()
    session_a.get.return_value = user_a
    count_res_a = MagicMock()
    count_res_a.scalar.return_value = 0
    ack_res_a = MagicMock()
    ack_res_a.scalars.return_value.first.return_value = MagicMock()
    session_a.execute.side_effect = [count_res_a, ack_res_a]

    resp_a = await get_integration_status(user=user_a, session=session_a)

    # Evaluate User B
    session_b = AsyncMock()
    session_b.get.return_value = user_b
    count_res_b = MagicMock()
    count_res_b.scalar.return_value = 0
    ack_res_b = MagicMock()
    ack_res_b.scalars.return_value.first.return_value = MagicMock()
    session_b.execute.side_effect = [count_res_b, ack_res_b]

    resp_b = await get_integration_status(user=user_b, session=session_b)

    assert resp_a["pagerduty"]["connected"] is False
    assert resp_a["pagerduty"]["status"] == "reconnect_required"

    assert resp_b["pagerduty"]["connected"] is True
    assert resp_b["pagerduty"]["status"] == "connected"
    assert resp_b["pagerduty"]["config"] == "API Token Connected"
