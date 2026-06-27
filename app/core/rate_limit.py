"""
Shared slowapi Limiter instance for the NexOps backend.

Created in its own module to avoid circular imports — both main.py and
individual route files need access to the same limiter instance.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],
    headers_enabled=True,
)
