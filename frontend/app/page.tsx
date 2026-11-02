"use client";
import { FormEvent, useState } from "react";
import { streamChat, Citation } from "@/lib/api";
import { useMe } from "@/lib/useMe";

type Turn = { q: string; a?: string; citations?: Citation[]; error?: string; done?: boolean };

export default function Home() {
  const { me, loading } = useMe();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);

  if (loading) return <p className="muted">Loading…</p>;
  if (!me)
    return (
      <section className="hero">
        <h1>Ask your company anything.</h1>
        <p className="muted">Answers come only from documents you are allowed to see, with citations.</p>
        <a className="btn" href="/api/auth/login">Sign in with Google</a>
      </section>
    );

  async function ask(e: FormEvent) {
    e.preventDefault();
    const question = q.trim();
    if (!question || busy) return;
    setQ("");
    setBusy(true);
    // Prior completed turns, so follow-ups like "when does it launch?" can be resolved.
    const history = turns
      .filter((t) => t.done && t.a)
      .slice(-4)
      .flatMap((t) => [
        { role: "user", content: t.q },
        { role: "assistant", content: t.a as string },
      ]);
    // Update the newest turn in place as events arrive.
    const patch = (fn: (t: Turn) => Turn) => setTurns((all) => all.map((x, i) => (i === all.length - 1 ? fn(x) : x)));
    setTurns((t) => [...t, { q: question }]);
    try {
      await streamChat(question, history, {
        meta: (m) => patch((t) => ({ ...t, citations: m.citations })),
        token: (d) => patch((t) => ({ ...t, a: (t.a ?? "") + d.text })),
        done: (d) =>
          patch((t) => ({
            ...t,
            done: true,
            citations: t.citations?.map((c) => ({ ...c, cited: d.cited.includes(c.n) })),
          })),
        error: (e) => patch((t) => ({ ...t, error: e.message })),
      });
    } catch (err) {
      patch((t) => ({ ...t, error: (err as Error).message }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <div className="turns">
        {turns.length === 0 && <p className="muted">Try: “What is our leave policy?” or paste a ticket ID like JIRA-4521.</p>}
        {turns.map((t, i) => (
          <div key={i} className="turn">
            <div className="q">{t.q}</div>
            {t.error && <div className="err">{t.error}</div>}
            {t.a ? (
              <div className="a">
                <p>{t.a}</p>
                {t.done && !!t.citations?.length && (
                  <ol className="cites">
                    {t.citations.map((c) => (
                      <li key={c.n} className={c.cited ? "cited" : ""}>
                        <b>[{c.n}]</b>{" "}
                        {c.url ? <a href={c.url} target="_blank" rel="noreferrer">{c.title}</a> : c.title}
                        <div className="muted snippet">{c.snippet}</div>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            ) : !t.error && <div className="muted">Thinking…</div>}
          </div>
        ))}
      </div>
      <form onSubmit={ask} className="ask">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask a question…" maxLength={2000} />
        <button className="btn" disabled={busy}>Ask</button>
      </form>
    </section>
  );
}
