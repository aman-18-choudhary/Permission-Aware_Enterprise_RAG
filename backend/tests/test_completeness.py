"""Auto-sync, restart recovery, Drive disconnect, per-document management, .docx."""
import io

from sqlalchemy import select

from app import scheduler
from app.ingestion import ingest_document
from app.models import Document, Source, User
from app.security import encrypt
from app.sync import SYNCERS


def make_user(db, email="u@acme.com", admin=False):
    u = User(email=email, is_admin=admin)
    db.add(u)
    db.commit()
    return u


def test_stuck_syncing_sources_are_reset_at_startup(db):
    u = make_user(db)
    db.add_all([Source(kind="github", name="a/b", owner_id=u.id, status="syncing"), Source(kind="github", name="c/d", owner_id=u.id, status="ok")])
    db.commit()
    assert scheduler.reset_stuck_syncs() == 1
    db.expire_all()
    by_name = {s.name: s for s in db.scalars(select(Source))}
    assert by_name["a/b"].status == "error" and "run Sync again" in by_name["a/b"].last_error
    assert by_name["c/d"].status == "ok"


def test_auto_sync_syncs_due_sources_only_and_survives_failures(db, svc, monkeypatch):
    u = make_user(db)
    db.add_all([
        Source(kind="github", name="ok/repo", owner_id=u.id, status="ok"),
        Source(kind="github", name="bad/repo", owner_id=u.id, status="ok"),
        Source(kind="github", name="busy/repo", owner_id=u.id, status="syncing"),
        Source(kind="upload", name="My uploads", owner_id=u.id, status="ok"),
    ])
    db.commit()
    seen = []

    def fake(db_, svc_, source):
        seen.append(source.name)
        if source.name == "bad/repo":
            raise RuntimeError("boom")
        return set(), []

    monkeypatch.setitem(SYNCERS, "github", fake)
    assert scheduler.sync_all(svc) == (2, False)  # a failing source is recorded, not fatal
    assert sorted(seen) == ["bad/repo", "ok/repo"]  # not the busy one, not uploads
    db.expire_all()
    assert db.scalar(select(Source).where(Source.name == "bad/repo")).status == "error"


def test_drive_disconnect_removes_index_and_token(client_factory, svc, db, monkeypatch):
    c = client_factory("dana@acme.com")
    user = db.scalar(select(User).where(User.email == "dana@acme.com"))
    user.drive_refresh_token_enc = encrypt("refresh-token")
    src = Source(kind="drive", name="Google Drive", owner_id=user.id, status="ok")
    db.add(src)
    db.commit()
    ingest_document(db, svc, src, "f1", "plan.md", None, "Drive document about falcon launch.", ["user:dana@acme.com"])
    assert svc.store.count() > 0

    revoked = []
    monkeypatch.setattr("app.routes.auth.httpx.post", lambda url, data=None, timeout=None: revoked.append(data["token"]))
    assert c.delete("/auth/drive").status_code == 204
    assert revoked == ["refresh-token"]  # revoked at Google with the decrypted token
    assert svc.store.count() == 0
    db.expire_all()
    assert db.get(User, user.id).drive_refresh_token_enc is None
    assert db.scalar(select(Source).where(Source.kind == "drive")) is None
    assert c.get("/auth/me").json()["drive_connected"] is False


def test_documents_can_be_listed_and_deleted_individually(client_factory, svc):
    alice, bob = client_factory("alice@acme.com"), client_factory("bob@acme.com")
    for name, vis in (("a.md", "private"), ("b.md", "org")):
        assert alice.post("/sources/upload", files={"file": (name, b"Some text about " + name.encode())}, data={"visibility": vis}).status_code == 200
    sid = alice.get("/sources").json()[0]["id"]
    docs = alice.get(f"/sources/{sid}/documents").json()
    assert {d["title"]: d["visibility"] for d in docs} == {"a.md": "restricted", "b.md": "everyone"}
    assert bob.get(f"/sources/{sid}/documents").status_code == 404  # not bob's source
    doc_a = next(d["id"] for d in docs if d["title"] == "a.md")
    before = svc.store.count()
    assert bob.delete(f"/sources/{sid}/documents/{doc_a}").status_code == 404
    assert alice.delete(f"/sources/{sid}/documents/{doc_a}").status_code == 204
    assert svc.store.count() < before
    assert [d["title"] for d in alice.get(f"/sources/{sid}/documents").json()] == ["b.md"]


def test_docx_upload_is_indexed_including_tables(client_factory):
    from docx import Document as Docx

    d = Docx()
    d.add_paragraph("Annual leave policy: twenty five days per year.")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Sick leave", "ten days"
    buf = io.BytesIO()
    d.save(buf)
    alice = client_factory("alice@acme.com")
    r = alice.post("/sources/upload", files={"file": ("policy.docx", buf.getvalue())})
    assert r.status_code == 200
    out = alice.post("/chat", json={"question": "sick leave days"}).json()
    assert out["citations"] and out["citations"][0]["title"] == "policy.docx"


def test_failed_reindex_keeps_the_previous_version_searchable(db, svc):
    u = make_user(db)
    src = Source(kind="github", name="a/b", owner_id=u.id)
    db.add(src)
    db.commit()
    ingest_document(db, svc, src, "f", "doc.md", None, "Original text about the falcon launch.", ["tenant:all"])
    q = svc.embedder.embed_query("falcon launch")
    assert svc.store.search(q, "falcon launch", ["tenant:all"])

    def boom(texts):
        raise RuntimeError("quota")

    svc.embedder.embed_documents = boom
    try:
        ingest_document(db, svc, src, "f", "doc.md", None, "Changed text about the falcon launch date.", ["tenant:all"])
        raise AssertionError("expected the failure to propagate")
    except RuntimeError:
        db.rollback()
    hits = svc.store.search(q, "falcon launch", ["tenant:all"])
    assert hits and "Original text" in hits[0].text  # old chunks survived the failed update


def test_quota_exhaustion_gives_a_clean_503_not_a_crash(client_factory, svc):
    from app.gemini import QuotaExhausted

    alice = client_factory("alice@acme.com")

    def out_of_quota(text):
        raise QuotaExhausted("daily")

    svc.embedder.embed_query = out_of_quota
    for path in ("/chat", "/chat/stream"):
        r = alice.post(path, json={"question": "anything"})
        assert r.status_code == 503 and "quota" in r.json()["detail"].lower()


def test_auto_sync_stops_the_pass_when_quota_runs_out(db, svc, monkeypatch):
    u = make_user(db)
    db.add_all([Source(kind="github", name="one/repo", owner_id=u.id, status="ok"), Source(kind="github", name="two/repo", owner_id=u.id, status="ok")])
    db.commit()
    calls = []

    def quota(db_, svc_, source):
        calls.append(source.name)
        from app.gemini import QuotaExhausted

        raise QuotaExhausted("Gemini daily quota exhausted")

    monkeypatch.setitem(SYNCERS, "github", quota)
    done, quota_hit = scheduler.sync_all(svc)
    assert quota_hit is True and len(calls) == 1  # did not hammer the second source
