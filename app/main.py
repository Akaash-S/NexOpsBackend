"""
NexOps Backend — Main Application Entry Point

A production-ready DevOps intelligence engine built with FastAPI.
Manages repositories, processes events, executes automation rules,
and provides real-time insights.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.core.security import init_firebase

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-24s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
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

    # Initialize database tables
    await init_db()
    logger.info("Database tables initialized")

    yield

    # --- Shutdown ---
    logger.info("NexOps Engine shutting down...")


# --- Create FastAPI App ---
app = FastAPI(
    title=settings.APP_NAME,
    description="DevOps Intelligence & Automation Engine",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS Middleware ──────────────────────────────────────────────────────
origins = settings.cors_origins_list or ["http://localhost:3000", "http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ── Register API Routes ─────────────────────────────────────────────────
from app.api.routes import repos, events, alerts, rules, insights, users, teams, workspaces, pipelines, analytics, integrations, webhooks, dependencies, clusters

app.include_router(repos.router, prefix=settings.API_PREFIX)
app.include_router(events.router, prefix=settings.API_PREFIX)
app.include_router(alerts.router, prefix=settings.API_PREFIX)
app.include_router(rules.router, prefix=settings.API_PREFIX)
app.include_router(insights.router, prefix=settings.API_PREFIX)
app.include_router(users.router, prefix=settings.API_PREFIX)
app.include_router(teams.router, prefix=settings.API_PREFIX)
app.include_router(workspaces.router, prefix=settings.API_PREFIX)
app.include_router(pipelines.router, prefix=settings.API_PREFIX)
app.include_router(analytics.router, prefix=settings.API_PREFIX)
app.include_router(integrations.router, prefix=settings.API_PREFIX)
app.include_router(webhooks.router, prefix=settings.API_PREFIX)
app.include_router(dependencies.router, prefix=settings.API_PREFIX)
app.include_router(clusters.router, prefix=settings.API_PREFIX)

from fastapi import WebSocket, WebSocketDisconnect
from app.core.websocket import manager

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and wait for client messages if needed
            data = await websocket.receive_text()
            # Echo or process client messages (optional)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
        manager.disconnect(websocket)
@app.get("/health", tags=["System"])
async def health_check():
    """Basic health check endpoint."""
    return {
        "status": "operational",
        "service": settings.APP_NAME,
        "version": "1.0.0",
    }


@app.get("/", tags=["System"])
async def root():
    """Root endpoint with API info."""
    return {
        "service": settings.APP_NAME,
        "description": "DevOps Intelligence & Automation Engine",
        "docs": "/docs",
        "health": "/health",
        "api_prefix": settings.API_PREFIX,
    }
