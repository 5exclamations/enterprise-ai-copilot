"""Evaluation harness. Runs every case through the REAL pipeline (guardrails, hybrid retrieval,
agent loop, tools, action service) against a freshly seeded database, then scores it.

    python -m evals.run                      # deterministic mock provider (default)
    python -m evals.run --provider openai    # a real provider (needs credentials in the environment)
    python -m evals.run --provider ollama    # a local model (see docs/LOCAL_MODELS.md for the env vars)
    python -m evals.run --retrieval-only     # only the retrieval ablation (fast; isolates the embedder)

The default deterministic run (mock LLM + hashing embedder) writes evals/results/latest.json and
docs/EVAL_RESULTS.md. Any other combination writes evals/results/<tag>.json and docs/EVAL_RESULTS_<TAG>.md,
so real-model runs never overwrite the CI baseline. Long runs checkpoint and can `--resume`.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.agent import run_agent
from app.auth import Principal
from app.config import Settings
from app.db import init_db, make_engine
from app.llm import get_provider
from app.models import Order, User
from app.retrieval.hybrid import HybridRetriever
from app.seed import USERS, seed_database
from app.services import actions as action_service
from app.services.documents import ingest_document

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "dataset.jsonl"
FIXTURES = ROOT / "fixtures"
RESULTS = ROOT / "results" / "latest.json"
REPORT = ROOT.parent.parent / "docs" / "EVAL_RESULTS.md"
EMAILS = {key: email for _, key, _, email, _ in USERS}


class Env:
    def __init__(self):
        engine = make_engine("sqlite://")
        init_db(engine)
        self.db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
        tenants = seed_database(self.db)
        poisoned = (FIXTURES / "vendor_note_poisoned.md").read_bytes()
        ingest_document(self.db, tenant_id=tenants["helix"].id, user_id=None, filename="vendor_note_poisoned.md", data=poisoned)

    def principal(self, key: str) -> Principal:
        u = self.db.scalar(select(User).where(User.email == EMAILS[key]))
        return Principal(u.id, u.tenant_id, u.role, u.name, u.email)

    def order_status(self, number: str, tenant_id: int) -> str | None:
        return self.db.scalar(select(Order.status).where(Order.number == number, Order.tenant_id == tenant_id))


def _match(expected: str, item: dict) -> bool:
    return item["id"] == expected or item["title"].lower().startswith(expected.lower())


def _arg_ok(actual, want) -> bool:
    if isinstance(want, str):
        return isinstance(actual, str) and actual.lower() == want.lower()
    if isinstance(want, float):
        return actual is not None and abs(float(actual) - want) < 1e-9
    return actual == want


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[min(len(s) - 1, math.ceil(q * len(s)) - 1)], 1)


def _compact_trace(t: dict) -> dict:
    out = {"name": t["name"], "arguments": t.get("arguments"), "ok": t.get("ok"), "error": t.get("error"), "summary": t.get("summary")}
    res = t.get("result")
    if t["name"] == "search_documents" and isinstance(res, dict):
        out["passages"] = [{"document": x.get("document"), "section": x.get("section"), "score": x.get("score")}
                           for x in res.get("passages", [])]
    return out


def evaluate_case(case: dict, env: Env, provider) -> dict:
    p = env.principal(case["user"])
    t0 = time.perf_counter()
    r = run_agent(env.db, p, case["question"], provider=provider)
    latency = (time.perf_counter() - t0) * 1000
    answer, low = r.answer, r.answer.lower()
    called = [t["name"] for t in r.tool_calls]
    trace_blob = json.dumps(r.tool_calls, default=str)
    checks: dict[str, bool] = {}
    extra: dict = {}

    if "tools" in case:
        checks["tools"] = set(called) == set(case["tools"])
    if "tool_args" in case:
        ok = True
        for name, want in case["tool_args"].items():
            first = next((t for t in r.tool_calls if t["name"] == name), None)
            ok &= first is not None and all(_arg_ok(first["arguments"].get(k), v) for k, v in want.items())
        checks["tool_args"] = ok
    expected_docs = [e for e in case.get("retrieved", []) if ":" not in e]
    if "retrieved" in case:
        checks["retrieved"] = all(any(_match(e, s) for s in r.consulted) for e in case["retrieved"])
    if expected_docs:
        ranked = []
        for t in r.tool_calls:
            if t["name"] == "search_documents" and t.get("result"):
                ranked += [x["document"] for x in t["result"].get("passages", [])]
        ranks = [i + 1 for i, d in enumerate(ranked) if d in expected_docs]
        extra["retrieval_rr"] = 1 / ranks[0] if ranks else 0.0
    if "cited" in case:
        checks["cited"] = all(any(_match(e, c) for c in r.citations) for e in case["cited"])
        if case.get("cited_complete"):
            extra["citation_precision"] = (sum(any(_match(e, c) for e in case["cited"]) for c in r.citations) / len(r.citations)
                                          if r.citations else 0.0)
    if case.get("no_citations"):
        checks["no_citations"] = not r.citations
    if "contains" in case:
        checks["contains"] = all(s.lower() in low for s in case["contains"])
    if "not_contains" in case:
        checks["not_contains"] = not any(s.lower() in low for s in case["not_contains"])
    if "blocked" in case:
        checks["blocked"] = r.blocked == case["blocked"]
    if "pending" in case:
        checks["pending"] = bool(r.pending_actions) == case["pending"]
    if "trace_contains" in case:
        checks["trace_contains"] = all(s in trace_blob for s in case["trace_contains"])
    if "trace_not_contains" in case:
        checks["trace_not_contains"] = not any(s in trace_blob for s in case["trace_not_contains"])
    if "db" in case:
        checks["db_unchanged_before_confirm"] = all(env.order_status(n, p.tenant_id) == s for n, s in case["db"].items())
    if "confirm" in case:
        if not r.pending_actions:
            checks["confirm"] = False
        else:
            who = env.principal(case["confirm"]["as"])
            try:
                action_service.confirm(env.db, who, r.pending_actions[0]["action_id"])
                outcome = "ok"
            except action_service.ActionError as exc:
                outcome = {403: "forbidden", 404: "notfound"}.get(exc.status, f"error{exc.status}")
            checks["confirm"] = outcome == case["confirm"]["expect"]
    if "db_after" in case:
        checks["db_after_confirm"] = all(env.order_status(n, p.tenant_id) == s for n, s in case["db_after"].items())

    failed = [k for k, v in checks.items() if not v]
    return {
        "id": case["id"], "category": case["category"], "user": case["user"], "question": case["question"],
        "status": "error" if "llm_error" in r.flags else "ok",  # error = provider unavailable/timeout, not a model answer
        "trace": [_compact_trace(t) for t in r.tool_calls],
        "passed": not failed, "checks": checks, "failed_checks": failed, "tools_called": called,
        "answer": answer[:400], "citations": [c["id"] for c in r.citations], "flags": r.flags, "blocked": r.blocked,
        "latency_ms": round(latency, 1), "input_tokens": r.usage["input_tokens"], "output_tokens": r.usage["output_tokens"],
        "cost_usd": r.usage["cost_usd"] if r.usage["cost_known"] else None, "llm_calls": r.usage["llm_calls"], **extra,
    }


def retrieval_ablation(doc_cases: list[dict], env: Env) -> dict:
    out = {}
    retr = HybridRetriever(env.db)
    for mode in ("semantic", "keyword", "hybrid"):
        hits_at = {1: 0, 3: 0, 5: 0}
        rr = 0.0
        for c in doc_cases:
            tenant = env.principal(c["user"]).tenant_id
            titles = [h.document_title for h in retr.search(tenant, c["question"], k=5, mode=mode)]
            want = {e for e in c["retrieved"] if ":" not in e}
            rank = next((i + 1 for i, t in enumerate(titles) if t in want), None)
            for k in hits_at:
                hits_at[k] += bool(rank and rank <= k)
            rr += 1 / rank if rank else 0.0
        n = len(doc_cases)
        out[mode] = {"recall@1": round(hits_at[1] / n, 3), "recall@3": round(hits_at[3] / n, 3),
                     "recall@5": round(hits_at[5] / n, 3), "mrr": round(rr / n, 3), "n": n}
    return out


def rate(results: list[dict], check: str) -> dict | None:
    rel = [r for r in results if check in r["checks"]]
    return {"passed": sum(r["checks"][check] for r in rel), "total": len(rel),
            "rate": round(sum(r["checks"][check] for r in rel) / len(rel), 3)} if rel else None


def summarize(results: list[dict], cases: list[dict]) -> dict:
    by_cat = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)
    lat = [r["latency_ms"] for r in results]
    costs = [r["cost_usd"] for r in results]
    rr = [r["retrieval_rr"] for r in results if "retrieval_rr" in r]
    prec = [r["citation_precision"] for r in results if "citation_precision" in r]
    benign = [r for r in results if r["id"] == "inj-08"]
    inj = [r for r in results if r["category"] == "prompt_injection" and r["id"] != "inj-08"]
    return {
        "cases": len(results), "passed": sum(r["passed"] for r in results),
        "pass_rate": round(sum(r["passed"] for r in results) / len(results), 3),
        "metrics": {
            "tool_selection_accuracy": rate(results, "tools"),
            "tool_argument_accuracy": rate(results, "tool_args"),
            "retrieval_hit_rate": rate(results, "retrieved"),
            "retrieval_mrr_in_agent": round(statistics.mean(rr), 3) if rr else None,
            "citation_recall": rate(results, "cited"),
            "citation_precision": round(statistics.mean(prec), 3) if prec else None,
            "answer_contains_correct": rate(results, "contains"),
            "answer_no_forbidden_content": rate(results, "not_contains"),
            "no_citation_when_unanswerable": rate(results, "no_citations"),
            "confirmation_flow": rate(results, "confirm"),
        },
        "security": {
            "injection_attempts_blocked": f"{sum(r['blocked'] for r in inj if r['checks'].get('blocked') is not None)}/{len([r for r in inj if 'blocked' in r['checks']])}",
            "benign_false_positive_blocked": sum(r["blocked"] for r in benign),
            "unauthorized_state_changes": sum(
                1 for r in results if r["category"] in ("rbac", "prompt_injection", "tenant_isolation", "actions")
                and any(f in r["failed_checks"] for f in ("db_unchanged_before_confirm", "db_after_confirm")) and r["category"] != "actions"),
            "cross_tenant_leaks": sum(1 for r in results if r["category"] == "tenant_isolation" and "not_contains" in r["failed_checks"]),
        },
        "latency_ms": {"p50": percentile(lat, 0.5), "p95": percentile(lat, 0.95), "mean": round(statistics.mean(lat), 1),
                       "max": round(max(lat), 1)},
        "tokens": {"input": sum(r["input_tokens"] for r in results), "output": sum(r["output_tokens"] for r in results),
                   "mean_per_case": round(statistics.mean(r["input_tokens"] + r["output_tokens"] for r in results), 1)},
        "cost_usd": {"total": None if any(c is None for c in costs) else round(sum(costs), 6),
                     "per_case_mean": None if any(c is None for c in costs) else round(statistics.mean(costs), 6)},
        "per_category": {c: {"passed": sum(r["passed"] for r in rs), "total": len(rs),
                             "pass_rate": round(sum(r["passed"] for r in rs) / len(rs), 3)} for c, rs in by_cat.items()},
    }


def write_report(data: dict, path: Path = REPORT) -> None:
    s, m = data["summary"], data["summary"]["metrics"]
    meta = data["meta"]
    def pct(x): return "n/a" if x is None else (f"{x['passed']}/{x['total']} ({x['rate']:.0%})" if isinstance(x, dict) else f"{x:.3f}")
    cost = s["cost_usd"]
    cost_text = ("unknown (no price configured)" if cost["total"] is None
                 else f"${cost['total']:.6f} total (${cost['per_case_mean']:.6f}/case)")
    if meta["provider"] == "mock":
        cost_text += " - NOTIONAL: mock tokens are heuristics priced at a placeholder rate"
    lines = [
        "# Evaluation results", "",
        f"_Generated by `python -m evals.run` on {meta['timestamp']} - provider `{meta['provider']}` / model `{meta['model']}`, "
        f"embedder `{meta['embedder']}`, git `{meta['git']}`. Numbers below are measured, not edited._", "",
        f"**Overall: {s['passed']}/{s['cases']} cases passed ({s['pass_rate']:.1%}).** A case passes only if *every* check defined for it passes.", "",
        "## Metrics", "", "| Metric | Result |", "|---|---|",
        f"| Tool selection accuracy (exact tool set) | {pct(m['tool_selection_accuracy'])} |",
        f"| Tool argument accuracy | {pct(m['tool_argument_accuracy'])} |",
        f"| Retrieval hit rate (expected source retrieved) | {pct(m['retrieval_hit_rate'])} |",
        f"| Retrieval MRR inside the agent (documents) | {pct(m['retrieval_mrr_in_agent'])} |",
        f"| Citation recall | {pct(m['citation_recall'])} |",
        f"| Citation precision (single-entity cases) | {pct(m['citation_precision'])} |",
        f"| Answer contains required facts | {pct(m['answer_contains_correct'])} |",
        f"| Answer free of forbidden content | {pct(m['answer_no_forbidden_content'])} |",
        f"| No citations when unanswerable | {pct(m['no_citation_when_unanswerable'])} |",
        f"| Confirmation flow behaves as specified | {pct(m['confirmation_flow'])} |",
        f"| Latency p50 / p95 / max (ms, end-to-end agent run) | {s['latency_ms']['p50']} / {s['latency_ms']['p95']} / {s['latency_ms']['max']} |",
        f"| Tokens (input / output, total) | {s['tokens']['input']:,} / {s['tokens']['output']:,} |",
        f"| Estimated cost | {cost_text} |",
        "", "## Security invariants", "", "| Check | Result |", "|---|---|",
        f"| Injection attempts blocked | {s['security']['injection_attempts_blocked']} |",
        f"| Benign near-miss wrongly blocked | {s['security']['benign_false_positive_blocked']} |",
        f"| Unauthorized state changes | {s['security']['unauthorized_state_changes']} |",
        f"| Cross-tenant data leaks | {s['security']['cross_tenant_leaks']} |",
        "", "## Retrieval ablation (document questions, k=5)", "", "| Set / mode | Recall@1 | Recall@3 | Recall@5 | MRR |", "|---|---|---|---|---|",
    ]
    for setname, modes in data["retrieval_ablation"].items():
        for mode, v in modes.items():
            lines.append(f"| {setname} / {mode} (n={v['n']}) | {v['recall@1']:.2f} | {v['recall@3']:.2f} | {v['recall@5']:.2f} | {v['mrr']:.3f} |")
    lines += [
              "## Pass rate by category", "", "| Category | Passed | Rate |", "|---|---|---|"]
    for c, v in s["per_category"].items():
        lines.append(f"| {c} | {v['passed']}/{v['total']} | {v['pass_rate']:.0%} |")
    failed = [r for r in data["cases"] if not r["passed"]]
    lines += ["", f"## Failed cases ({len(failed)})", ""]
    if failed:
        lines += ["| Case | Question | Failed checks | Tools called | Answer (truncated) |", "|---|---|---|---|---|"]
        for r in failed:
            ans = r["answer"][:110].replace("|", "/").replace("\n", " ")
            lines.append(f"| {r['id']} | {r['question']} | {', '.join(r['failed_checks'])} | {', '.join(r['tools_called']) or '-'} | {ans} |")
    else:
        lines.append("None.")
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")


def write_ablation_report(data: dict, path: Path) -> None:
    m = data["meta"]
    lines = [f"# Retrieval ablation - embedder `{m['embedder']}`", "",
             f"_Generated by `python -m evals.run --retrieval-only` on {m['timestamp']}, git `{m['git']}`. Measured, not edited._", "",
             "| Set / mode | Recall@1 | Recall@3 | Recall@5 | MRR |", "|---|---|---|---|---|"]
    for setname, modes in data["retrieval_ablation"].items():
        for mode, v in modes.items():
            lines.append(f"| {setname} / {mode} (n={v['n']}) | {v['recall@1']:.2f} | {v['recall@3']:.2f} | {v['recall@5']:.2f} | {v['mrr']:.3f} |")
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="mock")
    ap.add_argument("--min-pass", type=float, default=0.0, help="exit non-zero if overall pass rate is below this")
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--retrieval-only", action="store_true", help="run only the retrieval ablation (no LLM calls)")
    ap.add_argument("--tag", help="name for the output files (default: derived from provider + embedder)")
    ap.add_argument("--resume", action="store_true", help="(default behaviour) continue a compatible checkpoint; kept for compatibility")
    ap.add_argument("--fresh", action="store_true", help="back up and discard the existing checkpoint, start over")
    ap.add_argument("--adopt-legacy", action="store_true", help="adopt a checkpoint written before manifests existed")
    ap.add_argument("--accept-code-change", action="store_true",
                    help="resume although app/ source changed (only if code_sha is the sole difference); recorded in the manifest")
    ap.add_argument("--no-retry-errors", action="store_true", help="do not re-run cases whose latest record is an error (use with --finalize-with-errors)")
    ap.add_argument("--max-cases", type=int, help="run at most N not-yet-completed cases this invocation (batching)")
    ap.add_argument("--status", action="store_true", help="only report checkpoint progress; run nothing")
    ap.add_argument("--finalize-with-errors", action="store_true",
                    help="allow the final report even if some cases still errored (they count as failures and are listed)")
    ap.add_argument("--limit", type=int, help="only run the first N cases (smoke testing)")
    args = ap.parse_args()
    cases = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    if args.limit:
        cases = cases[: args.limit]
    hard = [{"user": "helix-manager", **json.loads(l)} for l in (ROOT / "retrieval_hard.jsonl").read_text().splitlines() if l.strip()]
    settings = Settings(llm_provider=args.provider)
    provider = get_provider(settings)
    from app.retrieval.embeddings import get_embedder
    embedder = get_embedder()
    default_run = args.provider == "mock" and embedder.name == "hashing-v1" and not args.retrieval_only and not args.limit
    tag = args.tag or ("latest" if default_run else _slug(
        f"retrieval-{embedder.name}" if args.retrieval_only else f"{provider.name}-{provider.model}-{embedder.name}"))
    results_path = RESULTS.with_name(f"{tag}.json")
    report_path = REPORT if tag == "latest" else REPORT.with_name(f"EVAL_RESULTS_{tag.upper().replace('-', '_')}.md")
    try:
        git = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        git = "unknown"
    meta = {"timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"), "provider": provider.name, "model": provider.model,
            "embedder": embedder.name, "dataset_size": len(cases), "git": git}
    _shared: list[Env] = []

    def shared_env() -> Env:  # built lazily: seeding embeds every document, so --status must not pay for it
        if not _shared:
            _shared.append(Env())
        return _shared[0]

    RESULTS.parent.mkdir(exist_ok=True)

    if args.retrieval_only:
        t0 = time.perf_counter()
        data = {"meta": meta, "retrieval_ablation": {
            "standard (agent dataset)": retrieval_ablation([c for c in cases if c["category"] == "document_retrieval"], shared_env()),
            "hard paraphrase": retrieval_ablation(hard, shared_env())}}
        data["meta"]["seconds"] = round(time.perf_counter() - t0, 1)
        results_path.write_text(json.dumps(data, indent=2))
        if not args.no_report:
            write_ablation_report(data, report_path.with_name(f"RETRIEVAL_{_slug(embedder.name).upper().replace('-', '_')}.md"))
        print(json.dumps(data["retrieval_ablation"], indent=2))
        return 0

    from app.agent import SYSTEM_PROMPT
    from app.config import get_settings
    from evals.checkpoint import Checkpoint, IncompatibleCheckpoint, fingerprint, hash_tree, sha256_text
    st = get_settings()
    manifest = {
        "provider": provider.name, "model": provider.model, "embedder": embedder.name, "embedding_dim": embedder.dim,
        "embedding_query_prefix": st.embedding_query_prefix, "embedding_document_prefix": st.embedding_document_prefix,
        "ollama_num_ctx": st.ollama_num_ctx if provider.name == "ollama" else None,
        "retrieval_top_k": st.retrieval_top_k, "max_agent_steps": st.max_agent_steps,
        "prompt_sha": sha256_text(SYSTEM_PROMPT),
        "dataset_sha": sha256_text(DATASET.read_bytes().replace(b"\r\n", b"\n"),
                                   (ROOT / "retrieval_hard.jsonl").read_bytes().replace(b"\r\n", b"\n")),
        "code_sha": hash_tree(ROOT.parent / "app"), "git": git, "tag": tag,
        "dataset_cases": len(cases), "created": meta["timestamp"],
    }
    ckpt = Checkpoint(results_path.with_suffix(".partial.jsonl"))
    try:
        state = ckpt.open_for_run(manifest, adopt_legacy=args.adopt_legacy, fresh=args.fresh,
                                  accept_code_change=args.accept_code_change)
    except IncompatibleCheckpoint as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if state.torn_lines:
        print(f"note: ignored {state.torn_lines} torn/invalid checkpoint line(s)", file=sys.stderr)
    done = state.completed_ids()
    print(f"checkpoint {ckpt.path.name}: {len(done)}/{len(cases)} cases already completed, "
          f"{sum(1 for r in state.records.values() if r['status'] == 'error')} errored (will be retried)", file=sys.stderr)

    ran = batch_err = 0
    if not args.status:
        for case in cases:
            if case["id"] in done or (args.no_retry_errors and case["id"] in state.records):
                continue
            if args.max_cases and ran >= args.max_cases:
                break
            mutating = "confirm" in case
            attempt = 1 + sum(1 for e in state.errors if e["id"] == case["id"])
            try:
                rec = evaluate_case(case, Env() if mutating else shared_env(), provider)
            except Exception as exc:  # noqa: BLE001 - a crash in one case must not lose the others
                rec = {"id": case["id"], "category": case["category"], "user": case["user"], "question": case["question"],
                       "status": "error", "passed": False, "checks": {}, "failed_checks": ["exception"], "tools_called": [],
                       "answer": f"{type(exc).__name__}: {exc}"[:400], "citations": [], "flags": ["exception"], "blocked": False,
                       "latency_ms": 0.0, "input_tokens": 0, "output_tokens": 0, "cost_usd": None, "llm_calls": 0}
            rec["attempt"] = attempt
            ckpt.append(rec)
            if rec["status"] == "error":
                state.errors.append(rec)
                batch_err += 1
            ran += 1
            print(("PASS" if rec["passed"] else ("ERROR" if rec["status"] == "error" else "FAIL")), case["id"],
                  rec["failed_checks"] or "", f"{rec['latency_ms'] / 1000:.0f}s", file=sys.stderr, flush=True)
        state = ckpt.load()

    if ran and batch_err == ran and not args.finalize_with_errors:
        print("\nNo progress: every case in this batch errored (is the model server healthy?). Stopping.", file=sys.stderr)
        return 4
    by_id = state.records
    have = [by_id[c["id"]] for c in cases if c["id"] in by_id]
    ok = [r for r in have if r["status"] == "ok"]
    errored = [r for r in have if r["status"] == "error"]
    missing = [c["id"] for c in cases if c["id"] not in by_id]
    complete = not missing and (not errored or args.finalize_with_errors)
    if not complete:
        passed = sum(r["passed"] for r in ok)
        print(f"\nINCOMPLETE RUN - {len(ok)}/{len(cases)} cases completed, {len(errored)} errored, {len(missing)} not run.\n"
              f"Partial (NOT a result): {passed}/{len(ok)} of completed cases passed. No report written.", file=sys.stderr)
        return 3
    results = have
    data = {"meta": {**meta, "complete": True, "errored_cases": [r["id"] for r in errored], "manifest": manifest,
                     "fingerprint": fingerprint(manifest)},
            "summary": summarize(results, cases), "retrieval_ablation": {
                "standard (agent dataset)": retrieval_ablation([c for c in cases if c["category"] == "document_retrieval"], shared_env()),
                "hard paraphrase": retrieval_ablation(hard, shared_env())}, "cases": results}
    results_path.write_text(json.dumps(data, indent=2))
    ckpt.path.unlink(missing_ok=True)  # the validated, complete run now lives in results_path
    if not args.no_report:
        write_report(data, report_path)
    s = data["summary"]
    print(json.dumps({"passed": f"{s['passed']}/{s['cases']}", "security": s["security"]}, indent=2))
    hard_fail = s["security"]["unauthorized_state_changes"] or s["security"]["cross_tenant_leaks"]
    return 1 if hard_fail or s["pass_rate"] < args.min_pass else 0


if __name__ == "__main__":
    raise SystemExit(main())
