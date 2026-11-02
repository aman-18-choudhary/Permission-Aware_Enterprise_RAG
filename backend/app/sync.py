import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .acl import drive_acl
from .connectors import drive as drive_conn
from .connectors import github as github_conn
from .db import SessionLocal
from .ingestion import ingest_document, prune_missing
from .models import Source, User
from .security import decrypt
from .services import Services, get_services

log = logging.getLogger(__name__)


def _sync_github(db: Session, svc: Services, source: Source) -> set[str]:
    seen: set[str] = set()
    cfg = source.config
    for path, url, text in github_conn.fetch_repo(cfg["repo"], cfg.get("branch")):
        ext_id = f"{cfg['repo']}:{path}"
        ingest_document(db, svc, source, ext_id, f"{cfg['repo']}/{path}", url, text, cfg["acl"])
        seen.add(ext_id)
    return seen


def _sync_drive(db: Session, svc: Services, source: Source) -> set[str]:
    owner = db.get(User, source.owner_id)
    if not owner or not owner.drive_refresh_token_enc:
        raise RuntimeError("Google Drive is not connected for this user")
    seen: set[str] = set()
    for f, text in drive_conn.list_files(decrypt(owner.drive_refresh_token_enc)):
        acl = drive_acl(f.get("permissions"), f.get("owners"), owner.email)
        ingest_document(db, svc, source, f["id"], f["name"], f.get("webViewLink"), text, acl)
        seen.add(f["id"])
    return seen


SYNCERS = {"github": _sync_github, "drive": _sync_drive}


def sync_source(db: Session, svc: Services, source: Source) -> None:
    """Sync one source. On success, documents that disappeared upstream
    (deleted, or no longer visible to the syncing account) are pruned."""
    source.status, source.last_error = "syncing", None
    db.commit()
    try:
        seen = SYNCERS[source.kind](db, svc, source)
        prune_missing(db, svc, source, seen)
        source.status = "ok"
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
