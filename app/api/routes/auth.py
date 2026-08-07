"""
Auth & Email Verification Routes
Provides OTP generation, hashing, rate-limiting, and verification for manual email signups.
"""

import time
import asyncio
import secrets
import string
import hmac
import hashlib
import logging
import re
from typing import Optional
from pydantic import BaseModel, field_validator
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from firebase_admin import auth as firebase_auth

from app.core.config import settings
from app.core.database import get_session
from app.core.redis import get_cached_data, set_cached_data, delete_cached_data
from app.models.user import User
from app.models.workspace import Workspace

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger("nexops.auth")

# Static blocklist of disposable email providers for Part 2d defense-in-depth
DISPOSABLE_DOMAINS = {
    "mailinator.com",
    "guerrillamail.com",
    "10minutemail.com",
    "tempmail.com",
    "throwawaymail.com",
    "yopmail.com",
    "trashmail.com",
    "sharklasers.com",
    "dispostable.com",
    "getairmail.com",
    "maildrop.cc",
    "fakemailgenerator.com",
}

_OTP_TTL_SECONDS = 600       # 10 minutes code validity
_COOLDOWN_TTL_SECONDS = 60    # 60 seconds resend cooldown
_MAX_ATTEMPTS = 5            # Lockout after 5 wrong attempts


def _hash_email(email: str) -> str:
    """Consistently hash email address for Redis key indexing."""
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()[:32]


def _hash_otp(email: str, code: str) -> str:
    """Cryptographically hash OTP code using HMAC-SHA256 with server encryption key as salt."""
    payload = f"{email.lower().strip()}:{code.strip()}"
    return hmac.new(
        settings.ENCRYPTION_KEY.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()


EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class OTPRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or not EMAIL_REGEX.match(v):
            raise ValueError("Invalid email address format.")
        return v


class OTPVerifyRequest(BaseModel):
    email: str
    code: str

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or not EMAIL_REGEX.match(v):
            raise ValueError("Invalid email address format.")
        return v


@router.post("/otp/request")
async def request_email_otp(
    payload: OTPRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    Generate and dispatch a 6-digit OTP code to the specified email address.
    Enforces disposable domain blocking, 60s resend cooldown, and HMAC code hashing.
    """
    email_clean = payload.email.lower().strip()
    domain = email_clean.split("@")[-1]

    # 1. Disposable Domain Blocklist Check
    if domain in DISPOSABLE_DOMAINS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Disposable email addresses are not permitted. Please use your work or personal email address."
        )

    email_hash = _hash_email(email_clean)
    cooldown_key = f"nexops:otp:cooldown:{email_hash}"
    otp_key = f"nexops:otp:{email_hash}"

    # 2. Resend Cooldown Check (60 seconds)
    in_cooldown = await get_cached_data(cooldown_key)
    if in_cooldown:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Please wait 60 seconds before requesting another verification code."
        )

    # 3. Generate 6-digit CSPRNG numeric code
    otp_code = "".join(secrets.choice(string.digits) for _ in range(6))
    hashed_code = _hash_otp(email_clean, otp_code)

    now = time.time()
    otp_data = {
        "hashed_code": hashed_code,
        "attempts": 0,
        "expires_at": now + _OTP_TTL_SECONDS
    }

    # Store hashed OTP code in Redis (TTL = 10 minutes)
    await set_cached_data(otp_key, otp_data, ttl=_OTP_TTL_SECONDS)
    # Set resend cooldown indicator in Redis (TTL = 60 seconds)
    await set_cached_data(cooldown_key, {"cooldown": True}, ttl=_COOLDOWN_TTL_SECONDS)

    # Dispatch email via SMTP background task
    from app.services.email_service import send_otp_email
    asyncio.create_task(send_otp_email(email_clean, otp_code))

    logger.info(f"Generated 6-digit Email OTP for {email_clean} (Expires in 10m). Code: {otp_code}")

    return {
        "status": "otp_sent",
        "email": email_clean,
        "expires_in_seconds": _OTP_TTL_SECONDS,
        "cooldown_seconds": _COOLDOWN_TTL_SECONDS,
        "dev_code": otp_code if settings.APP_ENV in ("local", "development") else None
    }


@router.post("/otp/verify")
async def verify_email_otp(
    payload: OTPVerifyRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    Verify submitted 6-digit OTP code against Redis hashed record.
    Enforces 10-minute expiry, 5-attempt lockout, single-use deletion, and marks user.email_verified = True.
    """
    email_clean = payload.email.lower().strip()
    code_clean = payload.code.strip()
    email_hash = _hash_email(email_clean)
    otp_key = f"nexops:otp:{email_hash}"
    cooldown_key = f"nexops:otp:cooldown:{email_hash}"

    otp_data = await get_cached_data(otp_key)

    # 1. Expiry Check
    if not otp_data or time.time() > otp_data.get("expires_at", 0):
        if otp_data:
            await delete_cached_data(otp_key)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired. Please request a new code."
        )

    attempts = otp_data.get("attempts", 0)

    # 2. Attempt Limit Lockout Check (Max 5 Attempts)
    if attempts >= _MAX_ATTEMPTS:
        await delete_cached_data(otp_key)
        await delete_cached_data(cooldown_key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many invalid attempts. This verification code has been locked out. Please request a fresh code."
        )

    # 3. Compare Hash
    submitted_hash = _hash_otp(email_clean, code_clean)
    stored_hash = otp_data.get("hashed_code", "")

    if not hmac.compare_digest(submitted_hash, stored_hash):
        attempts += 1
        otp_data["attempts"] = attempts
        if attempts >= _MAX_ATTEMPTS:
            await delete_cached_data(otp_key)
            await delete_cached_data(cooldown_key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many invalid attempts. This verification code has been locked out. Please request a fresh code."
            )
        else:
            remaining = _MAX_ATTEMPTS - attempts
            ttl_remaining = max(1, int(otp_data.get("expires_at", 0) - time.time()))
            await set_cached_data(otp_key, otp_data, ttl=ttl_remaining)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid verification code. {remaining} attempt(s) remaining."
            )

    # 4. Success -> Single-Use Invalidation (Delete OTP immediately)
    await delete_cached_data(otp_key)
    await delete_cached_data(cooldown_key)

    # 5. Provision or update User in SQL database (Bypass RLS for cross-tenant user lookup by email)
    from sqlalchemy import text
    await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false)"))

    result = await session.execute(select(User).where(User.email == email_clean))
    user = result.scalars().first()

    if not user:
        # Create a new user with unique workspace ID and email_verified = True
        uid = f"usr-{secrets.token_hex(8)}"
        user_ws_id = f"ws-{uid[:12]}"

        ws_res = await session.execute(select(Workspace).where(Workspace.id == user_ws_id))
        user_ws = ws_res.scalars().first()
        if not user_ws:
            from sqlalchemy import text
            await session.execute(
                text("SELECT set_config('nexops.current_workspace_id', :ws_id, false), set_config('nexops.bypass_rls', 'true', false)"),
                {"ws_id": user_ws_id}
            )
            user_ws = Workspace(id=user_ws_id, name=f"{email_clean.split('@')[0]}'s Workspace", color="blue")
            session.add(user_ws)
            await session.flush()

        user = User(
            id=uid,
            email=email_clean,
            full_name=email_clean.split("@")[0].capitalize(),
            role="member",
            workspace_id=user_ws_id,
            email_verified=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    else:
        if not user.email_verified:
            user.email_verified = True
            session.add(user)
            await session.commit()
            await session.refresh(user)

    # 6. Issue Firebase Custom Auth Token
    custom_token_bytes = firebase_auth.create_custom_token(user.id)
    custom_token = custom_token_bytes.decode("utf-8") if isinstance(custom_token_bytes, bytes) else str(custom_token_bytes)

    logger.info(f"Successfully verified email OTP for {user.email} (ID: {user.id}). Marked email_verified = True.")

    return {
        "status": "verified",
        "email": user.email,
        "user_id": user.id,
        "custom_token": custom_token,
        "workspace_id": user.workspace_id
    }
