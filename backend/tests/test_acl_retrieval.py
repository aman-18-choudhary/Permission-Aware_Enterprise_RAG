"""Security tests: a user must never receive content they may not access."""
from sqlalchemy import select

from app.acl import TENANT_ALL, drive_acl, principals_for, user_principal
from app.ingestion import ingest_document
from app.models import Source, User
from app.rag import NO_ACCESS
from app.sync import SYNCERS, sync_source


def upload(c, name, text, visibility="private"):
    r = c.post("/sources/upload", files={"file": (name, text.encode())}, data={"visibility": visibility})
    assert r.status_code == 200, r.text
    return r.json()


def ask(c, q):
    r = c.post("/chat", json={"question": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_private_upload_is_invisible_to_other_users(client_factory, svc):
    alice, bob = client_factory("alice@acme.com"), client_factory("bob@acme.com")
    upload(alice, "salary.md", "The CFO salary band is confidential and listed here: tier nine.")

    out = ask(bob, "What is the CFO salary band?")
    assert out["answer"] == NO_ACCESS and out["citations"] == []
    assert svc.llm.prompts == []  # restricted text never reached the LLM

    out = ask(alice, "What is the CFO salary band?")
    assert out["citations"] and out["citations"][0]["title"] == "salary.md"


def test_org_visibility_is_shared(client_factory):
    alice, bob = client_factory("alice@acme.com"), client_factory("bob@acme.com")
    upload(alice, "handbook.md", "Leave policy: employees get twenty five days of annual leave.", "org")
    assert ask(bob, "annual leave policy")["citations"]


def test_hybrid_search_finds_exact_identifier(client_factory):
    alice = client_factory("alice@acme.com")
    upload(alice, "a.md", "General notes about onboarding and laptops for new joiners.")
    upload(alice, "b.md", "Incident JIRA-4521 was caused by an expired certificate on the gateway.")
    out = ask(alice, "JIRA-4521")
    assert out["citations"][0]["title"] == "b.md"


def test_acl_only_change_does_not_reembed_and_takes_effect(client_factory, svc, db):
    alice, bob = client_factory("alice@acme.com"), client_factory("bob@acme.com")
    upload(alice, "plan.md", "Roadmap codename falcon launches in March.")
    src = db.scalar(select(Source))
    calls = svc.embedder.doc_calls

    # share with bob
    res = ingest_document(db, svc, src, "upload:plan.md", "plan.md", None,
                          "Roadmap codename falcon launches in March.", [user_principal("alice@acme.com"), user_principal("bob@acme.com")])
    assert res == "acl_only" and svc.embedder.doc_calls == calls
    assert ask(bob, "codename falcon roadmap")["citations"]

    # revoke
    ingest_document(db, svc, src, "upload:plan.md", "plan.md", None,
                    "Roadmap codename falcon launches in March.", [user_principal("alice@acme.com")])
    assert ask(bob, "codename falcon roadmap")["citations"] == []


def test_group_principal_via_admin_assigned_membership(client_factory, svc, db):
    admin, carol = client_factory("admin@acme.com"), client_factory("carol@acme.com")
    src = Source(kind="github", name="x/y", owner_id=db.scalar(select(User.id).where(User.email == "admin@acme.com")))
    db.add(src)
    db.commit()
    ingest_document(db, svc, src, "f1", "finance.md", None, "Quarterly budget forecast for finance team.", ["group:finance@acme.com"])

    assert ask(carol, "quarterly budget forecast")["citations"] == []
    carol_id = next(u["id"] for u in admin.get("/admin/users").json() if u["email"] == "carol@acme.com")
    assert admin.put(f"/admin/users/{carol_id}/groups", json={"groups": ["Finance@acme.com"]}).status_code == 200
    assert ask(carol, "quarterly budget forecast")["citations"]


def test_deleted_upstream_documents_are_pruned(client_factory, svc, db, monkeypatch):
    admin = client_factory("admin@acme.com")
    uid = db.scalar(select(User.id).where(User.email == "admin@acme.com"))
    src = Source(kind="github", name="x/y", owner_id=uid)
    db.add(src)
    db.commit()

    def fake_sync(db_, svc_, source):
        ingest_document(db_, svc_, source, "keep", "keep.md", None, "Keep this document about pineapples.", [TENANT_ALL])
        return {"keep"}, []

    ingest_document(db, svc, src, "gone", "gone.md", None, "Removed document about pineapples too.", [TENANT_ALL])
    monkeypatch.setitem(SYNCERS, "github", fake_sync)
    sync_source(db, svc, src)

    titles = {c["title"] for c in ask(admin, "pineapples")["citations"]}
    assert titles == {"keep.md"} and src.status == "ok"


def test_drive_acl_translation_fails_closed():
    perms = [
        {"type": "user", "emailAddress": "Dana@Acme.com"},
        {"type": "group", "emailAddress": "eng@acme.com"},
        {"type": "domain", "domain": "acme.com"},
        {"type": "anyone", "allowFileDiscovery": False},  # link-only: NOT public
    ]
    acl = drive_acl(perms, [{"emailAddress": "owner@acme.com"}], "sync@acme.com")
    assert set(acl) == {"user:dana@acme.com", "group:eng@acme.com", "domain:acme.com", "user:owner@acme.com"}
    assert TENANT_ALL not in acl
    assert drive_acl(None, None, "Sync@acme.com") == ["user:sync@acme.com"]  # no sharing info -> syncer only
    assert TENANT_ALL in drive_acl([{"type": "anyone", "allowFileDiscovery": True}], [], "s@acme.com")


def test_principals_include_domain_and_groups():
    u = User(email="Eve@Acme.com", domain="acme.com", groups=["eng@acme.com"])
    assert principals_for(u) == sorted(["user:eve@acme.com", "tenant:all", "domain:acme.com", "group:eng@acme.com"])


def test_auth_required_and_admin_only(client_factory):
    from fastapi.testclient import TestClient
    from app.main import app

    anon = TestClient(app)
    assert anon.post("/chat", json={"question": "hi"}).status_code == 401
    assert anon.get("/sources").status_code == 401
    assert client_factory("bob@acme.com").get("/admin/status").status_code == 403
    assert client_factory("admin@acme.com").get("/admin/status").status_code == 200


def test_cannot_touch_someone_elses_source(client_factory):
    alice, bob = client_factory("alice@acme.com"), client_factory("bob@acme.com")
    upload(alice, "a.md", "alice private notes")
    sid = alice.get("/sources").json()[0]["id"]
    assert bob.delete(f"/sources/{sid}").status_code == 404
    assert bob.get("/sources").json() == []
    assert alice.delete(f"/sources/{sid}").status_code == 204


def test_chunks_of_one_document_become_one_citation(client_factory):
    alice = client_factory("alice@acme.com")
    big = "\n\n".join(f"Section {i}: railway vibration sensors detect faults early. " + "detail " * 120 for i in range(12))
    upload(alice, "report.pdf.md", big)
    upload(alice, "other.md", "Railway vibration notes in a second file.")
    cites = ask(alice, "railway vibration sensors")["citations"]
    titles = [c["title"] for c in cites]
    assert sorted(titles) == sorted(set(titles))  # no document listed twice
    assert [c["n"] for c in cites] == list(range(1, len(cites) + 1))


def test_followup_is_rewritten_using_history_and_stays_acl_filtered(client_factory, svc):
    alice, bob = client_factory("alice@acme.com"), client_factory("bob@acme.com")
    upload(alice, "plan.md", "Roadmap codename falcon launches in March.")
    history = [{"role": "user", "content": "Tell me about falcon"}, {"role": "assistant", "content": "It is a roadmap item."}]

    # no history -> no rewrite call
    ask(alice, "falcon roadmap")
    assert svc.llm.rewrites == []

    out = alice.post("/chat", json={"question": "when does it launch?", "history": history}).json()
    assert len(svc.llm.rewrites) == 1 and out["search_query"] == "falcon roadmap launch month"
    assert out["citations"] and out["citations"][0]["title"] == "plan.md"

    # same history from another user must not unlock alice's private doc
    leak = bob.post("/chat", json={"question": "when does it launch?", "history": history}).json()
    assert leak["citations"] == [] and leak["answer"] == NO_ACCESS


def test_rewrite_failure_falls_back_to_original_question(client_factory, svc, monkeypatch):
    alice = client_factory("alice@acme.com")
    upload(alice, "plan.md", "Roadmap codename falcon launches in March.")
    real = svc.llm.generate

    def flaky(system, prompt):
        if system.startswith("Rewrite"):
            raise RuntimeError("gemini busy")
        return real(system, prompt)

    monkeypatch.setattr(svc.llm, "generate", flaky)
    h = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    out = alice.post("/chat", json={"question": "falcon roadmap", "history": h}).json()
    assert out["search_query"] == "falcon roadmap" and out["citations"]


class PromoteNeedle:
    """Stand-in reranker: puts the passage mentioning 'needle' first; records what it was shown."""

    def __init__(self):
        self.seen_texts: list[str] = []

    def rerank(self, query, hits, top_k):
        self.seen_texts += [h.text for h in hits]
        return sorted(hits, key=lambda h: "needle" not in h.text)[:top_k]


def test_reranker_reorders_but_only_sees_acl_filtered_candidates(client_factory, svc):
    alice, bob = client_factory("alice@acme.com"), client_factory("bob@acme.com")
    upload(alice, "secret.md", "Confidential needle: board acquisition plan for project orchid.", "private")
    upload(bob, "a.md", "Orchid care guide: water weekly and keep in indirect light.", "org")
    upload(bob, "b.md", "The orchid needle-nose pliers are stored in the toolbox.", "org")
    rr = PromoteNeedle()
    svc.reranker = rr

    out = ask(bob, "orchid")
    assert out["citations"][0]["title"] == "b.md"  # reranker's choice wins over search order
    assert not any("acquisition plan" in t for t in rr.seen_texts)  # never saw alice's private text
    assert all("acquisition" not in c["snippet"] for c in out["citations"])


def parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(l.split(": ", 1) for l in block.split("\n"))
        events.append((lines["event"], __import__("json").loads(lines["data"])))
    return events


def test_stream_sends_sources_first_then_tokens_then_done(client_factory):
    alice = client_factory("alice@acme.com")
    upload(alice, "plan.md", "Roadmap codename falcon launches in March.")
    r = alice.post("/chat/stream", json={"question": "falcon roadmap"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = parse_sse(r.text)
    names = [n for n, _ in ev]
    assert names[0] == "meta" and names[-1] == "done" and names.count("token") == 3
    assert ev[0][1]["citations"][0]["title"] == "plan.md"
    assert "".join(d["text"] for n, d in ev if n == "token") == "Here is the answer [1]."
    assert ev[-1][1]["cited"] == [1]


def test_stream_respects_acl_and_never_calls_llm_without_access(client_factory, svc):
    alice, bob = client_factory("alice@acme.com"), client_factory("bob@acme.com")
    upload(alice, "plan.md", "Roadmap codename falcon launches in March.")
    ev = parse_sse(bob.post("/chat/stream", json={"question": "falcon roadmap"}).text)
    assert ev[0][1]["citations"] == []
    assert "".join(d["text"] for n, d in ev if n == "token") == NO_ACCESS
    assert svc.llm.prompts == []


def test_stream_requires_login_and_reports_llm_failure(client_factory, svc, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    assert TestClient(app).post("/chat/stream", json={"question": "x"}).status_code == 401

    alice = client_factory("alice@acme.com")
    upload(alice, "plan.md", "Roadmap codename falcon launches in March.")

    def boom(system, prompt):
        raise RuntimeError("secret internal detail")
        yield  # pragma: no cover

    monkeypatch.setattr(svc.llm, "generate_stream", boom)
    ev = parse_sse(alice.post("/chat/stream", json={"question": "falcon roadmap"}).text)
    assert ev[-1][0] == "error" and "secret internal detail" not in ev[-1][1]["message"]


def test_cited_numbers_handles_lists():
    from app.rag import cited_numbers

    assert cited_numbers("A [1]. B [2, 3]. C [4,5].") == {1, 2, 3, 4, 5}
    assert cited_numbers("no cites, array[0] ok? [x]") == {0}  # bare digits in brackets still count


def test_chat_endpoints_are_rate_limited_per_user(client_factory, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "chat_per_minute", 2)
    alice, bob = client_factory("alice@acme.com"), client_factory("bob@acme.com")
    assert ask(alice, "one")["answer"] and ask(alice, "two")["answer"]
    r = alice.post("/chat", json={"question": "three"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert alice.post("/chat/stream", json={"question": "x"}).status_code == 429  # shared budget
    assert bob.post("/chat", json={"question": "mine"}).status_code == 200  # other users unaffected
