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

_user_cache = {}

def invalidate_user_cache(user_id: str):
    """Invalidates the in-memory cache for a given user ID."""
    _user_cache.pop(user_id, None)

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    session: AsyncSession = Depends(get_session)
):
    """
    Verify Firebase ID token and ensure the user exists in the SQL database.
    Any token failure raises 401 — there are no dev-mode bypasses.
    """
    # Verify the Firebase ID token — unconditionally, in all environments.
    try:
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

    # Serve from cache if available
    if uid in _user_cache:
        user = User(**_user_cache[uid])
        from sqlalchemy import text
        if user.workspace_id:
            await session.execute(
                text("SELECT set_config('nexops.current_workspace_id', :workspace_id, false), set_config('nexops.current_user_id', :user_id, false)"),
                {"workspace_id": user.workspace_id, "user_id": user.id}
            )
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

        _user_cache[uid] = user.model_dump()
        from sqlalchemy import text
        if user.workspace_id:
            await session.execute(
                text("SELECT set_config('nexops.current_workspace_id', :workspace_id, false), set_config('nexops.current_user_id', :user_id, false)"),
                {"workspace_id": user.workspace_id, "user_id": user.id}
            )
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
