"use client";
import { useState } from "react";
import ActionCard, { ChangeList } from "@/components/ActionCard";
import { Badge, Empty, ErrorBanner, label, PageHead, Skeleton, statusTone, useFetch } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";
import type { ActionRow } from "@/lib/types";

export default function ActionsPage() {
  const { data, error, loading, reload } = useFetch(() => api<ActionRow[]>("/api/actions"));
  const [tab, setTab] = useState<"pending" | "history">("pending");
  const pending = (data ?? []).filter((a) => a.status === "pending");
  const history = (data ?? []).filter((a) => a.status !== "pending");
  return (
    <div className="content">
      <PageHead title="Approvals" sub="State changes drafted by the Copilot. Nothing is executed until a manager confirms it.">
        <button className="btn" onClick={reload}>Refresh</button></PageHead>
      <div className="chips" style={{ marginBottom: 14 }}>
        <button className={`chip ${tab === "pending" ? "on" : ""}`} onClick={() => setTab("pending")}>Pending ({pending.length})</button>
        <button className={`chip ${tab === "history" ? "on" : ""}`} onClick={() => setTab("history")}>History ({history.length})</button></div>
      <ErrorBanner error={error} retry={reload} />
      {loading ? <div className="card"><Skeleton /></div> : tab === "pending" ? (
        !pending.length ? <div className="card"><Empty title="Nothing waiting for approval">Ask the Copilot to draft a change, e.g. “Cancel order SO-10004”.</Empty></div> :
        <div className="stack">{pending.map((a) => <div key={a.id}>
          <div className="faint" style={{ marginBottom: 4 }}>Drafted {fmtDate(a.created_at)}{a.reason ? ` · “${a.reason}”` : ""}</div>
          <ActionCard action={{ action_id: a.id, ...a.preview }} onResolved={() => setTimeout(reload, 400)} /></div>)}</div>
      ) : !history.length ? <div className="card"><Empty title="No history yet" /></div> : (
        <div className="card table-wrap"><table><thead><tr><th>Action</th><th>Changes</th><th>Status</th><th>Resolved</th></tr></thead>
          <tbody>{history.map((a) => <tr key={a.id}><td className="wrap"><b>{a.preview.title}</b><div className="faint mono">{a.id.slice(0, 8)}</div></td><td><ChangeList changes={a.preview.changes} />
            {a.status === "failed" && <div className="faint">{String((a.result as { error?: string } | null)?.error ?? "")}</div>}</td>
            <td><Badge tone={statusTone(a.status)}>{label(a.status)}</Badge></td><td className="muted">{a.resolved_at ? fmtDate(a.resolved_at) : "—"}</td></tr>)}</tbody></table></div>)}
    </div>
  );
}
