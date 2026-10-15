import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.routers.health import router as health_router
from app.routers.auth import router as auth_router
from app.routers.ideas import router as ideas_router
from app.routers.admin import router as admin_router
from app.routers.admin_export import router as admin_export_router
from app.routers.files import idea_files_router, files_router
from app.routers.intake import router as intake_router
from app.routers.tracking import router as tracking_router
from app.routers.inventor import router as inventor_router
from app.routers.admin_jury import router as admin_jury_router
from app.routers.jury import router as jury_router
from app.routers.admin_decisions import router as admin_decisions_router
from app.routers.public_inquiries import router as public_inquiries_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed by Alembic only. Run `alembic upgrade head` before starting.
    # create_tables() / Base.metadata.create_all() must NOT run here — it cannot
    # create PostgreSQL enum types (intakestatus, pathwaystage, etc.) that Alembic
    # migrations define. Calling it would raise UndefinedObject errors on startup.
    from app.database import test_connection
    logger.info("Starting NMF-IFIA Innovation Hub API...")
    logger.info(f"Allowed CORS origins: {settings.allowed_origins_list}")
    test_connection()
    logger.info("Startup complete. Schema managed by Alembic — run: alembic upgrade head")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response


@app.middleware("http")
async def unhandled_exception_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        logger.exception("Unhandled API error: %s %s", request.method, request.url.path)
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
        origin = request.headers.get("origin")
        if origin in settings.allowed_origins_list:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers.add_vary_header("Origin")
        return response

# Root health check (no prefix)
app.include_router(health_router)

# Versioned API
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router,   prefix="/api/v1")
app.include_router(ideas_router,  prefix="/api/v1")
app.include_router(admin_export_router, prefix="/api/v1")
app.include_router(admin_router,       prefix="/api/v1")
app.include_router(idea_files_router,  prefix="/api/v1")
app.include_router(files_router,       prefix="/api/v1")
app.include_router(intake_router,      prefix="/api/v1")
app.include_router(tracking_router,    prefix="/api/v1")
app.include_router(inventor_router,    prefix="/api/v1")
app.include_router(admin_jury_router,      prefix="/api/v1")
app.include_router(jury_router,            prefix="/api/v1")
app.include_router(admin_decisions_router, prefix="/api/v1")
app.include_router(public_inquiries_router, prefix="/api/v1")
