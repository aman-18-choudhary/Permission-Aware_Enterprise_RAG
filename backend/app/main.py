import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .db import Base, engine
from .net import prefer_ipv4
from .routes import admin, auth, chat, sources

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
    Base.metadata.create_all(engine)  # TODO: Alembic migrations before real production use
    if s.reranker_model and s.gemini_api_key:
        threading.Thread(target=_warm_up, daemon=True).start()
    yield


app = FastAPI(title="Second Brain", lifespan=lifespan)
for r in (auth.router, sources.router, chat.router, admin.router):
    app.include_router(r)


@app.get("/health")
def health():
    return {"ok": True}
