"use client";
import { useState } from "react";
import { Badge, Empty, ErrorBanner, PageHead, Skeleton, useFetch } from "@/components/ui";
import { api } from "@/lib/api";
import type { EvalResults, Rate } from "@/lib/types";

const NAMES: Record<string, string> = {
  tool_selection_accuracy: "Tool selection accuracy", tool_argument_accuracy: "Tool argument accuracy", retrieval_hit_rate: "Retrieval hit rate",
  citation_recall: "Citation recall", answer_contains_correct: "Answer contains required facts", answer_no_forbidden_content: "Answer free of forbidden content",
  no_citation_when_unanswerable: "No citation when unanswerable", confirmation_flow: "Confirmation flow",
};
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

export default function EvaluationPage() {
  const { data: d, error, loading, reload } = useFetch(() => api<EvalResults>("/api/eval/latest"));
  const [cat, setCat] = useState("all");
  const [onlyFailed, setOnlyFailed] = useState(false);
  const cases = (d?.cases ?? []).filter((c) => (cat === "all" || c.category === cat) && (!onlyFailed || !c.passed));
  const mock = d?.meta.provider === "mock";
  return (
    <div className="content">
      <PageHead title="Evaluation" sub="Measured quality of the real retrieval + agent pipeline on a fixed question set.">
        <button className="btn" onClick={reload}>Reload</button></PageHead>
      {error && error.includes("No evaluation") ? <div className="card"><Empty title="No evaluation results yet">Run <code>python -m evals.run</code> in the backend.</Empty></div> : <ErrorBanner error={error} retry={reload} />}
      {loading && !d ? <div className="card"><Skeleton rows={8} /></div> : d && (<div className="stack">
        {mock && <div className="banner warn"><div><b>Deterministic mock provider.</b> These numbers measure the pipeline (retrieval, tool schemas, guardrails, validation) with a rule-based planner, <b>not</b> a real LLM. Failures marked below are mostly planner limits. Live-provider quality is unverified.</div></div>}
        <div className="grid g4">
          <div className="card stat"><div className="label">Pass rate</div><div className="value">{pct(d.summary.pass_rate)}</div><div className="sub">{d.summary.passed}/{d.summary.cases} cases · all checks must pass</div></div>
          <div className="card stat"><div className="label">Latency p50 / p95</div><div className="value">{d.summary.latency_ms.p50} ms</div><div className="sub">p95 {d.summary.latency_ms.p95} ms (end-to-end, in-process)</div></div>
          <div className="card stat"><div className="label">Tokens / case</div><div className="value">{d.summary.tokens.mean_per_case.toLocaleString()}</div><div className="sub">{d.summary.tokens.input.toLocaleString()} in · {d.summary.tokens.output.toLocaleString()} out</div></div>
          <div className="card stat"><div className="label">Est. cost</div><div className="value">{d.summary.cost_usd.total === null ? "n/a" : `$${d.summary.cost_usd.total.toFixed(4)}`}</div><div className="sub">{mock ? "notional rate, heuristic tokens" : "configured prices"}</div></div>
        </div>
        <div className="grid g2">
          <div className="card"><div className="card-head"><h2>Quality metrics</h2></div><div className="stack" style={{ padding: 18 }}>
            {Object.entries(d.summary.metrics).filter(([k, v]) => v && typeof v === "object" && NAMES[k]).map(([k, v]) => { const r = v as Rate; return (
              <div key={k}><div className="row" style={{ justifyContent: "space-between" }}><span>{NAMES[k]}</span><b>{r.passed}/{r.total} · {pct(r.rate)}</b></div><div className="bar-track"><div className="bar-fill" style={{ width: pct(r.rate), background: r.rate >= 0.9 ? "var(--ok)" : r.rate >= 0.7 ? "var(--brand)" : "var(--bad)" }} /></div></div>); })}</div></div>
          <div className="stack">
            <div className="card"><div className="card-head"><h2>Security invariants</h2></div><dl className="kv card-pad">
              <dt>Injection blocked</dt><dd><Badge tone="ok">{String(d.summary.security.injection_attempts_blocked)}</Badge></dd>
              <dt>False positives</dt><dd>{String(d.summary.security.benign_false_positive_blocked)}</dd>
              <dt>Unauthorized changes</dt><dd><Badge tone={d.summary.security.unauthorized_state_changes === 0 ? "ok" : "bad"}>{String(d.summary.security.unauthorized_state_changes)}</Badge></dd>
              <dt>Cross-tenant leaks</dt><dd><Badge tone={d.summary.security.cross_tenant_leaks === 0 ? "ok" : "bad"}>{String(d.summary.security.cross_tenant_leaks)}</Badge></dd></dl></div>
            <div className="card"><div className="card-head"><h2>Retrieval ablation (Recall@5 / MRR)</h2></div><div className="table-wrap"><table><thead><tr><th>Set</th><th className="num">Semantic</th><th className="num">Keyword</th><th className="num">Hybrid</th></tr></thead>
              <tbody>{Object.entries(d.retrieval_ablation).map(([set, m]) => <tr key={set}><td>{set} <span className="faint">n={m.hybrid.n}</span></td>
                {(["semantic", "keyword", "hybrid"] as const).map((k) => <td key={k} className="num">{m[k]["recall@5"].toFixed(2)} / {m[k].mrr.toFixed(2)}</td>)}</tr>)}</tbody></table></div></div>
          </div>
        </div>
        <div className="card"><div className="card-head"><h2>By category</h2></div><div className="stack" style={{ padding: 18 }}>
          {Object.entries(d.summary.per_category).map(([k, v]) => <div key={k}><div className="row" style={{ justifyContent: "space-between" }}><span>{k.replace(/_/g, " ")}</span><b>{v.passed}/{v.total}</b></div>
            <div className="bar-track"><div className="bar-fill" style={{ width: pct(v.pass_rate), background: v.pass_rate === 1 ? "var(--ok)" : "var(--warn)" }} /></div></div>)}</div></div>
        <div className="card">
          <div className="toolbar"><h2 style={{ marginRight: 8 }}>Cases</h2>
            <select className="input" style={{ maxWidth: 220 }} value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Category"><option value="all">All categories</option>{Object.keys(d.summary.per_category).map((c) => <option key={c}>{c}</option>)}</select>
            <label className="row"><input type="checkbox" checked={onlyFailed} onChange={(e) => setOnlyFailed(e.target.checked)} /> Failures only</label>
            <span className="faint" style={{ marginLeft: "auto" }}>{d.meta.timestamp} · {d.meta.provider}/{d.meta.model} · {d.meta.embedder} · {d.meta.git}</span></div>
          <div className="table-wrap"><table><thead><tr><th>ID</th><th>Question</th><th>Tools</th><th>Result</th><th className="num">ms</th></tr></thead>
            <tbody>{cases.map((c) => <tr key={c.id}><td className="mono">{c.id}</td><td className="wrap">{c.question}<div className="faint">{c.answer.slice(0, 120)}</div></td><td className="mono">{c.tools_called.join(", ") || "—"}</td>
              <td>{c.passed ? <Badge tone="ok">pass</Badge> : <Badge tone="bad">fail: {c.failed_checks.join(", ")}</Badge>}</td><td className="num">{c.latency_ms}</td></tr>)}</tbody></table></div>
        </div>
      </div>)}
    </div>
  );
}
