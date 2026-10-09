"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "ok" | "warn" | "bad" | "info" | "brand"; children: React.ReactNode }) {
  return <span className={`badge ${tone === "neutral" ? "" : tone}`}>{children}</span>;
}
export const statusTone = (s: string): "ok" | "warn" | "bad" | "info" | "neutral" =>
  ({ delivered: "ok", shipped: "info", confirmed: "info", pending: "warn", on_hold: "warn", cancelled: "bad", OK: "ok", LOW: "warn", OUT_OF_STOCK: "bad", DISCONTINUED: "neutral",
    failed: "bad", rejected: "neutral", expired: "neutral" } as Record<string, "ok" | "warn" | "bad" | "info" | "neutral">)[s] ?? "neutral";
export const label = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export function ErrorBanner({ error, retry }: { error: string | null; retry?: () => void }) {
  if (!error) return null;
  return <div className="banner bad" role="alert"><div style={{ flex: 1 }}><b>Something went wrong.</b> {error}</div>{retry && <button className="btn sm" onClick={retry}>Retry</button>}</div>;
}
export function Skeleton({ rows = 5 }: { rows?: number }) {
  return <div className="stack" style={{ padding: 18 }} aria-busy="true" aria-label="Loading">{Array.from({ length: rows }, (_, i) => <div key={i} className="skel" style={{ width: `${95 - ((i * 13) % 40)}%` }} />)}</div>;
}
export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return <div className="empty"><b>{title}</b>{children}</div>;
}
export function Spinner() { return <span className="spinner" role="status" aria-label="Loading" />; }

export function PageHead({ title, sub, children }: { title: string; sub?: string; children?: React.ReactNode }) {
  return <div className="page-head"><div><h1>{title}</h1>{sub && <p>{sub}</p>}</div>{children && <div className="right">{children}</div>}</div>;
}

export function Modal({ title, children, onClose, footer }: { title: string; children: React.ReactNode; onClose: () => void; footer: React.ReactNode }) {
  useEffect(() => { const h = (e: KeyboardEvent) => e.key === "Escape" && onClose(); window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h); }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head"><h2>{title}</h2></div><div className="modal-body">{children}</div><div className="modal-foot">{footer}</div>
      </div>
    </div>
  );
}
export function Drawer({ title, sub, children, onClose }: { title: string; sub?: React.ReactNode; children: React.ReactNode; onClose: () => void }) {
  useEffect(() => { const h = (e: KeyboardEvent) => e.key === "Escape" && onClose(); window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h); }, [onClose]);
  return (<>
    <div className="overlay" style={{ zIndex: 54, placeItems: "stretch" }} onMouseDown={onClose} />
    <aside className="drawer" role="dialog" aria-label={title}>
      <div className="drawer-head"><div style={{ flex: 1, minWidth: 0 }}><h2>{title}</h2>{sub && <div className="muted" style={{ marginTop: 2 }}>{sub}</div>}</div><button className="btn sm ghost" onClick={onClose} aria-label="Close">✕</button></div>
      <div className="drawer-body">{children}</div>
    </aside></>);
}

type Toast = { id: number; msg: string; tone: "ok" | "bad" | "info" };
const ToastCtx = createContext<(msg: string, tone?: Toast["tone"]) => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((msg: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, msg, tone }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 4200);
  }, []);
  return <ToastCtx.Provider value={push}>{children}<div className="toasts" aria-live="polite">{items.map((t) => <div key={t.id} className={`toast ${t.tone === "info" ? "" : t.tone}`}>{t.msg}</div>)}</div></ToastCtx.Provider>;
}

export function useFetch<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const run = useCallback(() => {
    setLoading(true); setError(null);
    loader().then(setData).catch((e: Error) => setError(e.message)).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(run, [run]);
  return { data, error, loading, reload: run, setData };
}

export function BarChart({ data, height = 140 }: { data: { label: string; value: number }[]; height?: number }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const w = 100 / Math.max(1, data.length);
  return (
    <svg viewBox={`0 0 100 ${height / 4 + 8}`} width="100%" height={height + 24} role="img" aria-label="Bar chart" preserveAspectRatio="none">
      {data.map((d, i) => { const h = (d.value / max) * (height / 4); const bw = Math.min(w * 0.64, 6); return (
        <g key={d.label}><rect x={i * w + (w - bw) / 2} y={height / 4 - h} width={bw} height={h} rx="0.8" fill="var(--brand)" opacity=".9"><title>{`${d.label}: ${d.value}`}</title></rect></g>); })}
      <line x1="0" x2="100" y1={height / 4} y2={height / 4} stroke="var(--border-strong)" strokeWidth=".3" />
    </svg>
  );
}
