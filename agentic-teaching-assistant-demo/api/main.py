"""
FastAPI Application Entry Point

This module creates the FastAPI app instance with CORS configuration
and includes all route modules.
"""

import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add parent directory to path for imports
parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from common.debug import get_debug_logger
from common.storage_mount import detect_storage_mount, env_flag, is_running_in_container
logger = get_debug_logger(__name__)


def _verify_storage_mount_or_fail() -> None:
    """Prevent silent user-data loss when storage is not mounted persistently."""
    save_to = Path(os.environ.get("AGENTICTA_SAVE_TO", "/workspace/mnt/")).resolve()
    require_mount = env_flag(
        "AGENTICTA_REQUIRE_STORAGE_MOUNT",
        is_running_in_container(),
    )
    sentinel_file = os.environ.get("AGENTICTA_STORAGE_SENTINEL_FILE")

    try:
        save_to.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise RuntimeError(
            f"Storage path '{save_to}' is not writable/creatable: {exc}"
        ) from exc

    has_mount, mount_checks, sentinel_path = detect_storage_mount(save_to, sentinel_file=sentinel_file)
    writable = os.access(save_to, os.W_OK)

    logger.info(
        "Storage check: path=%s has_mount=%s writable=%s require_mount=%s checks=%s sentinel=%s",
        save_to,
        has_mount,
        writable,
        require_mount,
        mount_checks,
        sentinel_path,
    )

    if not writable:
        raise RuntimeError(
            f"Storage path '{save_to}' is not writable. "
            "This will break account persistence."
        )

    if require_mount and not has_mount:
        raise RuntimeError(
            f"Storage path '{save_to}' is not on a mounted volume. "
            f"Detection checks: {mount_checks}. "
            "Set up persistent storage at AGENTICTA_SAVE_TO, configure "
            "AGENTICTA_STORAGE_SENTINEL_FILE, or disable this guard with "
            "AGENTICTA_REQUIRE_STORAGE_MOUNT=false (not recommended)."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown events."""
    # Startup
    logger.info("AgenticTA API starting up...")
    
    # Prevent silent account loss due to ephemeral container storage.
    _verify_storage_mount_or_fail()
    
    # Check backend availability
    try:
        from api.dependencies import get_backend
        backend = get_backend()
        if backend.is_available("nodes"):
            logger.info("Backend modules available")
        else:
            logger.warning("Backend modules not available - running in mock mode")
    except Exception as e:
        logger.warning("Backend check failed: %s", e)
    
    yield
    
    # Shutdown
    logger.info("AgenticTA API shutting down...")


# Create FastAPI app
app = FastAPI(
    title="AgenticTA API",
    description="AI-powered Teaching Assistant backend API",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS for frontend
# In production, restrict origins to specific domains
ALLOWED_ORIGINS = os.environ.get(
    "CORS_ORIGINS", 
    "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://localhost:8000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,  # Cache preflight for 10 minutes
)


# Import and include routes
from api.routes import auth, curriculum, chat, files, quiz, calendar, youtube, upload_ui, upload_image_ui

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(curriculum.router, prefix="/api/curriculum", tags=["Curriculum"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(files.router, prefix="/api/files", tags=["Files"])
app.include_router(quiz.router, prefix="/api/quiz", tags=["Quiz"])
app.include_router(calendar.router, prefix="/api/calendar", tags=["Calendar"])
app.include_router(youtube.router, prefix="/api/youtube", tags=["YouTube"])
app.include_router(upload_ui.router, tags=["Upload UI"])
app.include_router(upload_image_ui.router, tags=["Image Upload UI"])


# Serve Study Break Games SPA at /games (built from StudyBreakGames/)
_GAMES_DIST = Path(__file__).resolve().parent.parent / "StudyBreakGames" / "dist"
if _GAMES_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/games", StaticFiles(directory=str(_GAMES_DIST), html=True), name="study-break-games")
    logger.info("Study Break Games SPA mounted at /games (dist: %s)", _GAMES_DIST)
else:
    logger.warning(
        "StudyBreakGames dist/ not found at %s — /games unavailable. "
        "Run: cd StudyBreakGames && npm run build",
        _GAMES_DIST,
    )


@app.get("/")
async def root():
    """Root endpoint - API health check."""
    return {
        "status": "ok",
        "message": "AgenticTA API is running",
        "version": "0.1.0",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.environ.get("API_PORT", 8000))
    host = os.environ.get("API_HOST", "0.0.0.0")
    
    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        reload=True,
        reload_dirs=[str(parent_dir)],
    )
