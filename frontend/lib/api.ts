export type Me = { id: string; email: string; name: string; is_admin: boolean; drive_connected: boolean };
export type Citation = { n: number; title: string; url: string | null; snippet: string; cited: boolean };
export type Source = {
  id: string; kind: string; name: string; status: string;
  last_error: string | null; last_synced_at: string | null; documents: number;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { credentials: "include", ...init });
  if (res.status === 401) throw new Error("unauthenticated");
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
