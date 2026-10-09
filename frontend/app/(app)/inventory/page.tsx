"use client";
import { Fragment, useMemo, useState } from "react";
import { Badge, Empty, ErrorBanner, label, PageHead, Skeleton, statusTone, useFetch } from "@/components/ui";
import { api, money } from "@/lib/api";
import type { ProductRow } from "@/lib/types";

const FILTERS = ["all", "LOW", "OUT_OF_STOCK", "OK", "DISCONTINUED"] as const;

export default function InventoryPage() {
  const { data, error, loading, reload } = useFetch(() => api<ProductRow[]>("/api/products"));
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const cats = useMemo(() => [...new Set((data ?? []).map((p) => p.category))], [data]);
  const rows = (data ?? []).filter((p) => (filter === "all" || p.status === filter) && (!cat || p.category === cat) &&
    (!q || (p.sku + " " + p.name).toLowerCase().includes(q.toLowerCase())));
  const count = (s: string) => (data ?? []).filter((p) => p.status === s).length;
  return (
    <div className="content">
      <PageHead title="Inventory" sub="Live stock across warehouses. Available = on hand − reserved; LOW means at or below the reorder point." />
      <div className="grid g4" style={{ marginBottom: 16 }}>
        <div className="card stat"><div className="label">Products</div><div className="value">{data?.length ?? "—"}</div></div>
        <div className="card stat"><div className="label">Low stock</div><div className="value" style={{ color: "var(--warn)" }}>{data ? count("LOW") : "—"}</div></div>
        <div className="card stat"><div className="label">Out of stock</div><div className="value" style={{ color: "var(--bad)" }}>{data ? count("OUT_OF_STOCK") : "—"}</div></div>
        <div className="card stat"><div className="label">Healthy</div><div className="value" style={{ color: "var(--ok)" }}>{data ? count("OK") : "—"}</div></div>
      </div>
      <ErrorBanner error={error} retry={reload} />
      <div className="card">
        <div className="toolbar">
          <input className="input" style={{ maxWidth: 260 }} placeholder="Search SKU or name" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search products" />
          <select className="input" style={{ maxWidth: 180 }} value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Category"><option value="">All categories</option>{cats.map((c) => <option key={c}>{c}</option>)}</select>
          <div className="chips">{FILTERS.map((f) => <button key={f} className={`chip ${filter === f ? "on" : ""}`} onClick={() => setFilter(f)}>{f === "all" ? "All" : label(f)}</button>)}</div>
        </div>
        <div className="table-wrap">{loading ? <Skeleton rows={8} /> : !rows.length ? <Empty title="No products match">Try clearing filters.</Empty> : (
          <table><thead><tr><th>SKU</th><th>Product</th><th>Category</th><th className="num">Price</th><th className="num">On hand</th><th className="num">Reserved</th><th className="num">Available</th><th className="num">Reorder at</th><th>Status</th></tr></thead>
            <tbody>{rows.map((p) => (<Fragment key={p.sku}>
              <tr className="clickable" onClick={() => setOpen(open === p.sku ? null : p.sku)}>
                <td className="mono">{p.sku}</td><td className="wrap">{p.name} {p.hazmat && <Badge tone="warn">hazmat</Badge>}</td><td className="muted">{p.category}</td><td className="num">{money(p.unit_price)}</td>
                <td className="num">{p.on_hand}</td><td className="num">{p.reserved}</td><td className="num"><b>{p.available}</b></td><td className="num">{p.reorder_point}</td><td><Badge tone={statusTone(p.status)}>{label(p.status)}</Badge></td></tr>
              {open === p.sku && <tr><td colSpan={9} style={{ background: "var(--surface-2)" }}>
                <div className="row wrap">{p.warehouses.map((w) => <div key={w.warehouse} className="card card-pad" style={{ minWidth: 200 }}><b>{w.warehouse}</b><div className="muted">{w.available} available · {w.on_hand} on hand · {w.reserved} reserved</div></div>)}
                  <a href={`/chat?q=${encodeURIComponent(`Is ${p.sku} in stock?`)}`} className="btn sm">Ask Copilot</a>{p.status === "LOW" && <a href={`/chat?q=${encodeURIComponent(`Reorder 100 units of ${p.sku}`)}`} className="btn sm primary">Draft reorder</a>}</div></td></tr>}
            </Fragment>))}</tbody></table>)}</div>
      </div>
    </div>
  );
}
