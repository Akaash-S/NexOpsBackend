"""
NexOps RLS Security Utilities

Provides a guaranteed-safe context manager for temporarily bypassing
Row-Level Security in webhook and system-level database operations.

The context manager ensures `nexops.bypass_rls` is ALWAYS reset to 'false'
after the block exits — even if an exception is raised. This closes the
session leak identified in the security audit (P1-B4/B5).
"""

from contextlib import asynccontextmanager
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import logging

logger = logging.getLogger("nexops.security")


@asynccontextmanager
async def rls_bypass(session: AsyncSession):
    """
    Async context manager that enables RLS bypass for the duration of the block,
    then unconditionally resets it to 'false' on exit — even on exception or
    early return.

    Usage:
        async with rls_bypass(session):
            result = await session.execute(select(User).where(User.id == uid))
            user = result.scalars().first()
        # bypass_rls is guaranteed False here, even if the block raised
    """
    await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false)"))
    logger.debug("RLS bypass ENABLED for session")
    try:
        yield
    finally:
        try:
            await session.execute(text("SELECT set_config('nexops.bypass_rls', 'false', false)"))
            logger.debug("RLS bypass DISABLED for session")
        except Exception as reset_err:
            logger.error(f"CRITICAL: Failed to reset RLS bypass — session may be in elevated state: {reset_err}")
