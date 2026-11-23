"""FastAPI application factory.

Run:  python main.py serve        (or: uvicorn api.main:create_app --factory)

Deployment model: one origin. The API serves the built React app (frontend/dist), so
no CORS is needed. For intranet integration, either
  * the intranet calls /api/v1/* directly (add its origin to api.cors_origins), or
  * the intranet embeds the UI in an iframe (add its origin to api.frame_ancestors).
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine

from api.routers import auth, automation, daily, database as database_router, employees as employees_router, mail as mail_router, overview as overview_router, reports as reports_router, sales as sales_router, settings as settings_router
from api.sessions import resolve_secret
from core.config import Settings, get_settings
from core.exceptions import AppError, AuthorizationError
from core.logging_setup import configure_logging
from core.paths import PROJECT_ROOT
from database.connection import check_database, create_db_engine

log = logging.getLogger("api")

API_PREFIX = "/api/v1"
CSRF_HEADER = "X-APIS-Request"          # value must be "1"; forces a CORS preflight cross-origin
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def create_app(settings: Settings | None = None, engine: Engine | None = None, frontend_dist: Path | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    engine = engine or create_db_engine(settings)

    app = FastAPI(
        title=settings.app.name,
        version="1.0.0",
        docs_url="/api/docs" if settings.environment != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.environment != "production" else None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_secret = resolve_secret(settings)

    if settings.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.api.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", CSRF_HEADER],
        )

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and request.method in _UNSAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse({"detail": "Missing request header"}, status_code=status.HTTP_403_FORBIDDEN)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        # A route may set a stricter policy (e.g. sandboxed HTML report downloads); keep it.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https://tile.openstreetmap.org https://outletimages.s3.ap-southeast-1.amazonaws.com "
            "https://bizompictures.s3.ap-southeast-1.amazonaws.com https://omspics.s3.ap-southeast-1.amazonaws.com https://s3.ap-southeast-1.amazonaws.com; font-src 'self'; style-src 'self' 'unsafe-inline'; "
            f"frame-ancestors {' '.join(settings.api.frame_ancestors)}",
        )
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"   # HR data must not be cached
        return response

    @app.exception_handler(AuthorizationError)
    async def _forbidden(request: Request, exc: AuthorizationError):
        log.warning("authorization denied", extra={"path": request.url.path})
        return JSONResponse({"detail": "Not authorised"}, status_code=status.HTTP_403_FORBIDDEN)

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        log.error("application error", extra={"path": request.url.path, "error": type(exc).__name__})
        return JSONResponse({"detail": "Request could not be completed"}, status_code=status.HTTP_400_BAD_REQUEST)

    @app.get("/api/health", tags=["meta"])
    def liveness() -> dict:
        """Unauthenticated liveness/readiness for monitoring. No internal detail."""
        db = check_database(engine, settings)
        ready = db.reachable and db.schema_revision is not None
        return {"status": "ok" if ready else "not_ready"}

    for router in (auth.router, overview_router.router, daily.router, mail_router.router, automation.router, database_router.router, reports_router.router, employees_router.router, settings_router.router, sales_router.router):
        app.include_router(router, prefix=API_PREFIX)
    from api.routers import holidays as holidays_router          # HR's yearly holiday list (PDF), both modules
    app.include_router(holidays_router.router, prefix=API_PREFIX)
    from api.routers import feedback as feedback_router          # signed 'Was this right?' links from the emails (outside /api)
    app.include_router(feedback_router.router)

    dist = frontend_dist if frontend_dist is not None else FRONTEND_DIST
    if settings.api.serve_frontend and (dist / "index.html").is_file():
        _mount_frontend(app, dist)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    index = dist / "index.html"
    root = dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        # client-side routing. "no-cache" = the browser must check for a newer index.html every time (a quick 304 when
        # unchanged), so screens update right after a new build; the hashed /assets files can stay cached.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
