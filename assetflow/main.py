import logging
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from assetflow.api.routes import auth, health, projects, reviews
from assetflow.core.config import Settings, get_settings
from assetflow.core.errors import AppError, app_error_handler, unexpected_error_handler
from assetflow.core.logging import configure_safe_access_logging
from assetflow.db.base import Base
from assetflow.db.seed import seed_demo
from assetflow.db.session import SessionLocal, engine
from assetflow.services.previews import PreviewLifecycleService
from assetflow.web.routes import router as web_router

logger = logging.getLogger("assetflow")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_safe_access_logging()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        if settings.environment == "development":
            Base.metadata.create_all(bind=engine)
            with SessionLocal() as db:
                seed_demo(db)
                PreviewLifecycleService(db, settings.upload_dir).cleanup_expired()
        yield

    docs_enabled = settings.environment != "production"
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_exception_handler(AppError, app_error_handler)
    if not settings.debug:
        app.add_exception_handler(Exception, unexpected_error_handler)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        supplied_request_id = request.headers.get("x-request-id", "")
        request_id = supplied_request_id[:128] if supplied_request_id.isascii() else ""
        request_id = request_id or str(uuid4())
        start = time.perf_counter()
        if request.url.path.startswith("/static/uploads/"):
            from fastapi.responses import Response

            return Response(status_code=404)
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-response-time-ms"] = f"{(time.perf_counter() - start) * 1000:.2f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "font-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "public, max-age=3600")
        elif request.url.path != "/health":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.middleware("http")
    async def same_origin_cookie_writes(request: Request, call_next):
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.cookies.get("assetflow_session")
        ):
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")
            source = origin or referer
            source_host = urlparse(source).netloc if source else ""
            request_host = request.headers.get("host", "")
            missing_production_source = settings.environment == "production" and not source
            if missing_production_source or (source and source_host != request_host):
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    {"error": {"code": "invalid_origin", "message": "Cross-site write blocked"}},
                    status_code=403,
                )
        return await call_next(request)

    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.include_router(reviews.router, prefix="/api")
    app.include_router(web_router)
    return app


app = create_app()
