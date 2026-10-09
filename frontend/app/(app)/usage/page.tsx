"use client";
import { BarChart, Empty, ErrorBanner, PageHead, Skeleton, useFetch } from "@/components/ui";
import { api } from "@/lib/api";
import type { UsageSummary } from "@/lib/types";

function Bars({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map((e) => e[1]));
  if (!entries.length) return <Empty title="No data yet" />;
  return <div className="stack" style={{ padding: 18 }}>{entries.map(([k, v]) => (
    <div key={k}><div className="row" style={{ justifyContent: "space-between" }}><span className="mono">{k.replace(/_/g, " ")}</span><b>{v}</b></div><div className="bar-track"><div className="bar-fill" style={{ width: `${(v / max) * 100}%` }} /></div></div>))}</div>;
}

export default function UsagePage() {
  const { data: u, error, loading, reload } = useFetch(() => api<UsageSummary>("/api/usage/summary?days=14"));
  const tokens = u ? u.input_tokens + u.output_tokens : 0;
  return (
    <div className="content">
      <PageHead title="Usage" sub="LLM consumption, tool activity and guardrail events for your organization (last 14 days)."><button className="btn" onClick={reload}>Refresh</button></PageHead>
      <ErrorBanner error={error} retry={reload} />
      {loading && !u ? <div className="card"><Skeleton rows={6} /></div> : u && (<div className="stack">
        <div className="grid g4">
          <div className="card stat"><div className="label">LLM calls</div><div className="value">{u.llm_calls}</div><div className="sub">{u.corpus.documents} docs · {u.corpus.chunks} chunks indexed</div></div>
          <div className="card stat"><div className="label">Tokens</div><div className="value">{tokens.toLocaleString()}</div><div className="sub">{u.input_tokens.toLocaleString()} in · {u.output_tokens.toLocaleString()} out</div></div>
          <div className="card stat"><div className="label">Estimated cost</div><div className="value">${u.cost_usd.toFixed(4)}</div><div className="sub">{u.cost_unknown_calls ? `${u.cost_unknown_calls} calls with no price configured` : "mock provider uses a notional rate"}</div></div>
          <div className="card stat"><div className="label">LLM latency</div><div className="value">{u.llm_latency_ms.p50} ms</div><div className="sub">p50 · p95 {u.llm_latency_ms.p95} ms</div></div>
        </div>
        <div className="grid g2">
          <div className="card"><div className="card-head"><h2>LLM calls per day</h2></div><div className="card-pad">{u.by_day.length ? <><BarChart data={u.by_day.map((d) => ({ label: d.day, value: d.calls }))} />
            <div className="row" style={{ justifyContent: "space-between" }}><span className="faint">{u.by_day[0].day}</span><span className="faint">{u.by_day.at(-1)?.day}</span></div></> : <Empty title="No activity yet">Ask the Copilot a question.</Empty>}</div></div>
          <div className="card"><div className="card-head"><h2>By model</h2></div><div className="table-wrap">{Object.keys(u.by_model).length ? <table><thead><tr><th>Provider / model</th><th className="num">Calls</th><th className="num">Tokens</th><th className="num">Cost</th></tr></thead>
            <tbody>{Object.entries(u.by_model).map(([k, m]) => <tr key={k}><td className="mono">{k}</td><td className="num">{m.calls}</td><td className="num">{(m.input_tokens + m.output_tokens).toLocaleString()}</td><td className="num">${m.cost_usd.toFixed(4)}</td></tr>)}</tbody></table> : <Empty title="No data yet" />}</div></div>
        </div>
        <div className="grid g3">
          <div className="card"><div className="card-head"><h2>Tool calls</h2></div><Bars data={u.tool_calls} /></div>
          <div className="card"><div className="card-head"><h2>Guardrail events</h2></div><Bars data={u.guardrail_events} /></div>
          <div className="card"><div className="card-head"><h2>Action approvals</h2></div><Bars data={u.actions} /></div>
        </div>
      </div>)}
    </div>
  );
}
