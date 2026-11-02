"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMe } from "@/lib/useMe";

type Status = {
  totals: { users: number; sources: number; documents: number; chunks: number };
  sources: { id: string; kind: string; name: string; owner: string; status: string; last_error: string | null; last_synced_at: string | null; documents: number }[];
  recent_queries: { user: string; question: string; answered: boolean; at: string }[];
};

export default function Admin() {
  const { me, loading } = useMe();
  const [s, setS] = useState<Status | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => api<Status>("/admin/status").then(setS).catch((e) => setErr(e.message)), []);
  useEffect(() => { if (me?.is_admin) { load(); const t = setInterval(load, 5000); return () => clearInterval(t); } }, [me, load]);

  if (loading) return <p className="muted">Loading…</p>;
  if (!me?.is_admin) return <p>Admins only.</p>;
  if (err) return <p className="err">{err}</p>;
  if (!s) return <p className="muted">Loading…</p>;

  return (
    <section>
      <h2>Admin: sync status</h2>
      <div className="stats">
        {Object.entries(s.totals).map(([k, v]) => (
          <div key={k} className="stat"><div className="num">{v}</div><div className="muted">{k}</div></div>
        ))}
      </div>

      <h3>Sources</h3>
      <table>
        <thead><tr><th>Name</th><th>Type</th><th>Owner</th><th>Docs</th><th>Status</th><th>Last sync</th></tr></thead>
        <tbody>
          {s.sources.map((x) => (
            <tr key={x.id}>
              <td>{x.name}</td><td>{x.kind}</td><td>{x.owner}</td><td>{x.documents}</td>
              <td><span className={`pill ${x.status}`}>{x.status}</span>{x.last_error && <div className="err small">{x.last_error}</div>}</td>
              <td>{x.last_synced_at ? new Date(x.last_synced_at).toLocaleString() : "never"}</td>
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
