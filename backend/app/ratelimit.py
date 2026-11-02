import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException

from .config import get_settings
from .models import User
from .security import current_user


class SlidingWindowLimiter:
    """Per-key sliding-window limiter (in-process; use Redis if you run several replicas)."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window: float = 60.0) -> float | None:
        """Record a hit. Returns None if allowed, else seconds until the next slot."""
        now = self.clock()
        q = self.hits[key]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return q[0] + window - now
        q.append(now)
        return None


chat_limiter = SlidingWindowLimiter()


def limit_chat(user: User = Depends(current_user)) -> User:
    """Protects the shared Gemini quota from one user (or a runaway script)."""
    retry = chat_limiter.check(user.id, get_settings().chat_per_minute)
    if retry is not None:
        raise HTTPException(429, "Too many questions, slow down.", headers={"Retry-After": str(int(retry) + 1)})
    return user
