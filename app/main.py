import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.dependencies.redis import close_redis_client
from app.dependencies.supabase import close_async_supabase, init_async_supabase
from app.routers import auth, profile, rooms, ws
from app.services.websocket.auth import close_ws_authenticator
from app.services.websocket.manager import get_connection_manager

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Ludo Stacked API")
    logger.debug("Debug mode: %s", settings.DEBUG)

    # Initialize async Supabase client
    await init_async_supabase()
    logger.info("Async Supabase client initialized")

    # Initialize WebSocket connection manager and start cleanup task
    connection_manager = get_connection_manager()
    await connection_manager.start_cleanup_task()
    logger.info("WebSocket connection manager initialized")

    yield

    # Shutdown: stop cleanup task, close all connections, close Redis, close clients
    logger.info("Shutting down Ludo Stacked API")
    await connection_manager.stop_cleanup_task()
    await connection_manager.close_all_connections()
    await close_ws_authenticator()
    await close_async_supabase()
    await close_redis_client()
    logger.info("WebSocket, Supabase, and Redis cleanup complete")


app = FastAPI(
    title="Ludo Stacked API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.debug("CORS configured with origins: %s", settings.CORS_ORIGINS)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(profile.router, prefix="/api/v1")
app.include_router(rooms.router, prefix="/api/v1")
app.include_router(ws.router, prefix="/api/v1")
logger.debug("Routers registered: /api/v1/auth, /api/v1/profile, /api/v1/rooms, /api/v1/ws")


@app.get("/")
def root():
    return {"message": "Ludo Stacked API"}


@app.get("/health")
def health():
    return {"status": "healthy"}
