"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ActionRow } from "@/lib/types";
import { Badge, Spinner } from "./ui";

const I = (d: string) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>;
const NAV = [
  { href: "/chat", label: "Copilot", icon: I("M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"), group: "Assistant" },
  { href: "/actions", label: "Approvals", icon: I("M9 12l2 2 4-4M12 3l8 4v5c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V7z"), group: "Assistant" },
  { href: "/documents", label: "Documents", icon: I("M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h6"), group: "Workspace" },
  { href: "/inventory", label: "Inventory", icon: I("M21 8l-9-5-9 5v8l9 5 9-5zM3 8l9 5 9-5M12 13v8"), group: "Workspace" },
  { href: "/orders", label: "Orders", icon: I("M6 6h15l-1.5 9h-12zM6 6L5 3H2M9 20a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM18 20a1 1 0 1 0 0-2 1 1 0 0 0 0 2z"), group: "Workspace" },
  { href: "/usage", label: "Usage", icon: I("M4 20V10M10 20V4M16 20v-7M22 20H2"), group: "Insights" },
  { href: "/evaluation", label: "Evaluation", icon: I("M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"), group: "Insights" },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const { me, loading, logout } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(0);

  useEffect(() => { if (!loading && !me) router.replace("/login"); }, [me, loading, router]);
  useEffect(() => { setOpen(false); }, [path]);
  useEffect(() => {
    if (!me) return;
    const load = () => api<ActionRow[]>("/api/actions?status=pending").then((a) => setPending(a.length)).catch(() => {});
    load();
    const t = setInterval(load, 15000);
    const h = () => load();
    window.addEventListener("actions-changed", h);
    return () => { clearInterval(t); window.removeEventListener("actions-changed", h); };
  }, [me, path]);

  if (loading || !me) return <div style={{ display: "grid", placeItems: "center", height: "100vh" }}><Spinner /></div>;
  const groups = [...new Set(NAV.map((n) => n.group))];
  const initials = me.name.split(" ").map((p) => p[0]).slice(0, 2).join("");
  return (
    <div className="shell">
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="brand"><div className="brand-mark">C</div>Ops Copilot</div>
        <nav className="nav" aria-label="Main">
          {groups.map((g) => (
            <div key={g}><div className="nav-label">{g}</div>
              {NAV.filter((n) => n.group === g).map((n) => (
                <Link key={n.href} href={n.href} className={path.startsWith(n.href) ? "active" : ""}>
                  {n.icon}{n.label}{n.href === "/actions" && pending > 0 && <span className="count">{pending}</span>}
                </Link>))}
            </div>))}
        </nav>
        <div className="side-foot">{me.tenant}<br />Signed in as {me.role}</div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button className="menu-btn" onClick={() => setOpen((o) => !o)} aria-label="Toggle navigation">☰</button>
          <strong>{me.tenant}</strong><Badge tone={me.role === "admin" ? "brand" : me.role === "manager" ? "info" : "neutral"}>{me.role}</Badge>
          <div className="spacer" />
          <div className="user-chip"><div className="avatar">{initials}</div><div className="user-meta"><div>{me.name}</div><small>{me.email}</small></div></div>
          <button className="btn sm" onClick={() => { logout(); router.replace("/login"); }}>Sign out</button>
        </header>
        {children}
      </div>
    </div>
  );
}
