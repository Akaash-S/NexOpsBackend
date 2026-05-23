import firebase_admin
from firebase_admin import credentials, auth
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings
import os
import logging
from sqlmodel import select
from app.models.user import User

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

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security)
):
    """
    Verify Firebase token AND ensure the user exists in our SQL database.
    In development mode, falls back to a mock user if Firebase is uninitialized.
    """
    try:
        uid = None
        decoded_token = {}

        # 1. Attempt to verify the ID token sent from the client
        try:
            decoded_token = auth.verify_id_token(credentials.credentials)
            uid = decoded_token.get("uid")
        except Exception as auth_err:
            if settings.APP_ENV == "development":
                logger.warning(f"Development Auth Fallback: {auth_err}")
                uid = "dev-user-123"
                decoded_token = {
                    "uid": uid,
                    "email": "dev@nexops.local",
                    "name": "Local Developer",
                    "picture": None
                }
            else:
                raise auth_err
        
        # Check in-memory cache first to avoid slow DB queries
        if uid and uid in _user_cache:
            return _user_cache[uid]

        # 2. Sync with local database
        from app.core.database import async_session
        async with async_session() as session:
            result = await session.execute(select(User).where(User.id == uid))
            user = result.scalars().first()
            
            if not user:
                # Create user record in our DB
                user = User(
                    id=uid,
                    email=decoded_token.get("email", ""),
                    full_name=decoded_token.get("name", "Developer"),
                    avatar_url=decoded_token.get("picture"),
                    role="admin" if settings.APP_ENV == "development" else "member"
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
                logger.info(f"Created new database record for user: {uid}")
            else:
                # Only update and commit if there is actual change
                changed = False
                name = decoded_token.get("name")
                picture = decoded_token.get("picture")
                if name and user.full_name != name:
                    user.full_name = name
                    changed = True
                if picture and user.avatar_url != picture:
                    user.avatar_url = picture
                    changed = True
                if settings.APP_ENV == "development" and user.role != "admin":
                    user.role = "admin"
                    changed = True
                
                if changed:
                    session.add(user)
                    await session.commit()
                    await session.refresh(user)
            
            _user_cache[uid] = user
            return user
            
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        if settings.APP_ENV == "development":
             return User(id="dev-fallback", email="dev@nexops.local", full_name="Fallback Dev", role="admin")
             
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired authentication credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

def get_uid(user: User = Security(get_current_user)) -> str:
    """Helper dependency to extract the user's UID from the verified User model."""
    return user.id
