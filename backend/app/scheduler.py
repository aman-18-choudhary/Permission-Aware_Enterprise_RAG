"""Background re-sync, so shares and revocations in Drive/GitHub reach the index
without anyone pressing Sync. Unchanged files are skipped by hash, so a pass is cheap."""
import logging
import threading
import time

from sqlalchemy import select, update

from .db import SessionLocal
from .models import Source
from .services import get_services
from .sync import sync_source

log = logging.getLogger(__name__)
INTERRUPTED = "Interrupted by a restart; run Sync again."
QUOTA_PAUSE_SECONDS = 6 * 3600  # after a daily-quota failure, leave the quota to chat questions


def reset_stuck_syncs(session_factory=SessionLocal) -> int:
    """A sync that was running when the process died would stay "syncing" forever
    (and block manual syncs with 409). Called once at startup."""
    with session_factory() as db:
        res = db.execute(update(Source).where(Source.status == "syncing").values(status="error", last_error=INTERRUPTED))
        db.commit()
        return res.rowcount or 0


def sync_all(svc, session_factory=SessionLocal) -> tuple[int, bool]:
    """Returns (sources synced, whether the daily Gemini quota ran out)."""
    with session_factory() as db:
        ids = list(db.scalars(select(Source.id).where(Source.kind.in_(("github", "drive")), Source.status != "syncing")))
    done = 0
    for source_id in ids:
        with session_factory() as db:
            source = db.get(Source, source_id)
            if source is None or source.status == "syncing":
                continue
            try:
                sync_source(db, svc, source)
                done += 1
            except Exception:
                log.exception("auto-sync crashed for source %s", source_id)
                continue
            if source.status == "error" and "quota" in (source.last_error or "").lower():
                return done, True  # every other source would fail the same way
    return done, False


class AutoSync:
    def __init__(self, interval_seconds: float, svc_factory=get_services):
        self.interval, self.svc_factory = interval_seconds, svc_factory
        self.pause_until = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="auto-sync", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):  # first pass after one interval, not at boot
            if time.monotonic() < self.pause_until:
                continue
            try:
                n, quota_hit = sync_all(self.svc_factory())
                if quota_hit:
                    self.pause_until = time.monotonic() + QUOTA_PAUSE_SECONDS
                    log.warning("Gemini daily quota reached; auto-sync paused for %dh", QUOTA_PAUSE_SECONDS // 3600)
                log.info("auto-sync pass finished (%d source(s))", n)
            except Exception:
                log.exception("auto-sync pass failed")
