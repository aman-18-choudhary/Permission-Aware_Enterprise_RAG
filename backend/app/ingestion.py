import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from .chunking import chunk_text
from .models import Document, Source
from .services import Services


def ingest_document(
    db: Session,
    svc: Services,
    source: Source,
    external_id: str,
    title: str,
    url: str | None,
    text: str,
    acl: list[str],
) -> str:
    """Create/update one document in Postgres + Qdrant.

    Returns: created | updated | acl_only | unchanged.
    ACL-only changes (a share was added/revoked) only patch Qdrant payloads:
    no re-chunking and no re-embedding. Narrowing happens in the vector store
    before the DB row is committed, so a crash leaves access tighter, not looser.
    """
    acl = sorted(set(acl))
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    doc = db.scalar(select(Document).where(Document.source_id == source.id, Document.external_id == external_id))

    if doc is None:
        doc = Document(source_id=source.id, external_id=external_id, title=title, url=url, content_hash="", acl=acl)
        db.add(doc)
        db.flush()
        outcome = "created"
    elif doc.content_hash != content_hash or doc.title != title:
        outcome = "updated"
    elif sorted(doc.acl or []) != acl:
        svc.store.set_acl(doc.id, acl)
        doc.acl = acl
        db.commit()
        return "acl_only"
    else:
        return "unchanged"

    chunks = chunk_text(text)
    svc.store.delete_doc(doc.id)
    if chunks:
        # Title is prepended for embedding so each chunk carries its context.
        dense = svc.embedder.embed_documents([f"{title}\n\n{c}" for c in chunks])
        svc.store.upsert_chunks(doc.id, source.id, title, url, acl, chunks, dense)
    doc.title, doc.url, doc.acl = title, url, acl
    doc.content_hash, doc.chunk_count = content_hash, len(chunks)
    db.commit()
    return outcome


def delete_document(db: Session, svc: Services, doc: Document) -> None:
    svc.store.delete_doc(doc.id)
    db.delete(doc)
    db.commit()


def prune_missing(db: Session, svc: Services, source: Source, seen_external_ids: set[str]) -> int:
    """Remove documents that vanished upstream (deleted, or access lost)."""
    removed = 0
    for doc in list(source.documents):
        if doc.external_id not in seen_external_ids:
            delete_document(db, svc, doc)
            removed += 1
    return removed


def delete_source(db: Session, svc: Services, source: Source) -> None:
    for doc in list(source.documents):
        svc.store.delete_doc(doc.id)
    db.delete(source)
    db.commit()
