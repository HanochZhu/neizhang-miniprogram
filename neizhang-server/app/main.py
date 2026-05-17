import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import engine, Base
import app.models  # noqa: F401 — register all ORM tables before create_all
from app.routers import auth, chat, files, finance, admin, teams


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: create tables on startup."""
    # Startup: create all database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create upload directory if it doesn't exist
    os.makedirs(settings.upload_dir, exist_ok=True)

    yield

    # Shutdown: dispose the engine
    await engine.dispose()


app = FastAPI(
    title="内账 API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS - allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for uploads
static_dir = settings.upload_dir
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Include routers
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(files.router)
app.include_router(finance.router)
app.include_router(admin.router)
app.include_router(teams.router)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
