// Personal API keys (Wave 2 closure).
//
// Surfaces the ``/api/auth/api-keys`` CRUD endpoints from
// :mod:`backend.routers.auth`. The plaintext token is returned only on
// ``create`` and never persisted client-side — the caller is responsible for
// showing it to the user once and dropping it from memory afterwards.

export interface ApiKey {
  id: string;
  name: string;
  scopes: string[];
  last_used_at: string | null;
  created_at: string;
  revoked_at: string | null;
}

export interface ApiKeyCreateResult {
  key: ApiKey;
  token: string;
  warning: string;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const res = await fetch(path, {
    method: init.method ?? "GET",
    headers,
    credentials: "same-origin",
    body: init.body,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* fall back to statusText */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

export const apiKeys = {
  list: () => request<ApiKey[]>("/api/auth/api-keys"),
  create: (name: string, scopes?: string[]) =>
    request<ApiKeyCreateResult>("/api/auth/api-keys", {
      method: "POST",
      body: JSON.stringify({ name, scopes }),
    }),
  revoke: (id: string) =>
    request<void>(`/api/auth/api-keys/${id}`, { method: "DELETE" }),
  // Rotate: server creates a new key with the same name + scopes and
  // revokes the original atomically. The plaintext is returned ONCE on
  // the response (same warning contract as create) — callers must show
  // it to the user immediately and drop it from memory afterwards.
  rotate: (id: string) =>
    request<ApiKeyCreateResult>(`/api/auth/api-keys/${id}/rotate`, {
      method: "POST",
    }),
};
