import type { Me } from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY = "copilot.apiKey";

export const keyStore = {
  get: (): string | null => (typeof window === "undefined" ? null : window.sessionStorage.getItem(KEY)),
  set: (k: string) => window.sessionStorage.setItem(KEY, k),
  clear: () => window.sessionStorage.removeItem(KEY),
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function parse(res: Response) {
  if (res.status === 204) return null;
  const text = await res.text();
  let body: unknown = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!res.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : `Request failed (${res.status})`;
    throw new ApiError(res.status, msg);
  }
  return body;
}

export async function api<T>(path: string, init: RequestInit & { key?: string; json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const key = init.key ?? keyStore.get();
  if (key) headers.set("X-API-Key", key);
  let body = init.body;
  if (init.json !== undefined) { headers.set("Content-Type", "application/json"); body = JSON.stringify(init.json); }
  let res: Response;
  try { res = await fetch(`${API_URL}${path}`, { ...init, headers, body }); }
  catch { throw new ApiError(0, `Cannot reach the API at ${API_URL}. Is the backend running?`); }
  return (await parse(res)) as T;
}

export const fetchMe = (key: string) => api<Me>("/api/me", { key });

export function money(v: string | number, digits = 2) {
  return Number(v).toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits });
}
export const fmtDate = (s: string) => new Date(s).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
