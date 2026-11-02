import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .acl import drive_acl
from .connectors import drive as drive_conn
from .connectors import github as github_conn
from .db import SessionLocal
from .gemini import QuotaExhausted
from .ingestion import ingest_document, prune_missing
from .models import Source, User
from .security import decrypt
from .services import Services, get_services

log = logging.getLogger(__name__)


def _safe_ingest(db: Session, svc: Services, source: Source, ext_id, title, url, text, acl, seen: set, failures: list):
    """Ingest one document; a bad file is skipped (and reported), not fatal.
    A failed document still counts as "seen", so its previous version is kept
    instead of being pruned as if it had been deleted upstream."""
    seen.add(ext_id)
    try:
        ingest_document(db, svc, source, ext_id, title, url, text, acl)
    except QuotaExhausted:
        raise  # no point continuing: every following file would fail the same way
    except Exception as e:
        db.rollback()
        log.warning("skipping %s: %s", title, e)
        failures.append(f"{title}: {str(e)[:120]}")


def _sync_github(db: Session, svc: Services, source: Source) -> tuple[set[str], list[str]]:
    seen: set[str] = set()
    failures: list[str] = []
    cfg = source.config
    for path, url, text in github_conn.fetch_repo(cfg["repo"], cfg.get("branch")):
        _safe_ingest(db, svc, source, f"{cfg['repo']}:{path}", f"{cfg['repo']}/{path}", url, text, cfg["acl"], seen, failures)
    return seen, failures


def _sync_drive(db: Session, svc: Services, source: Source) -> tuple[set[str], list[str]]:
    owner = db.get(User, source.owner_id)
    if not owner or not owner.drive_refresh_token_enc:
        raise RuntimeError("Google Drive is not connected for this user")
    seen: set[str] = set()
    failures: list[str] = []
    for f, text in drive_conn.list_files(decrypt(owner.drive_refresh_token_enc)):
        acl = drive_acl(f.get("permissions"), f.get("owners"), owner.email)
        _safe_ingest(db, svc, source, f["id"], f["name"], f.get("webViewLink"), text, acl, seen, failures)
    return seen, failures


SYNCERS = {"github": _sync_github, "drive": _sync_drive}


def sync_source(db: Session, svc: Services, source: Source) -> None:
    """Sync one source. On success, documents that disappeared upstream
    (deleted, or no longer visible to the syncing account) are pruned.
    Re-running is cheap and resumable: unchanged documents are skipped by hash."""
    source.status, source.last_error = "syncing", None
    db.commit()
    try:
        seen, failures = SYNCERS[source.kind](db, svc, source)
        prune_missing(db, svc, source, seen)
        source.status = "ok"
        source.last_error = f"{len(failures)} file(s) skipped, e.g. {failures[0]}" if failures else None
        source.last_synced_at = datetime.now(timezone.utc)
    except Exception as e:  # surfaced in the admin view
        log.exception("sync failed for source %s", source.id)
        db.rollback()
        source = db.get(Source, source.id)
        source.status, source.last_error = "error", str(e)[:500]
    db.commit()


def run_sync_background(source_id: str) -> None:
    db = SessionLocal()
    try:
        source = db.get(Source, source_id)
        if source:
            sync_source(db, get_services(), source)
    finally:
        db.close()
