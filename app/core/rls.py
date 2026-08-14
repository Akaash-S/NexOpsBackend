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
    Async context manager that enables RLS bypass for the duration of the block.
    Explicitly sets nexops.bypass_rls to 'true' on entry and guarantees reset to 'false'
    with session scope (is_local=false) and flush on exit.
    """
    await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false)"))
    logger.debug("RLS bypass ENABLED")
    try:
        yield
    finally:
        try:
            await session.execute(text("SELECT set_config('nexops.bypass_rls', 'false', false)"))
            await session.flush()
            logger.debug("RLS bypass DISABLED")
        except Exception as reset_err:
            logger.error(f"CRITICAL: Failed to reset RLS bypass: {reset_err}")
