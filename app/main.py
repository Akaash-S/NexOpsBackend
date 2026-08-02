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
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.core.security import init_firebase, get_current_user
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle events."""
    # --- Startup ---
    logger.info("-" * 60)
    logger.info(f"  {settings.APP_NAME} Engine Starting...")
    logger.info(f"  Environment: {settings.APP_ENV}")
    logger.info(f"  Database: {settings.DATABASE_URL[:40]}...")
    logger.info("-" * 60)

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
    "https://nexops-frontend.vercel.app",
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
from app.api.routes import repos, events, alerts, insights, users, analytics, integrations, webhooks, dependencies, incidents, deployments, workspaces

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


from datetime import datetime
START_TIME = datetime.utcnow()


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
    db_branch = "unknown"
    try:
        db_url_str = settings.DATABASE_URL or ""
        if "@" in db_url_str:
            host_part = db_url_str.split("@")[1].split("/")[0]
            db_branch = host_part.split(".")[0]
        elif "://" in db_url_str:
            db_branch = db_url_str.split("://")[1].split("/")[0]

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
        "database": {
            "connected": db_ok,
            "branch": db_branch,
        }
    }


@app.get("/health/detailed", tags=["System"])
@app.get(f"{settings.API_PREFIX}/health/detailed", tags=["System"])
@limiter.exempt
async def health_check_detailed(user=Depends(get_current_user)):
    """
    Authenticated detailed health check — exposes latencies, DB branch, worker
    heartbeat, and integration reachability. Requires a valid Firebase ID token.
    Security audit P3-I2: infra metadata gated behind auth.
    """
    import os
    import time
    import httpx
    from datetime import datetime
    from sqlalchemy import text
    from app.core.database import async_session
    from app.core.redis import redis_client as _redis

    now = datetime.utcnow()
    uptime_seconds = round((now - START_TIME).total_seconds(), 2)

    # 1. Database
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
    except Exception as e:
        logger.warning(f"Health/detailed DB error: {e}")

    # 2. Redis
    redis_connected = False
    redis_latency_ms = 0.0
    queue_depth = 0
    worker_last_heartbeat = None
    try:
        if _redis:
            t0 = time.perf_counter()
            if await _redis.ping():
                redis_connected = True
                redis_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
                try:
                    queue_depth = await _redis.xlen("nexops:events:stream")
                except Exception:
                    pass
                try:
                    hb = await _redis.get("nexops:worker:heartbeat")
                    if hb:
                        worker_last_heartbeat = hb.decode() if isinstance(hb, bytes) else str(hb)
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Health/detailed Redis error: {e}")

    # 3. Integrations reachability
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

    overall_status = "operational" if (db_connected and redis_connected) else "degraded"
    return {
        "status": overall_status,
        "service": settings.APP_NAME,
        "version": "1.0.0",
        "commit_sha": os.getenv("RENDER_GIT_COMMIT", "unknown"),
        "deployed_at": os.getenv("RENDER_DEPLOYED_AT", START_TIME.isoformat() + "Z"),
        "uptime_seconds": uptime_seconds,
        "database": {"connected": db_connected, "branch": db_branch, "latency_ms": db_latency_ms},
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
