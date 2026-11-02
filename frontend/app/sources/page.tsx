"use client";
import { FormEvent, Fragment, useCallback, useEffect, useState } from "react";
import { api, json, Source } from "@/lib/api";
import { useMe } from "@/lib/useMe";

type Doc = { id: string; title: string; url: string | null; chunks: number; visibility: string };

export default function Sources() {
  const { me, loading } = useMe();
  const [sources, setSources] = useState<Source[]>([]);
  const [msg, setMsg] = useState("");
  const [repo, setRepo] = useState("");
  const [vis, setVis] = useState("private");
  const [open, setOpen] = useState<string | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);

  const load = useCallback(() => api<Source[]>("/sources").then(setSources).catch(() => {}), []);
  const loadDocs = useCallback((id: string) => api<Doc[]>(`/sources/${id}/documents`).then(setDocs).catch(() => setDocs([])), []);
  useEffect(() => { if (me) load(); }, [me, load]);
  // poll while anything is syncing
  useEffect(() => {
    if (!sources.some((s) => s.status === "syncing")) return;
    const t = setInterval(() => { load(); if (open) loadDocs(open); }, 3000);
    return () => clearInterval(t);
  }, [sources, load, open, loadDocs]);

  if (loading) return <p className="muted">Loading…</p>;
  if (!me) return <p>Please <a href="/api/auth/login">sign in</a>.</p>;

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg("");
    try { await fn(); setMsg(ok); load(); if (open) loadDocs(open); } catch (e) { setMsg((e as Error).message); }
  };

  const toggle = (id: string) => {
    if (open === id) return setOpen(null);
    setOpen(id);
    setDocs([]);
    loadDocs(id);
  };

  const upload = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const fd = new FormData(form);
    run(async () => { await api("/sources/upload", { method: "POST", body: fd }); form.reset(); }, "Uploaded and indexed.");
  };

  return (
    <section>
      <h2>Sources</h2>
      {msg && <p className="note">{msg}</p>}

      <div className="grid">
        <form onSubmit={upload} className="card">
          <h3>Upload a file</h3>
          <input type="file" name="file" accept=".pdf,.docx,.txt,.md,.csv,.json" required />
          <label>Who can see it?
            <select name="visibility" defaultValue="private">
              <option value="private">Only me</option>
              <option value="org">Everyone in the company</option>
            </select>
          </label>
          <button className="btn">Upload</button>
        </form>

        <form className="card" onSubmit={(e) => { e.preventDefault(); run(() => api("/sources/github", json({ repo, visibility: vis })), "Repository added; syncing…"); setRepo(""); }}>
          <h3>GitHub repository</h3>
          <input placeholder="owner/name" value={repo} onChange={(e) => setRepo(e.target.value)} required />
          <label>Who can see it?
            <select value={vis} onChange={(e) => setVis(e.target.value)}>
              <option value="private">Only me</option>
              <option value="org">Everyone in the company</option>
            </select>
          </label>
          <button className="btn">Add &amp; sync</button>
        </form>

        <div className="card">
          <h3>Google Drive</h3>
          <p className="muted">Files are indexed with their Drive sharing permissions and re-synced automatically.</p>
          {me.drive_connected ? (
            <>
              <span className="pill ok">Connected</span>{" "}
              <button
                className="ghost danger"
                onClick={() => confirm("Disconnect Drive? Everything indexed from it is removed and access is revoked.") &&
                  run(async () => { await api("/auth/drive", { method: "DELETE" }); location.reload(); }, "Disconnected.")}
              >
                Disconnect
              </button>
            </>
          ) : (
            <a className="btn" href="/api/auth/drive/connect">Connect Drive</a>
          )}
        </div>
      </div>

      <h3>Your sources</h3>
      <table>
        <thead><tr><th>Name</th><th>Type</th><th>Docs</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {sources.map((s) => (
            <Fragment key={s.id}>
              <tr>
                <td>{s.name}</td><td>{s.kind}</td><td>{s.documents}</td>
                <td><span className={`pill ${s.status}`}>{s.status}</span>{s.last_error && <div className="err small">{s.last_error}</div>}</td>
                <td className="actions">
                  <button className="ghost" onClick={() => toggle(s.id)}>{open === s.id ? "Hide files" : "Files"}</button>
                  {s.kind !== "upload" && <button className="ghost" disabled={s.status === "syncing"} onClick={() => run(() => api(`/sources/${s.id}/sync`, { method: "POST" }), "Sync started.")}>Sync</button>}
                  <button className="ghost danger" onClick={() => confirm(`Delete ${s.name} and its indexed data?`) && run(() => api(`/sources/${s.id}`, { method: "DELETE" }), "Deleted.")}>Delete</button>
                </td>
              </tr>
              {open === s.id && (
                <tr>
                  <td colSpan={5}>
                    {docs.length === 0 ? <span className="muted">No files.</span> : (
                      <ul className="files">
                        {docs.map((d) => (
                          <li key={d.id}>
                            <span>{d.url ? <a href={d.url} target="_blank" rel="noreferrer">{d.title}</a> : d.title}</span>
                            <span className="muted small">{d.chunks} chunks · {d.visibility}</span>
                            {s.kind === "upload" && (
                              <button className="ghost danger" onClick={() => confirm(`Delete ${d.title}?`) && run(() => api(`/sources/${s.id}/documents/${d.id}`, { method: "DELETE" }), "File deleted.")}>Delete</button>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
          {!sources.length && <tr><td colSpan={5} className="muted">No sources yet.</td></tr>}
        </tbody>
      </table>
    </section>
  );
}
