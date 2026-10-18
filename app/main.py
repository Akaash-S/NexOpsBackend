"""
NexOps Backend — Main Application Entry Point

A production-ready DevOps intelligence engine built with FastAPI.
Manages repositories, processes events, executes automation rules,
and provides real-time insights.
"""

import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import logging
from contextlib import asynccontextmanager
import secrets
import hmac
from fastapi import FastAPI, Depends, Request, Response, status, HTTPException
from fastapi.security.utils import get_authorization_scheme_param
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import init_db, get_session
from app.core.security import init_firebase, get_current_user
from app.core.sentry import init_sentry
from app.core.rate_limit import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-7s | %(message)s",
)
# Silence verbose logs from third-party libraries
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)

logger = logging.getLogger("nexops")


def mask_database_url(url_str: str) -> str:
    """
    Mask user, password, and host in database connection URL.
    Returns only driver and database name (e.g. 'postgresql+asyncpg://[MASKED]/nexops_dev').
    """
    if not url_str:
        return "[EMPTY]"
    try:
        from sqlalchemy.engine import make_url
        u = make_url(url_str)
        dbname = u.database or ""
        return f"{u.drivername}://[MASKED]/{dbname}"
    except Exception:
        parts = url_str.split("://", 1)
        driver = parts[0] if len(parts) > 1 else "unknown"
        dbname = url_str.rsplit("/", 1)[-1].split("?")[0] if "/" in url_str else "unknown"
        return f"{driver}://[MASKED]/{dbname}"


def mask_redis_url(url_str: str) -> str:
    """
    Mask credentials, host, and port in Redis connection URL.
    Returns scheme and database index only (e.g. 'redis://[MASKED]/0').
    """
    if not url_str:
        return "[EMPTY]"
    try:
        from urllib.parse import urlsplit
        p = urlsplit(url_str)
        scheme = p.scheme or "redis"
        db = p.path.lstrip("/") or "0"
        return f"{scheme}://[MASKED]/{db}"
    except Exception:
        return "redis://[MASKED]"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle events."""
    # --- Startup ---
    logger.info("-" * 60)
    logger.info(f"  {settings.APP_NAME} Engine Starting...")
    logger.info(f"  Environment: {settings.APP_ENV}")
    logger.info(f"  Database: {mask_database_url(settings.DATABASE_URL)}")
    logger.info(f"  Redis: {mask_redis_url(settings.REDIS_URL)}")
    logger.info("-" * 60)

    # Security Guard: Refuse to start if mock authentication is enabled in production
    import os
    if settings.APP_ENV == "production":
        if getattr(settings, "ALLOW_MOCK_AUTH", False) or os.getenv("ALLOW_MOCK_AUTH", "").lower() in ("true", "1"):
            logger.critical("FATAL: Refusing to start — mock authentication is strictly forbidden in production!")
            raise RuntimeError("Refusing to start: Mock authentication is strictly forbidden in production (APP_ENV=production).")

    # Initialize Firebase Admin
    init_firebase()

    # Initialize Redis check
    from app.core.redis import init_redis
    await init_redis()

    # Initialize database tables
    await init_db()
    logger.info("Database tables initialized")

    # Start Redis WS broadcast listener background task
    from app.core.websocket import start_ws_redis_listener
    listener_task = asyncio.create_task(start_ws_redis_listener())

    yield

    # --- Shutdown ---
    logger.info("NexOps Engine shutting down...")
    
    # Cancel Redis WS broadcast listener
    listener_task.cancel()
    await asyncio.gather(listener_task, return_exceptions=True)


# ── API docs: only available outside production ──────────────────────────
_is_production = settings.APP_ENV == "production"

# ── Sentry Monitoring ────────────────────────────────────────────────────
init_sentry("nexops-api")

# --- Create FastAPI App ---
app = FastAPI(
    title=settings.APP_NAME,
    description="DevOps Intelligence & Automation Engine",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
)

# ── Rate Limiting ────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ── Trusted Proxy Headers (P3 rate-limit fix) ─────────────────────────────
# Render (and most PaaS load-balancers) forwards the real client IP in
# X-Forwarded-For. Without this middleware, get_remote_address() returns the
# proxy IP — causing all users to share a single rate-limit bucket.
try:
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
    logger.info("ProxyHeadersMiddleware registered — real client IPs will be used for rate limiting")
except ImportError:
    logger.warning("uvicorn not available — ProxyHeadersMiddleware skipped (rate limiting keyed by proxy IP)")

# ── CORS Middleware (Outermost Middleware - Added Last) ─────────────────
# Must be added LAST so it wraps all inner middlewares (including SlowAPIMiddleware)
# and guarantees Access-Control-Allow-Origin headers on all responses (2xx, 4xx, and 5xx).
configured_origins = settings.cors_origins_list if settings.CORS_ORIGINS else []
default_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "https://nexops.asolvitra.tech",
]

origins = list(dict.fromkeys(configured_origins + default_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost:\d+",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "*",
        "Authorization",
        "Content-Type",
        "X-Hub-Signature-256",
        "X-PagerDuty-Signature",
        "X-GitHub-Event",
        "X-Requested-With",
        "X-Workspace-ID",
    ],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)

from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_unhandled_exception_handler(request, exc):
    logger.error(f"Global unhandled exception on {request.method} {request.url}: {exc}", exc_info=True)
    origin = request.headers.get("origin", "*")
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred while processing your request."},
        headers={
            "Access-Control-Allow-Origin": origin if origin else "*",
            "Access-Control-Allow-Credentials": "false",
            "Access-Control-Allow-Headers": "*",
        }
    )

# ── Register API Routes ─────────────────────────────────────────────────
from app.api.routes import repos, events, alerts, insights, users, analytics, integrations, webhooks, dependencies, incidents, deployments, workspaces, auth

app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(repos.router, prefix=settings.API_PREFIX)
app.include_router(events.router, prefix=settings.API_PREFIX)
app.include_router(alerts.router, prefix=settings.API_PREFIX)
app.include_router(insights.router, prefix=settings.API_PREFIX)
app.include_router(users.router, prefix=settings.API_PREFIX)
app.include_router(analytics.router, prefix=settings.API_PREFIX)
app.include_router(integrations.router, prefix=settings.API_PREFIX)
app.include_router(webhooks.router, prefix=settings.API_PREFIX)
app.include_router(dependencies.router, prefix=settings.API_PREFIX)
app.include_router(incidents.router, prefix=settings.API_PREFIX)
app.include_router(deployments.router, prefix=settings.API_PREFIX)
app.include_router(workspaces.router, prefix=settings.API_PREFIX)

from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect, Query
from app.core.websocket import manager
from firebase_admin import auth as firebase_auth

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    """
    WebSocket endpoint. Firebase token is always required — no dev-mode bypass.
    """
    try:
        if not token:
            raise Exception("Session token is missing.")

        # Verify the ID token against Firebase unconditionally
        decoded_token = firebase_auth.verify_id_token(token)
        uid = decoded_token.get("uid")
        if not uid:
            raise Exception("Invalid session token payload.")

    except Exception as auth_err:
        logger.warning(f"WebSocket connection rejected: {auth_err}")
        await websocket.accept()
        await websocket.close(code=4001)  # 4001: Unauthorized session
        return

    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and wait for client messages if needed
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
        manager.disconnect(websocket)


from datetime import datetime, timezone
START_TIME = datetime.now(timezone.utc)


@app.get("/health", tags=["System"])
@app.get(f"{settings.API_PREFIX}/health", tags=["System"])
@limiter.exempt
async def health_check():
    """
    Public health check — returns minimal status only.
    Uptime monitors and load balancers should call this endpoint.
    Detailed diagnostics (DB branch, latency, worker state) are available
    on /health/detailed which requires a valid Firebase auth token.
    """
    import time
    from sqlalchemy import text
    from app.core.database import async_session
    from app.core.redis import redis_client as _redis

    db_ok = False
    redis_ok = False
    try:
        async with async_session() as s:
            await s.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        logger.warning(f"Health DB check failed: {e}")

    try:
        if _redis:
            await _redis.ping()
            redis_ok = True
    except Exception:
        pass

    status = "operational" if (db_ok and redis_ok) else "degraded"
    return {
        "status": status,
        "service": settings.APP_NAME,
        "version": "1.0.0",
    }


async def verify_health_check_access(
    request: Request,
):
    """
    Verify caller has permission to view detailed system health diagnostics.
    Permits access exclusively via HEALTH_CHECK_SECRET (X-Health-Check-Secret header
    or Authorization: Bearer <secret>). Fails closed when HEALTH_CHECK_SECRET is unset or empty.
    Never logs the secret.
    """
    secret = (settings.HEALTH_CHECK_SECRET or "").strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Health check secret is not configured.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    provided = None
    header_secret = request.headers.get("X-Health-Check-Secret")
    if header_secret:
        provided = header_secret
    else:
        auth_header = request.headers.get("Authorization")
        if auth_header:
            scheme, param = get_authorization_scheme_param(auth_header)
            if scheme.lower() == "bearer" and param:
                provided = param

    if provided:
        try:
            provided_bytes = provided.encode("utf-8")
            secret_bytes = secret.encode("utf-8")
            if hmac.compare_digest(provided_bytes, secret_bytes):
                return "health_secret_authorized"
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required for detailed health diagnostics.",
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.get("/health/detailed", tags=["System"])
@app.get(f"{settings.API_PREFIX}/health/detailed", tags=["System"])
@limiter.exempt
async def health_check_detailed(
    response: Response,
    auth=Depends(verify_health_check_access)
):
    """
    Protected detailed health check — runs read-only diagnostic queries:
    1. Database connection (SELECT 1)
    2. Events query with timezone-aware datetime comparison (created_at >= now - 7d)
    3. Alerts query with timezone-aware datetime comparison (created_at >= now - 7d)
    4. Current Alembic migration revision from alembic_version table
    5. Redis ping and latency
    Returns HTTP 200 and pass status if all checks succeed, or HTTP 503 and fail if any check fails.
    """
    import os
    import time
    import httpx
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import text, type_coerce, DateTime, func
    from sqlmodel import select
    from app.core.database import async_session
    from app.core.redis import redis_client as _redis
    from app.models.event import Event
    from app.models.alert import Alert

    now_utc = datetime.now(timezone.utc)
    uptime_seconds = round((now_utc - START_TIME).total_seconds(), 2)

    checks = {}
    all_passed = True

    # 1. Database Connection
    db_connected = False
    db_latency_ms = 0.0
    db_branch = "unknown"
    try:
        db_url_str = settings.DATABASE_URL or ""
        if "@" in db_url_str:
            host_part = db_url_str.split("@")[1].split("/")[0]
            db_branch = host_part.split(".")[0]
        elif "://" in db_url_str:
            db_branch = db_url_str.split("://")[1].split("/")[0]
        t0 = time.perf_counter()
        async with async_session() as session:
            res = await session.execute(text("SELECT 1"))
            res.scalar()
        db_connected = True
        db_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        checks["database_connection"] = {"status": "pass", "latency_ms": db_latency_ms}
    except Exception as e:
        logger.warning(f"Health/detailed DB connection error: {e}")
        checks["database_connection"] = {"status": "fail", "latency_ms": db_latency_ms, "error": str(e)}
        all_passed = False

    # 2. Events Query (reuse exact real service query pattern without type_coerce)
    events_count = 0
    events_latency_ms = 0.0
    try:
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        t0 = time.perf_counter()
        async with async_session() as session:
            stmt = select(func.count(Event.id)).where(Event.created_at >= seven_days_ago)
            res = await session.execute(stmt)
            events_count = res.scalar() or 0
        events_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        checks["database_events_query"] = {"status": "pass", "latency_ms": events_latency_ms, "count": events_count}
    except Exception as e:
        logger.warning(f"Health/detailed events query error: {e}")
        checks["database_events_query"] = {"status": "fail", "latency_ms": events_latency_ms, "error": str(e)}
        all_passed = False

    # 3. Alerts Query (reuse exact real service query pattern without type_coerce)
    alerts_count = 0
    alerts_latency_ms = 0.0
    try:
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        t0 = time.perf_counter()
        async with async_session() as session:
            stmt = select(func.count(Alert.id)).where(Alert.created_at >= seven_days_ago)
            res = await session.execute(stmt)
            alerts_count = res.scalar() or 0
        alerts_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        checks["database_alerts_query"] = {"status": "pass", "latency_ms": alerts_latency_ms, "count": alerts_count}
    except Exception as e:
        logger.warning(f"Health/detailed alerts query error: {e}")
        checks["database_alerts_query"] = {"status": "fail", "latency_ms": alerts_latency_ms, "error": str(e)}
        all_passed = False

    # 4. Alembic Revision Check
    alembic_rev = None
    alembic_latency_ms = 0.0
    try:
        t0 = time.perf_counter()
        async with async_session() as session:
            res = await session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            alembic_rev = res.scalar()
        if not alembic_rev:
            raise ValueError("No revision found in alembic_version table")
        alembic_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        checks["database_alembic_revision"] = {"status": "pass", "revision": alembic_rev, "latency_ms": alembic_latency_ms}
    except Exception as e:
        logger.warning(f"Health/detailed Alembic revision check error: {e}")
        checks["database_alembic_revision"] = {"status": "fail", "latency_ms": alembic_latency_ms, "error": str(e)}
        all_passed = False

    # 5. Redis Ping Check
    redis_connected = False
    redis_latency_ms = 0.0
    queue_depth = 0
    worker_last_heartbeat = None
    try:
        if not _redis:
            raise RuntimeError("Redis client is not configured")
        t0 = time.perf_counter()
        if await _redis.ping():
            redis_connected = True
            redis_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            checks["redis_ping"] = {"status": "pass", "latency_ms": redis_latency_ms}
            try:
                queue_depth = await _redis.xlen("nexops:events")
            except Exception:
                pass
            try:
                hb = await _redis.get("nexops:worker:heartbeat")
                if hb:
                    worker_last_heartbeat = hb.decode() if isinstance(hb, bytes) else str(hb)
            except Exception:
                pass
        else:
            raise RuntimeError("Redis ping returned False")
    except Exception as e:
        logger.warning(f"Health/detailed Redis error: {e}")
        checks["redis_ping"] = {"status": "fail", "latency_ms": redis_latency_ms, "error": str(e)}
        all_passed = False

    # 6. Integrations Reachability (diagnostic only)
    gh_reachable, gh_latency_ms = False, 0.0
    pd_reachable, pd_latency_ms = False, 0.0
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            try:
                t0 = time.perf_counter()
                r = await client.get("https://api.github.com/zen", headers={"User-Agent": "NexOps-HealthCheck"})
                if r.status_code in (200, 403):
                    gh_reachable = True
                    gh_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            except Exception:
                pass
            try:
                t0 = time.perf_counter()
                r = await client.get("https://api.pagerduty.com/", headers={"User-Agent": "NexOps-HealthCheck"}, follow_redirects=True)
                if r.status_code in (200, 401):
                    pd_reachable = True
                    pd_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Health/detailed HTTP error: {e}")

    # 6. Package Versions Check (installed vs pinned requirements.txt)
    package_versions = {}
    expected_versions = {}
    version_mismatches = []
    core_packages = ["sqlmodel", "sqlalchemy", "asyncpg", "pydantic", "fastapi"]

    from pathlib import Path
    import importlib.metadata
    pinned_map = {
        "fastapi": "0.115.6",
        "sqlmodel": "0.0.22",
        "sqlalchemy": "2.0.36",
        "asyncpg": "0.29.0",
        "pydantic": "2.12.5",
    }
    try:
        req_file = Path(__file__).resolve().parent.parent / "requirements.txt"
        if req_file.exists():
            for req_line in req_file.read_text(encoding="utf-8").splitlines():
                req_line = req_line.strip()
                for pkg in core_packages:
                    if req_line.startswith(f"{pkg}=="):
                        pinned_map[pkg] = req_line.split("==")[1].strip()
                    elif pkg == "sqlalchemy" and req_line.startswith("sqlalchemy[asyncio]=="):
                        pinned_map["sqlalchemy"] = req_line.split("==")[1].strip()
    except Exception:
        pass

    for pkg in core_packages:
        expected = pinned_map.get(pkg)
        expected_versions[pkg] = expected
        try:
            inst = importlib.metadata.version(pkg)
            package_versions[pkg] = inst
            if expected and inst != expected:
                version_mismatches.append(f"{pkg} installed ({inst}) != expected ({expected})")
        except Exception as e:
            package_versions[pkg] = f"error: {e}"
            version_mismatches.append(f"{pkg} not found: {e}")

    checks["package_versions"] = {
        "status": "pass" if not version_mismatches else "fail",
        "installed": package_versions,
        "expected": expected_versions,
        "mismatches": version_mismatches,
    }
    if version_mismatches:
        all_passed = False

    overall_status = "pass" if all_passed else "fail"
    if not all_passed:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    deployed_at = os.getenv("RENDER_DEPLOYED_AT")
    if not deployed_at:
        iso_str = START_TIME.isoformat()
        deployed_at = iso_str.replace("+00:00", "Z") if "+00:00" in iso_str else (iso_str + "Z" if not iso_str.endswith("Z") else iso_str)

    return {
        "status": overall_status,
        "service": settings.APP_NAME,
        "version": "1.0.0",
        "package_versions": package_versions,
        "commit_sha": os.getenv("RENDER_GIT_COMMIT", "unknown"),
        "deployed_at": deployed_at,
        "uptime_seconds": uptime_seconds,
        "checks": checks,
        "database": {"connected": db_connected, "branch": db_branch, "latency_ms": db_latency_ms, "revision": alembic_rev},
        "redis": {"connected": redis_connected, "latency_ms": redis_latency_ms},
        "worker": {"last_heartbeat_at": worker_last_heartbeat, "queue_depth": queue_depth},
        "integrations": {
            "github": {"reachable": gh_reachable, "latency_ms": gh_latency_ms},
            "pagerduty": {"reachable": pd_reachable, "latency_ms": pd_latency_ms},
        },
    }


@app.get("/", tags=["System"])
async def root():
    """Root endpoint with API info."""
    return {
        "service": settings.APP_NAME,
        "description": "DevOps Intelligence & Automation Engine",
        "health": "/health",
        "api_prefix": settings.API_PREFIX,
    }
