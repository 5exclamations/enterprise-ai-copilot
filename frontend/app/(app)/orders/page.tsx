"use client";
import { useState } from "react";
import { Badge, Drawer, Empty, ErrorBanner, label, PageHead, Skeleton, statusTone, Spinner, useFetch } from "@/components/ui";
import { api, money } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { OrderDetail, OrderRow } from "@/lib/types";

const STATUSES = ["all", "pending", "confirmed", "shipped", "delivered", "on_hold", "cancelled"];

export default function OrdersPage() {
  const { me } = useAuth();
  const { data, error, loading, reload } = useFetch(() => api<OrderRow[]>("/api/orders"));
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<OrderDetail | null>(null);
  const [loadingDetail, setLd] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const rows = (data ?? []).filter((o) => (status === "all" || o.status === status) && (!q || (o.order_number + o.customer).toLowerCase().includes(q.toLowerCase())));
  const open = async (n: string) => { setLd(n); setErr(null); try { setSel(await api<OrderDetail>(`/api/orders/${n}`)); } catch (e) { setErr((e as Error).message); } finally { setLd(null); } };
  const ask = (text: string) => `/chat?q=${encodeURIComponent(text)}`;
  return (
    <div className="content">
      <PageHead title="Orders" sub="Customer orders for your organization. Status changes are made through the Copilot and require manager approval." />
      <ErrorBanner error={error ?? err} retry={reload} />
      <div className="card">
        <div className="toolbar">
          <input className="input" style={{ maxWidth: 260 }} placeholder="Search order or customer" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search orders" />
          <div className="chips">{STATUSES.map((s) => <button key={s} className={`chip ${status === s ? "on" : ""}`} onClick={() => setStatus(s)}>{s === "all" ? "All" : label(s)}</button>)}</div>
          {loadingDetail && <Spinner />}
        </div>
        <div className="table-wrap">{loading ? <Skeleton rows={8} /> : !rows.length ? <Empty title="No orders match" /> : (
          <table><thead><tr><th>Order</th><th>Customer</th><th>Status</th><th>Placed</th><th className="num">Lines</th><th className="num">Total</th></tr></thead>
            <tbody>{rows.map((o) => <tr key={o.order_number} className="clickable" onClick={() => open(o.order_number)}>
              <td className="mono"><b>{o.order_number}</b></td><td>{o.customer}</td><td><Badge tone={statusTone(o.status)}>{label(o.status)}</Badge></td><td className="muted">{o.created_on}</td><td className="num">{o.items}</td><td className="num">{money(o.total)}</td></tr>)}</tbody></table>)}</div>
      </div>
      {sel && (
        <Drawer title={`Order ${sel.order_number}`} sub={<Badge tone={statusTone(sel.status)}>{label(sel.status)}</Badge>} onClose={() => setSel(null)}>
          <div className="stack">
            <dl className="kv"><dt>Customer</dt><dd>{sel.customer} <Badge>{sel.tier}</Badge></dd><dt>Email</dt><dd>{sel.email}</dd><dt>Phone</dt><dd>{sel.phone}</dd></dl>
            {me?.role === "viewer" && <div className="banner info">Contact details are masked for the viewer role.</div>}
            <table><thead><tr><th>SKU</th><th>Item</th><th className="num">Qty</th><th className="num">Line</th></tr></thead>
              <tbody>{sel.totals.lines.map((l) => <tr key={l.sku}><td className="mono">{l.sku}</td><td>{l.name}</td><td className="num">{l.quantity}</td><td className="num">{money(l.line_total)}</td></tr>)}</tbody></table>
            <dl className="kv"><dt>Subtotal</dt><dd>{money(sel.totals.subtotal)}</dd><dt>Discount ({sel.totals.discount_pct}%)</dt><dd>−{money(sel.totals.discount)}</dd>
              <dt>Shipping</dt><dd>{money(sel.totals.shipping)}</dd>{Number(sel.totals.hazmat_surcharge) > 0 && <><dt>Hazmat surcharge</dt><dd>{money(sel.totals.hazmat_surcharge)}</dd></>}
              <dt>Tax</dt><dd>{money(sel.totals.tax)}</dd><dt><b>Total</b></dt><dd><b>{money(sel.totals.total)}</b></dd></dl>
            <div className="row wrap"><a className="btn sm" href={ask(`Show me order ${sel.order_number}`)}>Ask Copilot</a>
              {me?.role !== "viewer" && ["pending", "confirmed"].includes(sel.status) && <a className="btn sm danger" href={ask(`Cancel order ${sel.order_number}`)}>Draft cancellation</a>}</div>
          </div>
        </Drawer>)}
    </div>
  );
}
