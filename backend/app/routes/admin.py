from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog, Document, Source, User
from ..security import require_admin
from ..services import Services, get_services

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/status")
def status(db: Session = Depends(get_db), svc: Services = Depends(get_services)):
    rows = db.execute(
        select(Source, User.email, func.count(Document.id))
        .join(User, User.id == Source.owner_id)
        .outerjoin(Document, Document.source_id == Source.id)
        .group_by(Source.id, User.email)
        .order_by(Source.created_at)
    ).all()
    audit = db.execute(
        select(AuditLog, User.email).join(User, User.id == AuditLog.user_id).order_by(AuditLog.created_at.desc()).limit(20)
    ).all()
    return {
        "totals": {
            "users": db.scalar(select(func.count(User.id))),
            "sources": len(rows),
            "documents": db.scalar(select(func.count(Document.id))),
            "chunks": svc.store.count(),
        },
        "sources": [
            {
                "id": s.id,
                "kind": s.kind,
                "name": s.name,
                "owner": email,
                "status": s.status,
                "last_error": s.last_error,
                "last_synced_at": s.last_synced_at,
                "documents": n,
            }
            for s, email, n in rows
        ],
        "recent_queries": [
            {"user": email, "question": a.question, "answered": a.answered, "at": a.created_at} for a, email in audit
        ],
    }


@router.get("/users")
def users(db: Session = Depends(get_db)):
    return [
        {"id": u.id, "email": u.email, "is_admin": u.is_admin, "domain": u.domain, "groups": u.groups}
        for u in db.scalars(select(User).order_by(User.email))
    ]


class GroupsIn(BaseModel):
    groups: list[str]


@router.put("/users/{user_id}/groups")
def set_groups(user_id: str, body: GroupsIn, db: Session = Depends(get_db)):
    """Group membership drives `group:` ACL principals (Drive shares with Google Groups)."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    user.groups = sorted({g.strip().lower() for g in body.groups if g.strip()})
    db.commit()
    return {"id": user.id, "groups": user.groups}
