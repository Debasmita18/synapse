import logging
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import get_settings
from app.core.exceptions import SynapseError, synapse_error_handler
from app.database import Base, engine
from app.routers import auth, payments, users

# ── Logging ───────────────────────────────────────────────────────────────────
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
    logger_factory=structlog.PrintLoggerFactory(),
)
logger = structlog.get_logger()

settings = get_settings()
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        # Import all models so Base sees their metadata before create_all
        import app.models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
    logger.info("SYNAPSE started", debug=settings.debug, db=settings.database_url)
    yield
    await engine.dispose()
    logger.info("SYNAPSE shutdown")


# ── App factory ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="SYNAPSE API",
    description="The neural codex for AI engineers — backend API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Custom exception handler
app.add_exception_handler(SynapseError, synapse_error_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(payments.router)

# ── Static files & templates ──────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ── Frontend routes ───────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def serve_index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "razorpay_key": settings.razorpay_key_id,
            "google_client_id": settings.google_client_id,
        },
    )


# ── Health check ─────────────────────────────────────────────────────────────
@app.get("/api/health", tags=["system"])
async def health():
    return {"status": "ok", "app": settings.app_name}


# ── Global 500 handler ────────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "An unexpected error occurred"},
    )
