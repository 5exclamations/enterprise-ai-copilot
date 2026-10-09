"use client";
import { useRef, useState } from "react";
import { Badge, Drawer, Empty, ErrorBanner, Modal, PageHead, Skeleton, Spinner, useFetch, useToast } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { DocDetail, DocSummary, IngestInfo, SearchHit } from "@/lib/types";

const CATS = ["", "policy", "sop", "catalog", "legal", "support", "other"];

export default function DocumentsPage() {
  const { me } = useAuth();
  const toast = useToast();
  const canEdit = me?.role !== "viewer";
  const { data, error, loading, reload } = useFetch(() => api<DocSummary[]>("/api/documents"));
  const [over, setOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const [detail, setDetail] = useState<DocDetail | null>(null);
  const [del, setDel] = useState<DocSummary | null>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const replaceRef = useRef<HTMLInputElement>(null);
  const replaceId = useRef<number | null>(null);

  const send = async (file: File, id?: number) => {
    setUploading(true); setUploadErr(null);
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await api<DocSummary & { ingestion: IngestInfo }>(id ? `/api/documents/${id}` : "/api/documents", { method: id ? "PUT" : "POST", body: fd });
      const i = r.ingestion;
      toast(i.unchanged ? "No changes detected" : `${r.title}: ${i.chunks_total} chunks (${i.embeddings_reused} embeddings reused)${i.chunks_quarantined ? `, ${i.chunks_quarantined} quarantined` : ""}`, "ok");
      reload();
    } catch (e) { setUploadErr((e as Error).message); } finally { setUploading(false); }
  };
  const open = async (d: DocSummary) => { try { setDetail(await api<DocDetail>(`/api/documents/${d.id}`)); } catch (e) { toast((e as Error).message, "bad"); } };
  const search = async (e: React.FormEvent) => {
    e.preventDefault(); if (q.trim().length < 2) return;
    setSearching(true);
    try { setHits(await api<SearchHit[]>("/api/documents/search", { method: "POST", json: { query: q, k: 5 } })); } catch (er) { toast((er as Error).message, "bad"); } finally { setSearching(false); }
  };
  const remove = async () => {
    if (!del) return;
    try { await api(`/api/documents/${del.id}`, { method: "DELETE" }); toast("Document deleted", "ok"); setDel(null); reload(); } catch (e) { toast((e as Error).message, "bad"); }
  };

  return (
    <div className="content">
      <PageHead title="Documents" sub="Policies, SOPs and catalogs the Copilot can search and cite. PDF, Markdown and text.">
        <button className="btn primary" disabled={!canEdit || uploading} onClick={() => fileRef.current?.click()}>{uploading ? <Spinner /> : "Upload document"}</button>
      </PageHead>
      <input ref={fileRef} type="file" accept=".pdf,.md,.txt,.markdown" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) send(f); e.target.value = ""; }} />
      <input ref={replaceRef} type="file" accept=".pdf,.md,.txt,.markdown" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f && replaceId.current) send(f, replaceId.current); e.target.value = ""; }} />
      <div className="stack">
        {canEdit ? (
          <div className={`drop ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files?.[0]; if (f) send(f); }}>
            {uploading ? <><Spinner /> Parsing, chunking, embedding…</> : <>Drag &amp; drop a file here, or use <b>Upload document</b>. Max 10&nbsp;MB.</>}
          </div>) : <div className="banner info">Your role (viewer) can read and search documents but not upload or delete them.</div>}
        <ErrorBanner error={uploadErr} />
        <ErrorBanner error={error} retry={reload} />
        <div className="card table-wrap">
          {loading ? <Skeleton /> : !data?.length ? <Empty title="No documents yet">Upload a policy to get started.</Empty> : (
            <table><thead><tr><th>Title</th><th>Category</th><th>Version</th><th className="num">Chunks</th><th>Effective</th><th>Updated</th><th /></tr></thead>
              <tbody>{data.map((d) => (
                <tr key={d.id} className="clickable" onClick={() => open(d)}>
                  <td className="wrap"><b>{d.title}</b><div className="faint">{d.filename}</div></td><td><Badge tone="brand">{d.category}</Badge></td><td>v{d.version}</td>
                  <td className="num">{d.chunks}{d.quarantined_chunks > 0 && <> <Badge tone="bad">{d.quarantined_chunks} quarantined</Badge></>}</td>
                  <td>{String(d.metadata.effective_date ?? "—")}</td><td className="muted">{fmtDate(d.updated_at)}</td>
                  <td onClick={(e) => e.stopPropagation()} style={{ whiteSpace: "nowrap" }}>
                    <button className="btn sm" disabled={!canEdit} onClick={() => { replaceId.current = d.id; replaceRef.current?.click(); }}>Replace</button>{" "}
                    <button className="btn sm danger" disabled={!canEdit} onClick={() => setDel(d)}>Delete</button></td>
                </tr>))}</tbody></table>)}
        </div>

        <div className="card">
          <div className="card-head"><h2>Retrieval inspector</h2><span className="faint">See how hybrid search ranks passages</span></div>
          <form className="toolbar" onSubmit={search}>
            <input className="input" style={{ flex: 1, minWidth: 220 }} placeholder="e.g. how long to return something?" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search query" />
            <button className="btn primary" disabled={searching || q.trim().length < 2}>{searching ? <Spinner /> : "Search"}</button>
          </form>
          {hits && (hits.length === 0 ? <Empty title="No relevant passages">Nothing cleared the relevance threshold, so the assistant would say it could not find an answer.</Empty> : (
            <div className="card-pad stack">{hits.map((h, i) => (
              <div key={h.source_id} className="src"><div className="row wrap"><b>{i + 1}. {h.document}</b>{h.section && <span className="muted">{h.section}</span>}
                <Badge tone="brand">score {h.score.toFixed(4)}</Badge>
                <Badge tone={h.semantic_rank ? "info" : "neutral"}>semantic {h.semantic_rank ? `#${h.semantic_rank} (${h.semantic_score?.toFixed(2)})` : "—"}</Badge>
                <Badge tone={h.keyword_rank ? "ok" : "neutral"}>keyword {h.keyword_rank ? `#${h.keyword_rank}` : "—"}</Badge></div>
                <div className="muted" style={{ marginTop: 4 }}>{h.content.slice(0, 280)}{h.content.length > 280 ? "…" : ""}</div></div>))}</div>))}
        </div>
      </div>

      {detail && (
        <Drawer title={detail.title} sub={`${detail.filename} · v${detail.version}`} onClose={() => setDetail(null)}>
          <div className="stack">
            <dl className="kv"><dt>Category</dt><dd>{detail.category}</dd><dt>Chunks</dt><dd>{detail.chunks}</dd><dt>Effective date</dt><dd>{String(detail.metadata.effective_date ?? "—")}</dd>
              <dt>Words</dt><dd>{String(detail.metadata.word_count)}</dd><dt>SKUs mentioned</dt><dd>{(detail.metadata.mentioned_skus as string[] | undefined)?.join(", ") || "—"}</dd></dl>
            <h3>Chunks</h3>
            {detail.chunk_list.map((c) => (
              <div key={c.index} className="src" style={c.flagged ? { borderLeftColor: "var(--bad)" } : {}}>
                <div className="row wrap"><span className="faint">#{c.index}</span>{c.section && <span className="muted">{c.section}</span>}{c.page && <Badge>page {c.page}</Badge>}<Badge>{c.tokens} tok</Badge>
                  {c.flagged && <Badge tone="bad">quarantined: {c.flag_reason}</Badge>}</div>
                <div style={{ whiteSpace: "pre-wrap", marginTop: 4 }}>{c.content}</div></div>))}
          </div>
        </Drawer>)}
      {del && <Modal title="Delete document?" onClose={() => setDel(null)} footer={<><button className="btn" onClick={() => setDel(null)}>Cancel</button><button className="btn danger" onClick={remove}>Delete</button></>}>
        <p style={{ marginTop: 0 }}><b>{del.title}</b> and its {del.chunks} chunks will be removed from search. This cannot be undone.</p></Modal>}
    </div>
  );
}
