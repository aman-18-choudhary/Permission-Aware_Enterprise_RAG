"use client";
import Link from "next/link";
import { api } from "@/lib/api";
import { useMe } from "@/lib/useMe";

export default function Nav() {
  const { me } = useMe();
  return (
    <header className="nav">
      <Link href="/" className="brand">Second Brain</Link>
      {me && (
        <nav>
          <Link href="/">Ask</Link>
          <Link href="/sources">Sources</Link>
          {me.is_admin && <Link href="/admin">Admin</Link>}
          <span className="muted">{me.email}</span>
          <button className="ghost" onClick={async () => { await api("/auth/logout", { method: "POST" }); location.href = "/"; }}>
            Sign out
          </button>
        </nav>
      )}
    </header>
  );
}
