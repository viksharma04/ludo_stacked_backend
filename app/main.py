import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, profile

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Ludo Stacked API")
    logger.debug("Debug mode: %s", settings.DEBUG)
    yield
    logger.info("Shutting down Ludo Stacked API")


settings = get_settings()

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
logger.debug("Routers registered: /api/v1/auth, /api/v1/profile")


@app.get("/")
def root():
    return {"message": "Ludo Stacked API"}


@app.get("/health")
def health():
    return {"status": "healthy"}
