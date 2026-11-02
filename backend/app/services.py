from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from .config import get_settings
from .vectorstore import VectorStore


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class LLM(Protocol):
    def generate(self, system: str, prompt: str) -> str: ...


@dataclass
class Services:
    embedder: Embedder
    llm: LLM
    store: VectorStore


@lru_cache
def get_services() -> Services:
    from .gemini import GeminiClient

    s = get_settings()
    gem = GeminiClient(s.gemini_api_key, s.gemini_chat_model, s.gemini_embed_model, s.embed_dim)
    store = VectorStore(s.qdrant_url, s.qdrant_collection, s.embed_dim)
    store.ensure_collection()
    return Services(embedder=gem, llm=gem, store=store)
