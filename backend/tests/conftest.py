import os

# Must be set before the app is imported.
os.environ.update(
    DATABASE_URL="sqlite://",
    QDRANT_URL=":memory:",
    AUTH_DEV_MODE="true",
    SECRET_KEY="test-secret-key-at-least-32-characters-long",
    ADMIN_EMAILS="admin@acme.com",
    EMBED_DIM="64",
)

import hashlib
import math
import re

import pytest
from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, engine
from app.main import app
from app.services import Services, get_services
from app.vectorstore import VectorStore

DIM = 64


class FakeEmbedder:
    """Deterministic bag-of-words embedding. Counts calls so tests can assert
    that ACL-only changes don't trigger re-embedding."""

    def __init__(self):
        self.doc_calls = 0

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * DIM
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts):
        self.doc_calls += 1
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


class FakeLLM:
    def __init__(self):
        self.prompts: list[str] = []  # answer prompts only
        self.rewrites: list[str] = []

    def generate_stream(self, system, prompt):
        self.prompts.append(prompt)
        yield from ("Here is ", "the answer ", "[1].")

    def generate(self, system, prompt):
        if system.startswith("Rewrite the user's latest message"):
            self.rewrites.append(prompt)
            return "falcon roadmap launch month"
        self.prompts.append(prompt)
        return "Here is the answer [1]."


@pytest.fixture
def svc():
    store = VectorStore(":memory:", "test_chunks", DIM)
    store.ensure_collection()
    return Services(embedder=FakeEmbedder(), llm=FakeLLM(), store=store)


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def client_factory(svc):
    app.dependency_overrides[get_services] = lambda: svc

    def make(email: str) -> TestClient:
        c = TestClient(app)
        r = c.post("/auth/dev-login", json={"email": email})
        assert r.status_code == 200, r.text
        return c

    yield make
    app.dependency_overrides.clear()
