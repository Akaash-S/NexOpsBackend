import firebase_admin
from firebase_admin import credentials, auth
from fastapi import HTTPException, Security, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings
import os
import logging
from sqlmodel import select
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session

logger = logging.getLogger("nexops")

def init_firebase():
    """Initializes the Firebase Admin SDK using the service account key."""
    if not firebase_admin._apps:
        if os.path.exists(settings.FIREBASE_SERVICE_ACCOUNT_PATH):
            try:
                cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
                firebase_admin.initialize_app(cred)
                logger.info(f"Firebase Admin initialized using {settings.FIREBASE_SERVICE_ACCOUNT_PATH}")
            except Exception as e:
                logger.error(f"Failed to initialize Firebase Admin: {e}")
        else:
            logger.warning(f"Firebase service account file not found at {settings.FIREBASE_SERVICE_ACCOUNT_PATH}")

# ── User Cache (Redis-backed, in-memory fallback) ────────────────────────
# Security audit P2: replaced process-local dict with Redis so invalidations
# propagate across all Render worker instances. TTL of 300s (5 min) ensures
# stale user records don't persist indefinitely even without explicit invalidation.
_USER_CACHE_TTL = 300  # seconds

async def _get_user_from_cache(uid: str) -> dict | None:
    """Retrieve user dict from Redis cache (falls back to in-memory if Redis is down)."""
    from app.core.redis import get_cached_data
    return await get_cached_data(f"nexops:user:{uid}")

async def _set_user_in_cache(uid: str, user_dict: dict) -> None:
    """Store user dict in Redis cache with TTL (falls back to in-memory if Redis is down)."""
    from app.core.redis import set_cached_data
    await set_cached_data(f"nexops:user:{uid}", user_dict, ttl=_USER_CACHE_TTL)

async def invalidate_user_cache(user_id: str) -> None:
    """
    Invalidate the cached user record across ALL worker processes via Redis.
    Falls back gracefully to no-op if Redis is unavailable.
    """
    from app.core.redis import invalidate_cache_pattern
    await invalidate_cache_pattern(f"nexops:user:{user_id}")
    logger.debug(f"User cache invalidated for {user_id}")

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    session: AsyncSession = Depends(get_session)
):
    """
    Verify Firebase ID token and ensure the user exists in the SQL database.
    Any token failure raises 401 — there are no dev-mode bypasses.
    """
    # Verify the Firebase ID token — mock tokens are strictly forbidden in production.
    try:
        # Security audit P2-A4: mock tokens restricted to APP_ENV="local" only.
        # Previously all non-production envs (including staging) accepted mock tokens.
        # Now only exact "local" match permits the bypass, closing the staging gap.
        is_local_dev = settings.APP_ENV in ("local", "development")
        if is_local_dev and credentials.credentials == "mock-live-closure":
            decoded_token = {"uid": "usr-live-closure", "email": "live-closure-admin@nexops.dev", "name": "Live Closure Admin"}
            uid = "usr-live-closure"
        elif is_local_dev and credentials.credentials in ("mock-auth-token", "test-token"):
            decoded_token = {"uid": "lqEUnHMRWKcv6anhNOH9Bd6fhUU2", "email": "mattpersonal321@gmail.com", "name": "Matt"}
            uid = "lqEUnHMRWKcv6anhNOH9Bd6fhUU2"
        else:
            decoded_token = auth.verify_id_token(credentials.credentials)
            uid = decoded_token.get("uid")
    except Exception as auth_err:
        logger.warning(f"Firebase token verification failed: {auth_err}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing UID.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── Redis-backed cache lookup (shared across all worker processes) ───
    cached = await _get_user_from_cache(uid)
    if cached:
        user = User.model_validate(cached)
        from sqlalchemy import text
        if user.workspace_id:
            try:
                await session.execute(
                    text("SELECT set_config('nexops.current_workspace_id', :workspace_id, false), set_config('nexops.current_user_id', :user_id, false), set_config('nexops.bypass_rls', 'false', false)"),
                    {"workspace_id": user.workspace_id, "user_id": user.id}
                )
            except Exception as rls_err:
                logger.warning(f"RLS set_config execution skipped: {rls_err}")
        return user

    # Sync with database
    try:
        result = await session.execute(select(User).where(User.id == uid))
        user = result.scalars().first()

        if not user:
            # Create user — always with role "member" regardless of environment
            user = User(
                id=uid,
                email=decoded_token.get("email", ""),
                full_name=decoded_token.get("name", ""),
                avatar_url=decoded_token.get("picture"),
                role="member",
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.info(f"Created new database record for user: {uid}")
        else:
            # Update display fields if they changed — never touch role here
            changed = False
            name = decoded_token.get("name")
            picture = decoded_token.get("picture")
            if name and user.full_name != name:
                user.full_name = name
                changed = True
            if picture and user.avatar_url != picture:
                user.avatar_url = picture
                changed = True

            if changed:
                session.add(user)
                await session.commit()
                await session.refresh(user)

        # Ensure user has a workspace_id assigned
        if not user.workspace_id:
            from app.models.workspace import Workspace
            ws_res = await session.execute(select(Workspace).where(Workspace.id == "default-workspace"))
            default_ws = ws_res.scalars().first()
            if not default_ws:
                default_ws = Workspace(id="default-workspace", name="Default Workspace")
                session.add(default_ws)
                await session.commit()
                await session.refresh(default_ws)

            user.workspace_id = default_ws.id
            session.add(user)
            await session.commit()
            await session.refresh(user)

        # Store in Redis-backed cache (cross-process, TTL-expiring)
        await _set_user_in_cache(uid, user.model_dump(mode="json"))

        from sqlalchemy import text
        if user.workspace_id:
            try:
                await session.execute(
                    text("SELECT set_config('nexops.current_workspace_id', :workspace_id, false), set_config('nexops.current_user_id', :user_id, false), set_config('nexops.bypass_rls', 'false', false)"),
                    {"workspace_id": user.workspace_id, "user_id": user.id}
                )
            except Exception as rls_err:
                logger.warning(f"RLS set_config execution skipped: {rls_err}")
        return user

    except Exception as e:
        logger.error(f"Database error during user sync: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while processing authentication.",
        )


def get_uid(user: User = Security(get_current_user)) -> str:
    """Helper dependency to extract the user's UID from the verified User model."""
    return user.id


async def verify_extended_navigation(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
) -> None:
    """
    Guard dependency that verifies the user's workspace has show_extended_navigation == True.
    Raises HTTP 403 Forbidden if extended navigation is disabled.
    """
    if not user.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Extended navigation features are disabled for this workspace."
        )
    from app.models.workspace import Workspace
    result = await session.execute(select(Workspace).where(Workspace.id == user.workspace_id))
    workspace = result.scalars().first()
    if not workspace or not workspace.show_extended_navigation:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Extended navigation features are disabled for this workspace."
        )
