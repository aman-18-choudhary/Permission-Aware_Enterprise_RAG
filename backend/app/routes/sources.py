import re
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..acl import TENANT_ALL, user_principal
from ..config import get_settings
from ..connectors.parsing import extract_text
from ..db import get_db
from ..ingestion import delete_source, ingest_document
from ..models import Document, Source, User
from ..security import current_user
from ..services import Services, get_services
from ..sync import run_sync_background

router = APIRouter(prefix="/sources", tags=["sources"])

Visibility = Literal["private", "org"]


def _acl_for(user: User, visibility: str) -> list[str]:
    return [TENANT_ALL] if visibility == "org" else [user_principal(user.email)]


def _owned(db: Session, source_id: str, user: User) -> Source:
    src = db.get(Source, source_id)
    if not src or (src.owner_id != user.id and not user.is_admin):
        raise HTTPException(404, "Source not found")  # 404, not 403: don't reveal existence
    return src


def _view(src: Source, doc_count: int) -> dict:
    return {
        "id": src.id,
        "kind": src.kind,
        "name": src.name,
        "status": src.status,
        "last_error": src.last_error,
        "last_synced_at": src.last_synced_at,
        "documents": doc_count,
    }


@router.get("")
def list_sources(db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(Source, func.count(Document.id)).outerjoin(Document).group_by(Source.id)
    if not user.is_admin:
        q = q.where(Source.owner_id == user.id)
    return [_view(s, n) for s, n in db.execute(q.order_by(Source.created_at)).all()]


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    visibility: Visibility = Form("private"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    svc: Services = Depends(get_services),
):
    s = get_settings()
    data = await file.read(s.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File larger than {s.max_upload_mb} MB")
    name = re.sub(r"[^\w.\- ]", "_", file.filename or "upload")
    try:
        text = extract_text(name, data)
    except ValueError as e:
        raise HTTPException(415, str(e))
    src = db.scalar(select(Source).where(Source.owner_id == user.id, Source.kind == "upload"))
    if not src:
        src = Source(kind="upload", name="My uploads", owner_id=user.id, status="ok")
        db.add(src)
        db.commit()
    outcome = ingest_document(db, svc, src, f"upload:{name}", name, None, text, _acl_for(user, visibility))
    return {"file": name, "result": outcome}


class GithubIn(BaseModel):
    repo: str  # owner/name
    branch: str | None = None
    visibility: Visibility = "private"


@router.post("/github")
def add_github(
    body: GithubIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", body.repo):
        raise HTTPException(422, "repo must look like owner/name")
    src = Source(
        kind="github",
        name=body.repo,
        owner_id=user.id,
        config={"repo": body.repo, "branch": body.branch, "acl": _acl_for(user, body.visibility)},
    )
    db.add(src)
    db.commit()
    background.add_task(run_sync_background, src.id)
    return _view(src, 0)


@router.post("/{source_id}/sync", status_code=202)
def sync(source_id: str, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(current_user)):
    src = _owned(db, source_id, user)
    if src.kind == "upload":
        raise HTTPException(400, "Uploads are indexed immediately")
    if src.status == "syncing":
        raise HTTPException(409, "Sync already running")
    src.status = "syncing"
    db.commit()
    background.add_task(run_sync_background, src.id)
    return {"status": "syncing"}


@router.delete("/{source_id}", status_code=204)
def remove(
    source_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    svc: Services = Depends(get_services),
):
    delete_source(db, svc, _owned(db, source_id, user))
