"""
Sentry Error Monitoring Integration for NexOps Backend & Worker.

Privacy compliance:
- send_default_pii=False
- before_send hook strips:
  - Authorization, Cookie, Set-Cookie, and all X-* secret headers
  - Request bodies (never send webhook payloads or user data)
  - Query strings containing tokens/passwords/keys
  - User emails and IP addresses
  - Regex redacts database URLs, Fernet tokens, JWTs, Bearer tokens, and email addresses.
- Minimal sample rates (traces_sample_rate=0.0). No profiling, no replay.
"""

import os
import re
import logging
import subprocess
from typing import Any, Dict, Optional
import sentry_sdk

logger = logging.getLogger("nexops.sentry")

# Patterns for sensitive tokens, emails, DB URLs
EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
DB_URL_REGEX = re.compile(r'(postgres(ql)?(\+[a-zA-Z0-9_]+)?|redis(s)?|mysql|sqlite)://[^\s\'"<>]+')
BEARER_REGEX = re.compile(r'(?i)bearer\s+[A-Za-z0-9_\-\.]+')
FERNET_REGEX = re.compile(r'gAAAAAB[A-Za-z0-9_\-]{50,}')
JWT_REGEX = re.compile(r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}')
TOKEN_KEY_VALUE_REGEX = re.compile(r'(?i)\b(token|key|secret|password|api_key|auth)[=:\s]+(["\']?)([A-Za-z0-9_\-\.]+)\2')
GENERIC_SECRET_KEY_REGEX = re.compile(r'(?i)(secret|token|password|api_key|auth|credential|access_token|private_key|webhook_secret|encryption_key)')


def scrub_value(val: Any) -> Any:
    """Recursively scrub values within dictionaries, lists, and strings."""
    if isinstance(val, str):
        val = EMAIL_REGEX.sub("[REDACTED_EMAIL]", val)
        val = DB_URL_REGEX.sub("[REDACTED_DB_URL]", val)
        val = BEARER_REGEX.sub("Bearer [REDACTED_TOKEN]", val)
        val = FERNET_REGEX.sub("[REDACTED_FERNET_TOKEN]", val)
        val = JWT_REGEX.sub("[REDACTED_JWT]", val)
        val = TOKEN_KEY_VALUE_REGEX.sub(r"\1=[REDACTED_TOKEN]", val)
        return val
    elif isinstance(val, dict):
        scrubbed = {}
        for k, v in val.items():
            k_lower = str(k).lower()
            if (
                GENERIC_SECRET_KEY_REGEX.search(k_lower)
                or k_lower.startswith("x-")
                or k_lower in ("authorization", "cookie", "set-cookie")
            ):
                scrubbed[k] = "[REDACTED]"
            else:
                scrubbed[k] = scrub_value(v)
        return scrubbed
    elif isinstance(val, list):
        return [scrub_value(item) for item in val]
    return val


def before_send_handler(event: Dict[str, Any], hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Sentry before_send privacy hook.
    Mandatory compliance:
    - Strips Authorization, Cookie, Set-Cookie, and all X-* secret headers
    - Strips request bodies completely (never send webhook payloads or user data)
    - Strips tokens and sensitive params from query strings
    - Strips user email and IP address
    - Recursively scrubs tokens, passwords, database URLs, and emails across breadcrumbs, exceptions, and extra context.
    """
    if not event:
        return event

    # 1. Scrub request data
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            new_headers = {}
            for k, v in headers.items():
                k_lower = str(k).lower()
                if (
                    k_lower in ("authorization", "cookie", "set-cookie")
                    or k_lower.startswith("x-")
                    or GENERIC_SECRET_KEY_REGEX.search(k_lower)
                ):
                    continue  # Strip header completely
                new_headers[k] = scrub_value(v)
            request["headers"] = new_headers

        # Redact request body completely (webhook payloads, json data, etc.)
        if "data" in request:
            request["data"] = "[REDACTED_BODY]"

        # Redact cookies
        if "cookies" in request:
            request["cookies"] = "[REDACTED]"

        # Redact query string
        query_string = request.get("query_string")
        if query_string:
            if isinstance(query_string, str):
                scrubbed_qs = re.sub(
                    r'(?i)(token|key|secret|password|auth|code|api_key)=([^&]+)',
                    r'\1=[REDACTED]',
                    query_string
                )
                request["query_string"] = scrub_value(scrubbed_qs)
            elif isinstance(query_string, dict):
                request["query_string"] = scrub_value(query_string)

    # 2. Scrub user info (strictly no email, no IP)
    user = event.get("user")
    if isinstance(user, dict):
        user.pop("email", None)
        user.pop("ip_address", None)
        user.pop("username", None)
        if "id" in user:
            user["id"] = scrub_value(user["id"])

    # 3. Recursively scrub breadcrumbs
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        event["breadcrumbs"] = scrub_value(breadcrumbs)
    elif isinstance(breadcrumbs, list):
        event["breadcrumbs"] = [scrub_value(b) for b in breadcrumbs]

    # 4. Recursively scrub extra, contexts, tags
    if "extra" in event and isinstance(event["extra"], dict):
        event["extra"] = scrub_value(event["extra"])
    if "contexts" in event and isinstance(event["contexts"], dict):
        event["contexts"] = scrub_value(event["contexts"])
    if "tags" in event and isinstance(event["tags"], dict):
        event["tags"] = scrub_value(event["tags"])

    # 5. Scrub exception values
    exception = event.get("exception")
    if isinstance(exception, dict):
        event["exception"] = scrub_value(exception)

    return event


def get_git_commit_sha() -> Optional[str]:
    """Retrieve git release commit SHA from Render environment or local git."""
    sha = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GIT_COMMIT_SHA")
    if sha:
        return sha
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return None


def init_sentry(service_name: str = "nexops-api") -> bool:
    """
    Initialize Sentry SDK if SENTRY_DSN is configured.
    If SENTRY_DSN is unset, logs that Sentry is disabled and returns False.
    """
    from app.core.config import settings

    dsn = getattr(settings, "SENTRY_DSN", None) or os.environ.get("SENTRY_DSN")
    if not dsn:
        logger.info(f"Sentry is disabled for {service_name} (SENTRY_DSN is not set).")
        return False

    environment = getattr(settings, "APP_ENV", None) or os.environ.get("APP_ENV", "local")
    release = get_git_commit_sha()

    integrations = []
    if service_name == "nexops-api":
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        integrations.extend([
            FastApiIntegration(transaction_style="endpoint"),
            StarletteIntegration(transaction_style="endpoint"),
        ])

    sentry_sdk.init(
        dsn=dsn,
        integrations=integrations,
        environment=environment,
        release=release,
        send_default_pii=False,
        before_send=before_send_handler,
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
    )
    sentry_sdk.set_tag("service", service_name)
    logger.info(f"Sentry initialized for {service_name} (environment={environment}, release={release})")
    return True
