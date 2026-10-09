"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ActionRow, Change, PendingActionPreview } from "@/lib/types";
import { Badge, Modal, Spinner, useToast } from "./ui";

export function ChangeList({ changes }: { changes: Change[] }) {
  return (
    <div className="diff">
      {changes.map((c) => (<span key={c.field} style={{ display: "contents" }}>
        <span className="muted">{c.field.replace(/_/g, " ")}</span>
        <span>{c.from !== null && c.from !== undefined && <><span className="from">{String(c.from)}</span> → </>}<span className="to">{String(c.to)}</span></span>
      </span>))}
    </div>
  );
}

type State = "pending" | "confirmed" | "rejected" | "failed";

export default function ActionCard({ action, onResolved }: { action: PendingActionPreview | (ActionRow["preview"] & { action_id: string }); onResolved?: (s: State) => void }) {
  const { me } = useAuth();
  const toast = useToast();
  const [state, setState] = useState<State>("pending");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const canConfirm = me?.role === "manager" || me?.role === "admin";

  const resolve = async (kind: "confirm" | "reject") => {
    setBusy(true); setErr(null);
    try {
      await api(`/api/actions/${action.action_id}/${kind}`, { method: "POST" });
      const next: State = kind === "confirm" ? "confirmed" : "rejected";
      setState(next); setOpen(false); onResolved?.(next);
      toast(kind === "confirm" ? "Change applied" : "Draft rejected", kind === "confirm" ? "ok" : "info");
      window.dispatchEvent(new Event("actions-changed"));
    } catch (e) {
      setErr((e as Error).message); setState("failed"); toast((e as Error).message, "bad");
      window.dispatchEvent(new Event("actions-changed"));
    } finally { setBusy(false); }
  };

  return (
    <div className={`action-card ${state === "confirmed" ? "done" : state === "rejected" ? "rejected" : ""}`}>
      <div className="row wrap"><b>{action.title}</b>
        <Badge tone={state === "pending" ? "warn" : state === "confirmed" ? "ok" : state === "failed" ? "bad" : "neutral"}>
          {state === "pending" ? "Awaiting confirmation" : state === "confirmed" ? "Executed" : state === "failed" ? "Failed" : "Rejected"}</Badge></div>
      <ChangeList changes={action.changes} />
      {action.warnings.map((w) => <div key={w} className="faint">Note: {w}</div>)}
      {err && <div className="banner bad" style={{ marginTop: 8 }}>{err}</div>}
      {state === "pending" && (
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn primary sm" disabled={!canConfirm} onClick={() => setOpen(true)} title={canConfirm ? "" : "Only managers and admins can confirm"}>Review &amp; confirm</button>
          <button className="btn sm" disabled={busy} onClick={() => resolve("reject")}>Reject</button>
          {!canConfirm && <span className="faint">Requires manager approval</span>}
        </div>)}
      {open && (
        <Modal title="Confirm this change?" onClose={() => !busy && setOpen(false)} footer={<>
          <button className="btn" disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
          <button className="btn primary" disabled={busy} onClick={() => resolve("confirm")}>{busy ? <Spinner /> : "Confirm and execute"}</button></>}>
          <p className="muted" style={{ marginTop: 0 }}>The assistant only <b>drafted</b> this. Nothing changes in your database until you confirm.</p>
          <b>{action.title}</b><ChangeList changes={action.changes} />
          {action.warnings.map((w) => <div key={w} className="banner warn" style={{ marginTop: 6 }}>{w}</div>)}
          {err && <div className="banner bad" style={{ marginTop: 8 }}>{err}</div>}
        </Modal>)}
    </div>
  );
}
