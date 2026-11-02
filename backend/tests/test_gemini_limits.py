import pytest

from app import gemini
from app.connectors.github import wanted
from app.gemini import GeminiClient, QuotaExhausted, RateWindow


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def test_rate_window_blocks_until_window_frees():
    c = Clock()
    w = RateWindow(limit=5, window=60, clock=c.now, sleep=c.sleep)
    w.acquire(3)
    w.acquire(2)  # exactly at the limit: no wait
    assert c.sleeps == []
    w.acquire(1)  # must wait for the first stamps (t=0) to age out
    assert c.t >= 60 and sum(c.sleeps) >= 60


def test_rate_window_counts_texts_not_calls():
    c = Clock()
    w = RateWindow(limit=100, window=60, clock=c.now, sleep=c.sleep)
    for _ in range(2):
        w.acquire(50)
    w.acquire(10)  # 110 texts in one minute would break the free tier
    assert c.t >= 60


class FakeAPIError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def _client():
    g = GeminiClient.__new__(GeminiClient)  # skip the real network client
    return g


def test_429_waits_for_the_hinted_delay_then_succeeds(monkeypatch):
    slept = []
    monkeypatch.setattr(gemini.time, "sleep", slept.append)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise FakeAPIError(429, "RESOURCE_EXHAUSTED ... Please retry in 4.3s.")
        return "ok"

    assert _client()._retry(fn) == "ok"
    assert slept == [pytest.approx(5.3)]


def test_daily_quota_is_not_retried(monkeypatch):
    monkeypatch.setattr(gemini.time, "sleep", lambda s: pytest.fail("should not sleep"))

    def fn():
        raise FakeAPIError(429, "RESOURCE_EXHAUSTED EmbedContentRequestsPerDay exceeded")

    with pytest.raises(QuotaExhausted):
        _client()._retry(fn)


def test_github_file_filter_skips_noise():
    assert wanted("README.md", 100)
    assert wanted("backend/app/main.py", 5_000)
    assert not wanted("frontend/package-lock.json", 1_000)
    assert not wanted("frontend/node_modules/x/index.js", 1_000)
    assert not wanted("assets/logo.png", 1_000)
    assert not wanted("big.md", 900_000)
