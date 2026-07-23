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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.core.security import init_firebase
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

# ── CORS Middleware ──────────────────────────────────────────────────────
# In production CORS_ORIGINS must be set to the exact deployed frontend URL.
# The fallback covers local development and the specific production frontend.
# The regex allows Vercel preview deployments for this project only.
origins = settings.cors_origins_list or [
    "http://localhost:3000",
    "http://localhost:5173",
    "https://nexops-frontend.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://nexops-frontend(-[a-z0-9]+)?\.vercel\.app",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    expose_headers=["Content-Length"],
)

# ── Rate Limiting ───────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ── Register API Routes ─────────────────────────────────────────────────
from app.api.routes import repos, events, alerts, insights, users, analytics, integrations, webhooks, dependencies, incidents, deployments, executor

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
app.include_router(executor.router, prefix=settings.API_PREFIX)

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


@app.get("/health", tags=["System"])
@limiter.exempt
async def health_check():
    """Basic health check endpoint."""
    import os
    return {
        "status": "operational",
        "service": settings.APP_NAME,
        "version": "1.0.0",
        "commit_sha": os.getenv("RENDER_GIT_COMMIT", "0d502fa"),
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
