"""
Sentry Error Monitoring Integration for NexOps Backend & Worker.

Privacy compliance:
- send_default_pii=False
<<<<<<< HEAD
- include_local_variables=False (SDK 2.x default is True; explicitly set False to prevent local variable values in stack frames)
- max_request_body_size="never"
- before_send hook strips:
  - Authorization, Cookie, Set-Cookie, and all X-* secret headers
  - Request bodies completely (never send webhook payloads or user data)
  - Query strings containing tokens/passwords/keys
  - User emails and IP addresses
  - Regex redacts database URLs, Fernet tokens, JWTs, Bearer tokens, GitHub tokens,
    PagerDuty tokens, Firebase ID tokens, and email addresses.
  - Runtime secret values (HEALTH_CHECK_SECRET, SENTRY_DSN, ENCRYPTION_KEY, *_WEBHOOK_SECRET)
  - Exception messages and SQLAlchemy DBAPIError / StatementError parameters and statements.
- before_breadcrumb hook scrubs all breadcrumbs (including LoggingIntegration) before storage.
=======
- before_send hook strips:
  - Authorization, Cookie, Set-Cookie, and all X-* secret headers
  - Request bodies (never send webhook payloads or user data)
  - Query strings containing tokens/passwords/keys
  - User emails and IP addresses
  - Regex redacts database URLs, Fernet tokens, JWTs, Bearer tokens, and email addresses.
>>>>>>> origin/main
- Minimal sample rates (traces_sample_rate=0.0). No profiling, no replay.
"""

import os
import re
import logging
import subprocess
<<<<<<< HEAD
from typing import Any, Dict, List, Optional
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

logger = logging.getLogger("nexops.sentry")

# Patterns for sensitive tokens, emails, DB URLs, credentials
EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
DB_URL_REGEX = re.compile(r'(postgres(ql)?(\+[a-zA-Z0-9_]+)?|redis(s)?|mysql|sqlite)://[^\s\'"<>]+')
BEARER_REGEX = re.compile(r'(?i)bearer\s+[A-Za-z0-9_\-\.]+')
FERNET_REGEX = re.compile(r'gAAAAAB[A-Za-z0-9_\-=]{20,}')
JWT_REGEX = re.compile(r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}')
# GitHub tokens: ghp_ (PAT), gho_ (OAuth), ghu_ (user), ghs_ (server), ghr_ (refresh), github_pat_ (fine-grained)
GITHUB_TOKEN_REGEX = re.compile(r'\b(gh[pousr]_[A-Za-z0-9_]{10,}|github_pat_[A-Za-z0-9_]{10,})\b')
# PagerDuty tokens: API tokens (u+..., pd_..., y_...) and keys
PAGERDUTY_TOKEN_REGEX = re.compile(r'\b(u\+[A-Za-z0-9_\-]{8,}|pd_[A-Za-z0-9_\-]{8,}|y_[A-Za-z0-9_\-]{8,})\b')
# SQLAlchemy formatted statement parameters: [parameters: (...)] or [parameters: {...}]
SQLALCHEMY_PARAMS_REGEX = re.compile(r'\[parameters:\s*(\([^)]*\)|\{[^}]*\})\]')
TOKEN_KEY_VALUE_REGEX = re.compile(r'(?i)\b(token|key|secret|password|api_key|auth)[=:\s]+(["\']?)([A-Za-z0-9_\-\.+]+)\2')
GENERIC_SECRET_KEY_REGEX = re.compile(r'(?i)(secret|token|password|api_key|auth|credential|access_token|private_key|webhook_secret|encryption_key|dsn)')


def get_runtime_secrets() -> List[str]:
    """
    Extract runtime secrets from application settings and environment variables.
    Covers HEALTH_CHECK_SECRET, SENTRY_DSN, ENCRYPTION_KEY, and any *_WEBHOOK_SECRET.
    Sorted longest first to prevent partial replacements.
    """
    secrets_found = set()
    try:
        from app.core.config import settings
        for attr in dir(settings):
            if (
                attr in ("HEALTH_CHECK_SECRET", "SENTRY_DSN", "ENCRYPTION_KEY")
                or attr.endswith("_WEBHOOK_SECRET")
                or attr.endswith("_SECRET")
            ):
                val = getattr(settings, attr, None)
                if val and isinstance(val, str) and len(val.strip()) >= 4:
                    secrets_found.add(val.strip())
    except Exception:
        pass

    for k, v in os.environ.items():
        if (
            k in ("HEALTH_CHECK_SECRET", "SENTRY_DSN", "ENCRYPTION_KEY")
            or k.endswith("_WEBHOOK_SECRET")
        ):
            if v and isinstance(v, str) and len(v.strip()) >= 4:
                secrets_found.add(v.strip())

    return sorted(list(secrets_found), key=len, reverse=True)


def scrub_value(val: Any) -> Any:
    """Recursively scrub values within dictionaries, lists, strings, and exceptions."""
    if isinstance(val, str):
        # 1. Scrub runtime secret values first
        for secret in get_runtime_secrets():
            if secret in val:
                val = val.replace(secret, "[REDACTED_SECRET]")

        # 2. Scrub specific token patterns
        val = GITHUB_TOKEN_REGEX.sub("[REDACTED_GITHUB_TOKEN]", val)
        val = PAGERDUTY_TOKEN_REGEX.sub("[REDACTED_PAGERDUTY_TOKEN]", val)
        val = FERNET_REGEX.sub("[REDACTED_FERNET_TOKEN]", val)
        val = JWT_REGEX.sub("[REDACTED_JWT]", val)
        val = EMAIL_REGEX.sub("[REDACTED_EMAIL]", val)
        val = DB_URL_REGEX.sub("[REDACTED_DB_URL]", val)
        val = SQLALCHEMY_PARAMS_REGEX.sub("[parameters: [REDACTED_PARAMS]]", val)
        val = BEARER_REGEX.sub("Bearer [REDACTED_TOKEN]", val)
        val = TOKEN_KEY_VALUE_REGEX.sub(r"\1=[REDACTED_TOKEN]", val)
        return val

=======
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
>>>>>>> origin/main
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
<<<<<<< HEAD

    elif isinstance(val, (list, tuple)):
        scrubbed_seq = [scrub_value(item) for item in val]
        return tuple(scrubbed_seq) if isinstance(val, tuple) else scrubbed_seq

    return val


def before_breadcrumb_handler(crumb: Dict[str, Any], hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Sentry before_breadcrumb privacy hook.
    Ensures that breadcrumbs collected by LoggingIntegration or HTTP integrations
    cannot carry secrets, tokens, PII, or credentials into the event breadcrumbs list.
    """
    if not crumb:
        return crumb
    return scrub_value(crumb)


=======
    elif isinstance(val, list):
        return [scrub_value(item) for item in val]
    return val


>>>>>>> origin/main
def before_send_handler(event: Dict[str, Any], hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Sentry before_send privacy hook.
    Mandatory compliance:
    - Strips Authorization, Cookie, Set-Cookie, and all X-* secret headers
    - Strips request bodies completely (never send webhook payloads or user data)
    - Strips tokens and sensitive params from query strings
<<<<<<< HEAD
    - Strips user email, IP address, and username
    - Recursively scrubs tokens, passwords, database URLs, and emails across breadcrumbs, exceptions, and extra context.
    - Strips SQLAlchemy DBAPIError/StatementError parameters and statements.
=======
    - Strips user email and IP address
    - Recursively scrubs tokens, passwords, database URLs, and emails across breadcrumbs, exceptions, and extra context.
>>>>>>> origin/main
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

<<<<<<< HEAD
    # 2. Scrub user info (strictly no email, no IP, no username)
=======
    # 2. Scrub user info (strictly no email, no IP)
>>>>>>> origin/main
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

<<<<<<< HEAD
    # 5. Scrub exception values and SQLAlchemy DBAPIError parameters
    exc_info = hint.get("exc_info")
    if exc_info:
        try:
            exc_type, exc_val, exc_tb = exc_info
            if hasattr(exc_val, "params") and exc_val.params is not None:
                exc_val.params = scrub_value(exc_val.params)
            if hasattr(exc_val, "statement") and exc_val.statement is not None:
                exc_val.statement = scrub_value(exc_val.statement)
            if hasattr(exc_val, "args") and exc_val.args:
                exc_val.args = tuple(scrub_value(a) for a in exc_val.args)
        except Exception:
            pass

    exception = event.get("exception")
    if isinstance(exception, dict):
        event["exception"] = scrub_value(exception)
        # Deep scrub in values list
        for item in event["exception"].get("values", []):
            if isinstance(item, dict):
                if "value" in item:
                    item["value"] = scrub_value(item["value"])
                stacktrace = item.get("stacktrace")
                if isinstance(stacktrace, dict):
                    for frame in stacktrace.get("frames", []):
                        if "vars" in frame:
                            frame["vars"] = scrub_value(frame["vars"])
                if "mechanism" in item and isinstance(item["mechanism"], dict):
                    item["mechanism"] = scrub_value(item["mechanism"])
=======
    # 5. Scrub exception values
    exception = event.get("exception")
    if isinstance(exception, dict):
        event["exception"] = scrub_value(exception)
>>>>>>> origin/main

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

<<<<<<< HEAD
    # Logging integration configured so breadcrumbs and log events cannot leak secrets
    logging_integration = LoggingIntegration(
        level=logging.INFO,
        event_level=logging.ERROR,
    )
    integrations = [logging_integration]

=======
    integrations = []
>>>>>>> origin/main
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
<<<<<<< HEAD
        include_local_variables=False,
        max_request_body_size="never",
        before_send=before_send_handler,
        before_breadcrumb=before_breadcrumb_handler,
=======
        before_send=before_send_handler,
>>>>>>> origin/main
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
    )
    sentry_sdk.set_tag("service", service_name)
    logger.info(f"Sentry initialized for {service_name} (environment={environment}, release={release})")
    return True
