"""
NexOps Encryption Key Rotation CLI Tool

Rotates the Fernet ENCRYPTION_KEY used for encrypting stored OAuth access tokens
and webhook secrets in PostgreSQL across all workspaces.

Usage:
    python scripts/rotate_key.py --old-key <OLD_KEY> --new-key <NEW_KEY>

This script:
1. Bypasses RLS safely for the duration of the migration.
2. Reads all user records containing encrypted secrets.
3. Decrypts with the old key and re-encrypts with the new key.
4. Atomically commits updates to the database.
5. Flushes all stale user cache keys in Redis.
"""

import sys
import os
import argparse
import asyncio
import logging
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlmodel import select

# Add backend root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("nexops.key_rotation")


def decrypt_with_key(cipher_text: str, key_str: str) -> str:
    """Decrypt ciphertext using a specific Fernet key string."""
    if not cipher_text:
        return cipher_text
    f = Fernet(key_str.encode())
    return f.decrypt(cipher_text.encode()).decode()


def encrypt_with_key(plain_text: str, key_str: str) -> str:
    """Encrypt plaintext using a specific Fernet key string."""
    if not plain_text:
        return plain_text
    f = Fernet(key_str.encode())
    return f.encrypt(plain_text.encode()).decode()


async def rotate_keys(old_key: str, new_key: str):
    """Scan all users, re-encrypt credentials from old_key to new_key, and flush Redis cache."""
    # Verify both keys are valid Fernet keys
    try:
        Fernet(old_key.encode())
    except Exception as e:
        logger.error(f"Invalid --old-key format: {e}")
        sys.exit(1)

    try:
        Fernet(new_key.encode())
    except Exception as e:
        logger.error(f"Invalid --new-key format: {e}")
        sys.exit(1)

    if old_key == new_key:
        logger.error("Old key and new key are identical. Rotation aborted.")
        sys.exit(1)

    from app.core.database import async_session
    from app.models.user import User
    from app.core.rls import rls_bypass
    from app.core.redis import invalidate_cache_pattern

    logger.info("Starting database scan for encrypted secrets...")

    rotated_users = 0
    rotated_tokens = 0

    async with async_session() as session:
        async with rls_bypass(session):
            result = await session.execute(select(User))
            users = result.scalars().all()

            for user in users:
                user_updated = False

                # Rotate GitHub Access Token
                if user.github_access_token:
                    try:
                        plain = decrypt_with_key(user.github_access_token, old_key)
                        user.github_access_token = encrypt_with_key(plain, new_key)
                        user_updated = True
                        rotated_tokens += 1
                    except Exception as e:
                        logger.error(f"Failed to rotate github_access_token for user {user.id}: {e}")

                # Rotate PagerDuty Access Token
                if user.pagerduty_access_token:
                    try:
                        plain = decrypt_with_key(user.pagerduty_access_token, old_key)
                        user.pagerduty_access_token = encrypt_with_key(plain, new_key)
                        user_updated = True
                        rotated_tokens += 1
                    except Exception as e:
                        logger.error(f"Failed to rotate pagerduty_access_token for user {user.id}: {e}")

                # Rotate PagerDuty Webhook Secret
                if user.pagerduty_webhook_secret:
                    try:
                        plain = decrypt_with_key(user.pagerduty_webhook_secret, old_key)
                        user.pagerduty_webhook_secret = encrypt_with_key(plain, new_key)
                        user_updated = True
                        rotated_tokens += 1
                    except Exception as e:
                        logger.error(f"Failed to rotate pagerduty_webhook_secret for user {user.id}: {e}")

                if user_updated:
                    session.add(user)
                    rotated_users += 1

            if rotated_users > 0:
                await session.commit()
                logger.info(f"Successfully committed updates for {rotated_users} users ({rotated_tokens} secrets re-encrypted).")
            else:
                logger.info("No stored secrets found requiring rotation.")

    # Flush user caches in Redis
    try:
        await invalidate_cache_pattern("nexops:user:*")
        logger.info("Flushed all cached user sessions from Redis.")
    except Exception as cache_err:
        logger.warning(f"Could not flush Redis cache: {cache_err}")

    logger.info("Key rotation process completed successfully.")


def main():
    parser = argparse.ArgumentParser(description="Rotate NexOps ENCRYPTION_KEY for stored credentials.")
    parser.add_argument("--old-key", required=True, help="Current Fernet base64 key")
    parser.add_argument("--new-key", required=True, help="New Fernet base64 key to migrate to")

    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    asyncio.run(rotate_keys(args.old_key, args.new_key))


if __name__ == "__main__":
    main()
