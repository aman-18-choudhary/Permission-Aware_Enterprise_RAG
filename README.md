# Second Brain: permission-aware enterprise RAG

Chat over company documents (file uploads, GitHub, Google Drive). Answers carry
citations and are built **only from documents the signed-in user may access**.
Slides for the idea: [`docs/Second_Brain_RAG_Presentation.pptx`](docs/Second_Brain_RAG_Presentation.pptx).

## How it works

```
Upload / GitHub / Drive ─▶ parse ─▶ chunk ─▶ Gemini embeddings ─▶ Qdrant
                                              (dense + sparse BM25-style vectors, ACL in payload)
Question ─▶ user's principals ─▶ Qdrant hybrid search (RRF) with ACL PRE-filter ─▶ Gemini answer + citations
```

- **ACL model** ([`backend/app/acl.py`](backend/app/acl.py)): each document stores principals
  (`user:`, `group:`, `domain:`, `tenant:all`). A user's principal set is intersected with them
  *inside* Qdrant (pre-filter on both the dense and sparse prefetch), so restricted chunks are never
  candidates and never reach the LLM. If nothing is accessible, the LLM isn't called at all.
- **Drive sync** reads each file's sharing permissions. Share/revoke changes only patch the ACL payload (no
  re-embedding). Files deleted or no longer visible upstream are pruned on the next sync.
  If Drive doesn't expose a file's sharing list, the file is visible to the syncing user only (fail closed).
  "Anyone with the link" files are *not* treated as public.
- **Auth**: Google OAuth (login = `openid email profile`; Drive is a separate opt-in consent with read-only scope).
  Session is an HttpOnly, SameSite=Lax JWT cookie; Drive refresh tokens are encrypted at rest.
- **Follow-ups**: the client sends recent turns; the backend rewrites the latest message into a standalone
  search question (falls back to the original if that fails). History never widens access: retrieval is
  always filtered for the signed-in user. Citations are grouped per document.
- **Admin view** (`/admin`): totals, per-source sync status/errors, recent-query audit log.

## Run it

```bash
cp .env.example .env     # fill in GEMINI_API_KEY, Google OAuth creds, SECRET_KEY, POSTGRES_PASSWORD
docker compose up --build
# open http://localhost:3000
```

Without Docker (dev, in-memory Qdrant, SQLite):

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt
AUTH_DEV_MODE=true GEMINI_API_KEY=... .venv/bin/uvicorn app.main:app --reload   # :8000
cd ../frontend && npm install && npm run dev                                    # :3000
```
`AUTH_DEV_MODE=true` enables `/auth/dev-login` (log in as any email, no Google). Refused when `ENV=prod`.
`QDRANT_URL` picks the vector store: `:memory:` (lost on restart), a folder path like `./data/qdrant`
(embedded, persisted on disk, single process), or `http://qdrant:6333` (server; what docker compose uses).

If calls to Google/Gemini hang for 15-40 s, your network probably advertises IPv6 but doesn't route it.
Set `FORCE_IPV4=true` in `.env` (see `backend/app/net.py`).

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q
```
Covers: private docs invisible to others (and never sent to the LLM), org sharing, exact-ID keyword matching,
ACL grant/revoke without re-embedding, group principals, upstream-deletion pruning, Drive ACL translation, authz.
Tests use a fake embedder/LLM; **Gemini, Google OAuth, Drive and GitHub calls are not covered by automated tests**
and need a manual pass with real credentials.

## Known limitations / next steps

- **Google Groups**: Drive shares to a group are honored, but membership is admin-assigned
  (`PUT /admin/users/{id}/groups`), not auto-synced from Google (needs Cloud Identity / Admin SDK).
- **GitHub ACL** is per-source (private = you, org = everyone), not mirrored from repo collaborators.
- The same Drive file synced by two users is indexed twice (once per user's source).
- No reranker yet (RRF only), no streaming, chat history lives in the browser tab only, PDF text only (no OCR).
- Schema is created with `create_all`; add Alembic before real production use.
- Sync runs in FastAPI background tasks; move to a queue (Celery/Arq) for scale.
