import firebase_admin
from firebase_admin import credentials, auth
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings
import os

import logging

logger = logging.getLogger("nexops")

# Initialize Firebase Admin SDK
def init_firebase():
    """Initializes the Firebase Admin SDK using the service account key."""
    if not firebase_admin._apps:
        # Check if the service account file exists
        if os.path.exists(settings.FIREBASE_SERVICE_ACCOUNT_PATH):
            try:
                cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
                firebase_admin.initialize_app(cred)
                logger.info(f"Firebase Admin initialized using {settings.FIREBASE_SERVICE_ACCOUNT_PATH}")
            except Exception as e:
                logger.error(f"Failed to initialize Firebase Admin: {e}")
        else:
            logger.warning(f"Firebase service account file not found at {settings.FIREBASE_SERVICE_ACCOUNT_PATH}")
            logger.warning("Backend authentication will fail until the service-account.json is provided.")

from sqlmodel import select
from app.core.database import get_session
from app.models.user import User

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security)
):
    """
    Verify Firebase token AND ensure the user exists in our SQL database.
    """
    try:
        # 1. Verify the ID token sent from the client
        decoded_token = auth.verify_id_token(credentials.credentials)
        uid = decoded_token.get("uid")
        
        # 2. Sync with local database
        # We need a session here. Since this is a dependency, we'll open a session manually
        # or use the context manager.
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
                    role="member"
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
                logger.info(f"Created new database record for user: {uid}")
            
            # Return the full User model object
            return user
            
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired authentication credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

def get_uid(user: User = Security(get_current_user)) -> str:
    """Helper dependency to extract the user's UID from the verified User model."""
    return user.id
