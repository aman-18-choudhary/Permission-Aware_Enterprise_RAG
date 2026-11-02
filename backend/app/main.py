from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .db import Base, engine
from .net import prefer_ipv4
from .routes import admin, auth, chat, sources

if get_settings().force_ipv4:
    prefer_ipv4()


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings().validate_for_runtime()
    Base.metadata.create_all(engine)  # TODO: Alembic migrations before real production use
    yield


app = FastAPI(title="Second Brain", lifespan=lifespan)
for r in (auth.router, sources.router, chat.router, admin.router):
    app.include_router(r)


@app.get("/health")
def health():
    return {"ok": True}
