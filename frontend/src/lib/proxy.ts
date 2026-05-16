/**
 * Proxy pool API client.
 *
 * Lives next to ``lib/api.ts`` and mirrors its HTTP/error-handling conventions
 * (workspace header injection, 401 -> session-expired hook). The ``request``
 * helper is duplicated locally rather than re-exported from ``api.ts`` so
 * that file stays untouched while this module ships in the same wave.
 */
import { getWorkspaceId } from "./api";

export type ProxyStatus = "unchecked" | "ok" | "fail";

export interface Proxy {
  id: string;
  workspace_id: string;
  name: string;
  type: string;
  host: string;
  port: number;
  username: string | null;
  provider: string | null;
  country_code: string | null;
  status: ProxyStatus;
  latency_ms: number | null;
  last_check_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProxyCreateInput {
  name: string;
  type: string;
  host: string;
  port: number;
  username?: string | null;
  password?: string | null;
  provider?: string | null;
}

export type ProxyUpdateInput = Partial<ProxyCreateInput>;

export interface ProxyTestResult {
  status: "ok" | "fail";
  latency_ms?: number;
  country_code?: string;
  error?: string;
}

export class ProxyApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ProxyApiError";
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const wsId = getWorkspaceId();
  if (wsId) headers["X-Workspace-Id"] = wsId;

  const init: RequestInit = {
    method: options.method ?? "GET",
    headers,
    credentials: "same-origin",
  };
  if (options.body !== undefined) {
    init.body = JSON.stringify(options.body);
  }

  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      // ignore non-JSON bodies
    }
    throw new ProxyApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  // DELETE may return empty body
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export interface BulkResult {
  created: number;
  failed: { index: number; error: string }[];
  proxies: Proxy[];
}

export const proxy = {
  list: () => request<Proxy[]>("/api/proxies"),
  create: (input: ProxyCreateInput) =>
    request<Proxy>("/api/proxies", { method: "POST", body: input }),
  bulkCreate: (proxies: ProxyCreateInput[]) =>
    request<BulkResult>("/api/proxies/bulk", {
      method: "POST",
      body: { proxies },
    }),
  get: (id: string) => request<Proxy>(`/api/proxies/${id}`),
  update: (id: string, input: ProxyUpdateInput) =>
    request<Proxy>(`/api/proxies/${id}`, { method: "PUT", body: input }),
  delete: (id: string) =>
    request<void>(`/api/proxies/${id}`, { method: "DELETE" }),
  test: (id: string) =>
    request<ProxyTestResult>(`/api/proxies/${id}/test`, { method: "POST" }),
};
