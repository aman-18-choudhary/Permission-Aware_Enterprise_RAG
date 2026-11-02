export type Me = { id: string; email: string; name: string; is_admin: boolean; drive_connected: boolean };
export type Citation = { n: number; title: string; url: string | null; snippet: string; cited: boolean };
export type Source = {
  id: string; kind: string; name: string; status: string;
  last_error: string | null; last_synced_at: string | null; documents: number;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { credentials: "include", ...init });
  if (res.status === 401) throw new Error("Your session has expired. Please sign in again.");
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail ?? msg; } catch {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

type StreamHandlers = {
  meta?: (d: { search_query: string; citations: Citation[] }) => void;
  token?: (d: { text: string }) => void;
  done?: (d: { cited: number[] }) => void;
  error?: (d: { message: string }) => void;
};

/** POST /chat/stream and dispatch server-sent events (EventSource can't POST). */
export async function streamChat(
  question: string,
  history: { role: string; content: string }[],
  h: StreamHandlers,
): Promise<void> {
  const res = await fetch("/api/chat/stream", { ...json({ question, history }), credentials: "include" });
  if (res.status === 401) throw new Error("Your session has expired. Please sign in again.");
  if (res.status === 429) throw new Error("You are asking too fast. Wait a few seconds and try again.");
  if (!res.ok || !res.body) {
    let detail = res.statusText || "request failed";
    try { detail = (await res.json()).detail ?? detail; } catch {}
    throw new Error(typeof detail === "string" ? detail : "request failed");
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const event = /^event: (.+)$/m.exec(block)?.[1] as keyof StreamHandlers | undefined;
      const data = /^data: (.+)$/m.exec(block)?.[1];
      if (event && data && h[event]) (h[event] as (d: unknown) => void)(JSON.parse(data));
    }
  }
}
