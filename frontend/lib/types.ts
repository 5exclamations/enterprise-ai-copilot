export type Role = "viewer" | "manager" | "admin";

export interface Me { user_id: number; name: string; email: string; role: Role; tenant: string }
export interface DemoUser { label: string; name: string; email: string; role: Role; tenant: string; api_key: string }

export interface Source { id: string; type: string; title: string; snippet: string; meta: Record<string, unknown> }
export interface ToolTrace {
  id: string; name: string; arguments: Record<string, unknown>; ok: boolean;
  summary: string | null; error: string | null; duration_ms: number; result: Record<string, unknown> | null;
}
export interface Change { field: string; from: unknown; to: unknown }
export interface PendingActionPreview {
  action_id: string; action_type: string; title: string; changes: Change[]; warnings: string[];
}
export interface ChatUsage {
  input_tokens: number; output_tokens: number; cost_usd: number; cost_known: boolean; llm_calls: number;
  provider: string; model: string; estimated_tokens: boolean;
}
export interface ChatResponse {
  conversation_id: string; answer: string; citations: Source[]; consulted: Source[]; tool_calls: ToolTrace[];
  pending_actions: PendingActionPreview[]; usage: ChatUsage; latency_ms: number; flags: string[];
  blocked: boolean; confidence: "high" | "medium" | "low";
}

export interface DocSummary {
  id: number; title: string; filename: string; category: string; version: number; content_type: string;
  chunks: number; quarantined_chunks: number; metadata: Record<string, unknown>; created_at: string; updated_at: string;
}
export interface DocDetail extends DocSummary {
  chunk_list: { index: number; section: string | null; page: number | null; tokens: number; flagged: boolean; flag_reason: string | null; content: string }[];
}
export interface IngestInfo { chunks_total: number; embeddings_computed: number; embeddings_reused: number; chunks_quarantined: number; unchanged: boolean }
export interface SearchHit {
  source_id: string; document: string; category: string; section: string | null; page: number | null; content: string;
  score: number; semantic_score: number | null; semantic_rank: number | null; keyword_rank: number | null;
}

export interface Warehouse { warehouse: string; on_hand: number; reserved: number; available: number }
export interface ProductRow {
  sku: string; name: string; category: string; unit_price: string; on_hand: number; reserved: number; available: number;
  reorder_point: number; status: "OK" | "LOW" | "OUT_OF_STOCK" | "DISCONTINUED"; hazmat: boolean; warehouses: Warehouse[];
}
export interface OrderRow { order_number: string; customer: string; status: string; items: number; total: string; created_on: string }
export interface OrderDetail {
  order_number: string; status: string; customer: string; tier: string; email: string; phone: string;
  totals: { lines: { sku: string; name: string; quantity: number; unit_price: string; line_total: string }[];
    subtotal: string; discount: string; discount_pct: string; shipping: string; hazmat_surcharge: string; tax: string; total: string; notes: string[] };
}
export interface ActionRow {
  id: string; action_type: string; status: string; reason: string; created_at: string; resolved_at: string | null;
  preview: { title: string; changes: Change[]; warnings: string[] }; result: Record<string, unknown> | null;
}

export interface UsageSummary {
  window_days: number; llm_calls: number; input_tokens: number; output_tokens: number; cost_usd: number; cost_unknown_calls: number;
  llm_latency_ms: { p50: number; p95: number }; by_day: { day: string; calls: number; tokens: number }[];
  by_model: Record<string, { calls: number; input_tokens: number; output_tokens: number; cost_usd: number }>;
  tool_calls: Record<string, number>; guardrail_events: Record<string, number>; actions: Record<string, number>;
  corpus: { documents: number; chunks: number };
}

export interface Rate { passed: number; total: number; rate: number }
export interface EvalCase {
  id: string; category: string; user: string; question: string; passed: boolean; failed_checks: string[];
  tools_called: string[]; answer: string; citations: string[]; latency_ms: number; input_tokens: number; output_tokens: number;
}
export interface EvalResults {
  meta: { timestamp: string; provider: string; model: string; embedder: string; dataset_size: number; git: string };
  summary: {
    cases: number; passed: number; pass_rate: number;
    metrics: Record<string, Rate | number | null>;
    security: Record<string, string | number>;
    latency_ms: { p50: number; p95: number; mean: number; max: number };
    tokens: { input: number; output: number; mean_per_case: number };
    cost_usd: { total: number | null; per_case_mean: number | null };
    per_category: Record<string, { passed: number; total: number; pass_rate: number }>;
  };
  retrieval_ablation: Record<string, Record<string, { "recall@1": number; "recall@3": number; "recall@5": number; mrr: number; n: number }>>;
  cases: EvalCase[];
}
