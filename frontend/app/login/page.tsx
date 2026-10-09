"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, API_URL } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { DemoUser } from "@/lib/types";
import { Badge, ErrorBanner, Spinner } from "@/components/ui";

export default function Login() {
  const { login, me } = useAuth();
  const router = useRouter();
  const [users, setUsers] = useState<DemoUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => { if (me) router.replace("/chat"); }, [me, router]);
  useEffect(() => { api<DemoUser[]>("/api/demo/users", { key: "" }).then(setUsers).catch((e: Error) => { setUsers([]); if (!e.message.includes("Not found")) setError(e.message); }); }, []);

  const go = async (k: string, id: string) => {
    setBusy(id); setError(null);
    try { await login(k); router.replace("/chat"); } catch (e) { setError((e as Error).message); setBusy(null); }
  };
  return (
    <div className="login">
      <section className="login-hero">
        <div className="brand"><div className="brand-mark">C</div>Ops Copilot</div>
        <h1>AI operations assistant for B2B teams</h1>
        <p>Ask about policies, products, inventory and orders. Every answer cites its sources, every tool call is visible, and nothing changes without your confirmation.</p>
        <ul>
          <li>Hybrid retrieval over your documents (vector + keyword)</li><li>Tenant-isolated data and role-based permissions</li>
          <li>Human-in-the-loop approvals for every state change</li>
        </ul>
      </section>
      <section className="login-panel">
        <div><h1>Sign in</h1><p className="muted" style={{ margin: "4px 0 0" }}>Choose a demo persona or paste an API key.</p></div>
        <ErrorBanner error={error} />
        {users === null ? <Spinner /> : users.length > 0 && (
          <div className="stack">
            <div className="faint" style={{ fontWeight: 600, fontSize: 12, textTransform: "uppercase", letterSpacing: ".05em" }}>Demo users</div>
            {users.map((u) => (
              <button key={u.label} className="persona" disabled={!!busy} onClick={() => go(u.api_key, u.label)}>
                <div className="avatar">{u.name.split(" ").map((p) => p[0]).join("")}</div>
                <div style={{ flex: 1 }}><b>{u.name}</b><div className="muted">{u.tenant}</div></div>
                {busy === u.label ? <Spinner /> : <Badge tone={u.role === "admin" ? "brand" : u.role === "manager" ? "info" : "neutral"}>{u.role}</Badge>}
              </button>))}
          </div>)}
        <form className="stack" onSubmit={(e) => { e.preventDefault(); if (key.trim()) go(key, "key"); }}>
          <label htmlFor="key" className="faint" style={{ fontWeight: 600, fontSize: 12, textTransform: "uppercase", letterSpacing: ".05em" }}>API key</label>
          <input id="key" className="input" type="password" autoComplete="off" placeholder="X-API-Key" value={key} onChange={(e) => setKey(e.target.value)} />
          <button className="btn primary" disabled={!key.trim() || !!busy} style={{ justifyContent: "center" }}>{busy === "key" ? <Spinner /> : "Sign in with key"}</button>
        </form>
        <small className="faint">API: {API_URL}</small>
      </section>
    </div>
  );
}
