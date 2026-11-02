"use client";
import { useCallback, useEffect, useState } from "react";
import { api, json } from "@/lib/api";
import { useMe } from "@/lib/useMe";

type Status = {
  totals: { users: number; sources: number; documents: number; chunks: number };
  sources: { id: string; kind: string; name: string; owner: string; status: string; last_error: string | null; last_synced_at: string | null; documents: number }[];
  recent_queries: { user: string; question: string; answered: boolean; at: string }[];
};
type AdminUser = { id: string; email: string; is_admin: boolean; domain: string | null; groups: string[] };

export default function Admin() {
  const { me, loading } = useMe();
  const [s, setS] = useState<Status | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(() => api<Status>("/admin/status").then(setS).catch((e) => setErr(e.message)), []);
  const loadUsers = useCallback(() => api<AdminUser[]>("/admin/users").then(setUsers).catch(() => {}), []);
  useEffect(() => {
    if (!me?.is_admin) return;
    load(); loadUsers();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [me, load, loadUsers]);

  if (loading) return <p className="muted">Loading…</p>;
  if (!me?.is_admin) return <p>Admins only.</p>;
  if (err) return <p className="err">{err}</p>;
  if (!s) return <p className="muted">Loading…</p>;

  const saveGroups = async (u: AdminUser) => {
    const groups = (edits[u.id] ?? u.groups.join(", ")).split(",").map((g) => g.trim()).filter(Boolean);
    try {
      await api(`/admin/users/${u.id}/groups`, { ...json({ groups }), method: "PUT" });
      setNote(`Groups saved for ${u.email}.`);
      setEdits((e) => { const { [u.id]: _drop, ...rest } = e; return rest; });
      loadUsers();
    } catch (e) { setNote((e as Error).message); }
  };

  const sync = async (id: string) => {
    try { await api(`/sources/${id}/sync`, { method: "POST" }); setNote("Sync started."); load(); }
    catch (e) { setNote((e as Error).message); }
  };

  return (
    <section>
      <h2>Admin</h2>
      {note && <p className="note">{note}</p>}
      <div className="stats">
        {Object.entries(s.totals).map(([k, v]) => (
          <div key={k} className="stat"><div className="num">{v}</div><div className="muted">{k}</div></div>
        ))}
      </div>

      <h3>Sources &amp; sync status</h3>
      <table>
        <thead><tr><th>Name</th><th>Type</th><th>Owner</th><th>Docs</th><th>Status</th><th>Last sync</th><th></th></tr></thead>
        <tbody>
          {s.sources.map((x) => (
            <tr key={x.id}>
              <td>{x.name}</td><td>{x.kind}</td><td>{x.owner}</td><td>{x.documents}</td>
              <td><span className={`pill ${x.status}`}>{x.status}</span>{x.last_error && <div className="err small">{x.last_error}</div>}</td>
              <td>{x.last_synced_at ? new Date(x.last_synced_at).toLocaleString() : "never"}</td>
              <td>{x.kind !== "upload" && <button className="ghost" disabled={x.status === "syncing"} onClick={() => sync(x.id)}>Sync now</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Users &amp; groups</h3>
      <p className="muted small">
        A user sees documents shared with <code>group:&lt;email&gt;</code> principals they belong to (e.g. a Drive file shared with
        eng@company.com). Enter group emails separated by commas.
      </p>
      <table>
        <thead><tr><th>User</th><th>Domain</th><th>Groups</th><th></th></tr></thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.email}{u.is_admin && <span className="pill ok" style={{ marginLeft: 8 }}>admin</span>}</td>
              <td>{u.domain ?? <span className="muted">-</span>}</td>
              <td><input value={edits[u.id] ?? u.groups.join(", ")} onChange={(e) => setEdits({ ...edits, [u.id]: e.target.value })} placeholder="eng@company.com, finance@company.com" /></td>
              <td><button className="ghost" disabled={edits[u.id] === undefined} onClick={() => saveGroups(u)}>Save</button></td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Recent queries (audit)</h3>
      <table>
        <thead><tr><th>When</th><th>User</th><th>Question</th><th>Answered</th></tr></thead>
        <tbody>
          {s.recent_queries.map((q, i) => (
            <tr key={i}><td>{new Date(q.at).toLocaleString()}</td><td>{q.user}</td><td>{q.question}</td><td>{q.answered ? "yes" : "no access / none"}</td></tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
