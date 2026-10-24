"""App entry point. Serves the API and both dashboards from one process.

Run:  uvicorn app.main:app --reload   (from the backend/ folder)
"""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import exc as sa_exc, text
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from . import models
from .config import REPO_DIR, settings
from .database import SessionLocal, init_db
from .routers import admin, auth, catalog, content, diagnostic, hire, learn, library, manager
from . import safeguards
from .services import ai

logging.basicConfig(level=logging.INFO)

app = FastAPI(title=settings.app_name, version="0.1.0")
# The API and the dashboards share one origin, so no cross-origin access is enabled.
app.add_middleware(GZipMiddleware, minimum_size=1000)  # JSON and JS shrink 70-85%; matters when thousands load at once
app.middleware("http")(safeguards.traffic_middleware)


@app.exception_handler(sa_exc.TimeoutError)
@app.exception_handler(sa_exc.OperationalError)
async def database_busy(request, exc):
    """Database saturated or briefly unavailable: fail fast with a retryable 503 instead of hanging."""
    safeguards.metrics.counters["db_unavailable"] += 1
    return JSONResponse({"detail": "The system is busy. Please try again in a few seconds."}, status_code=503,
                        headers={"Retry-After": "5"})

for r in (auth.router, catalog.router, hire.router, learn.router, manager.router, content.router, content.files_router, admin.router,
          diagnostic.router, library.router):
    app.include_router(r)


@app.middleware("http")
async def no_stale_frontend(request, call_next):
    # The dashboards have no build step, so make browsers re-check files after each change.
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.on_event("startup")
def startup():
    import anyio.to_thread

    # Sync endpoints run in a thread pool; AI and database waits shouldn't starve other requests.
    anyio.to_thread.current_default_thread_limiter().total_tokens = 100
    init_db()
    if not settings.auto_seed:
        return
    with SessionLocal() as db:
        if not db.scalar(select(func.count(models.Employee.id))):
            from .services.sync import sync_all

            logging.info("Empty database: loading data from %s", settings.data_dir)
            try:
                sync_all(db)
                from .services.demo import load_demo_documents

                load_demo_documents(db)
            except Exception:  # keep the server up so /api/admin can fix the data
                logging.exception("Initial sync failed")


@app.get("/api/health")
def health():
    return {"ok": True, "ai": "claude" if ai.ai_enabled() else "offline", "model": settings.ai_model if ai.ai_enabled() else None}


@app.get("/api/ready")
def ready():
    """Readiness for load balancers: this worker can reach the database."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"ready": False}, status_code=503)
    return {"ready": True}


@app.get("/")
def root():
    return RedirectResponse("/login/")


frontend = Path(settings.frontend_dir)
app.mount("/shared", StaticFiles(directory=frontend / "shared"), name="shared")
app.mount("/login", StaticFiles(directory=frontend / "shared" / "login", html=True), name="login")
app.mount("/manager", StaticFiles(directory=frontend / "manager-dashboard", html=True), name="manager")
app.mount("/hire", StaticFiles(directory=frontend / "hire-dashboard", html=True), name="hire")
