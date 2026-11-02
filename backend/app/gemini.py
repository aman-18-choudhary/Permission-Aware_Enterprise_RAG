import math
import re
import time
from collections import deque

from google import genai
from google.genai import types


class QuotaExhausted(RuntimeError):
    """Daily Gemini quota is gone: waiting a minute won't help."""


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class RateWindow:
    """Sliding-window limiter. The free tier counts every embedded *text* as a
    request (100/min), so we count texts, not API calls."""

    def __init__(self, limit: int, window: float = 60.0, clock=time.monotonic, sleep=time.sleep):
        self.limit, self.window, self.clock, self.sleep = limit, window, clock, sleep
        self.stamps: deque[float] = deque()

    def acquire(self, n: int) -> None:
        n = min(n, self.limit)
        while True:
            now = self.clock()
            while self.stamps and self.stamps[0] <= now - self.window:
                self.stamps.popleft()
            if len(self.stamps) + n <= self.limit:
                self.stamps.extend([now] * n)
                return
            self.sleep(max(self.stamps[0] + self.window - now, 0.05))


class GeminiClient:
    """Embeddings + generation via the Gemini API, tuned for the free tier:
    client-side throttling, batching, and honouring 429 retry hints."""

    def __init__(self, api_key: str, chat_model: str, embed_model: str, dim: int, embed_per_minute: int = 90):
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
        self.limiter = RateWindow(embed_per_minute)

    def _retry(self, fn, tries: int = 4):
        delay = 1.5
        for attempt in range(tries):
            try:
                return fn()
            except Exception as e:
                msg = str(e)
                if getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in msg:
                    if "PerDay" in msg:
                        raise QuotaExhausted("Gemini daily quota exhausted; retry tomorrow or use a paid key") from e
                    m = re.search(r"retry in ([\d.]+)s", msg)
                    wait = min(float(m.group(1)) + 1 if m else 20.0, 65.0)
                elif attempt < tries - 1:
                    wait, delay = delay, delay * 2
                else:
                    raise
                if attempt == tries - 1:
                    raise
                time.sleep(wait)

    def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        out: list[list[float]] = []
        step = max(1, min(50, self.limiter.limit))
        for i in range(0, len(texts), step):
            batch = texts[i : i + step]
            self.limiter.acquire(len(batch))
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

    def generate_stream(self, system: str, prompt: str):
        """Yield the answer in pieces as Gemini produces it. Not retried: once
        text has reached the user we can't restart cleanly."""
        for chunk in self.client.models.generate_content_stream(
            model=self.chat_model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0.2),
        ):
            if chunk.text:
                yield chunk.text

    def generate(self, system: str, prompt: str) -> str:
        res = self._retry(
            lambda: self.client.models.generate_content(
                model=self.chat_model,
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system, temperature=0.2),
            )
        )
        return (res.text or "").strip()
