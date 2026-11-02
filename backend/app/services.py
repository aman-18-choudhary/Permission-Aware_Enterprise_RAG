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
    def generate_stream(self, system: str, prompt: str): ...


class Reranker(Protocol):
    def rerank(self, query: str, hits: list, top_k: int) -> list: ...


@dataclass
class Services:
    embedder: Embedder
    llm: LLM
    store: VectorStore
    reranker: Reranker | None = None
    rerank_candidates: int = 20


@lru_cache
def get_services() -> Services:
    from .gemini import GeminiClient

    s = get_settings()
    gem = GeminiClient(s.gemini_api_key, s.gemini_chat_model, s.gemini_embed_model, s.embed_dim, s.embed_per_minute)
    store = VectorStore(s.qdrant_url, s.qdrant_collection, s.embed_dim)
    store.ensure_collection()
    reranker = None
    if s.reranker_model:
        from .reranker import CrossEncoderReranker

        reranker = CrossEncoderReranker(s.reranker_model)
    return Services(embedder=gem, llm=gem, store=store, reranker=reranker, rerank_candidates=s.rerank_candidates)
