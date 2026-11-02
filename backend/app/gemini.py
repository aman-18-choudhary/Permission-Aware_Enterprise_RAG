import math
import time

from google import genai
from google.genai import types


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class GeminiClient:
    """Embeddings + generation via the Gemini API (free tier friendly:
    batched embeds, retry with backoff on rate limits)."""

    def __init__(self, api_key: str, chat_model: str, embed_model: str, dim: int):
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        # Bound the SDK's own retrying so a busy Gemini fails fast instead of hanging a request.
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)),
        )
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.dim = dim

    def _retry(self, fn, tries: int = 3):
        delay = 1.5
        for attempt in range(tries):
            try:
                return fn()
            except Exception:
                if attempt == tries - 1:
                    raise
                time.sleep(delay)
                delay *= 2

    def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 50):
            batch = texts[i : i + 50]
            res = self._retry(
                lambda: self.client.models.embed_content(
                    model=self.embed_model,
                    contents=batch,
                    config=types.EmbedContentConfig(task_type=task, output_dimensionality=self.dim),
                )
            )
            out.extend(_normalize(list(e.values)) for e in res.embeddings)
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]

    def generate(self, system: str, prompt: str) -> str:
        res = self._retry(
            lambda: self.client.models.generate_content(
                model=self.chat_model,
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system, temperature=0.2),
            )
        )
        return (res.text or "").strip()
