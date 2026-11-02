import logging
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import get_settings
from .db import engine
from .migrate import run_migrations
from .gemini import QuotaExhausted
from .net import prefer_ipv4
from .routes import admin, auth, chat, sources
from .scheduler import AutoSync, reset_stuck_syncs
from .services import Services, get_services

logging.basicConfig(level=get_settings().log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
if get_settings().force_ipv4:
    prefer_ipv4()


log = logging.getLogger(__name__)


def _warm_up() -> None:
    """Connect to Qdrant and load the reranker in the background so the first question isn't slow."""
    try:
        from .services import get_services

        svc = get_services()
        if svc.reranker:
            svc.reranker.warm()
    except Exception:
        log.warning("warm-up failed (will retry lazily on first request)", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    s.validate_for_runtime()
    run_migrations()
    reset_stuck_syncs()
    if s.reranker_model and s.gemini_api_key:
        threading.Thread(target=_warm_up, daemon=True).start()
    auto = None
    if s.sync_interval_minutes > 0 and s.gemini_api_key:
        auto = AutoSync(s.sync_interval_minutes * 60)
        auto.start()
    yield
    if auto:
        auto.stop()


app = FastAPI(title="Second Brain", lifespan=lifespan)
for r in (auth.router, sources.router, chat.router, admin.router):
    app.include_router(r)


@app.exception_handler(QuotaExhausted)
async def quota_exhausted(request: Request, exc: QuotaExhausted):
    return JSONResponse({"detail": "The AI quota for today is used up. Please try again later."}, status_code=503)


@app.get("/health")
def health():
    """Liveness: the process is up."""
    return {"ok": True}


@app.get("/health/ready")
def ready(svc: Services = Depends(get_services)):
    """Readiness: database and vector store both answer."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        svc.store.count()
    except Exception:
        log.exception("readiness check failed")
        raise HTTPException(503, "dependency unavailable")
    return {"ok": True}
