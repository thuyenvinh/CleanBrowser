import { getWorkspaceId } from "./api";

export interface MarketplaceApp {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  long_description: string | null;
  icon_url: string | null;
  category: string | null;
  kind: "flow" | "script";
  version: string;
  creator_name: string | null;
  creator_url: string | null;
  install_count: number;
  is_official: boolean;
  is_public: boolean;
  required_permissions: string[];
  created_at: string;
  updated_at: string;
}

export interface TenantAppInstall {
  id: string;
  tenant_id: string;
  workspace_id: string;
  app_id: string;
  automation_id: string | null;
  installed_at: string;
  app_version: string | null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const wsId = getWorkspaceId();
  if (wsId) headers["X-Workspace-Id"] = wsId;
  const res = await fetch(path, {
    method: init.method ?? "GET",
    headers,
    credentials: "same-origin",
    body: init.body,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const b = await res.json();
      if (b?.detail) detail = b.detail;
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return text ? JSON.parse(text) : (undefined as T);
}

export interface MarketplaceAppSubmit {
  slug: string;
  name: string;
  kind: "flow" | "script";
  description?: string;
  long_description?: string;
  category?: string;
  dsl_json?: object;
  script_language?: string;
  script_code?: string;
  icon_url?: string;
  creator_name?: string;
  creator_url?: string;
}

export const marketplace = {
  listApps: (category?: string) =>
    request<MarketplaceApp[]>(
      `/api/marketplace/apps${category ? `?category=${encodeURIComponent(category)}` : ""}`,
    ),
  getApp: (id: string) => request<MarketplaceApp>(`/api/marketplace/apps/${id}`),
  install: (id: string, workspaceId?: string) =>
    request<TenantAppInstall>(`/api/marketplace/apps/${id}/install`, {
      method: "POST",
      body: JSON.stringify({ workspace_id: workspaceId }),
    }),
  listInstalls: () => request<TenantAppInstall[]>("/api/marketplace/installs"),
  uninstall: (installId: string) =>
    request<{ uninstalled: boolean }>(
      `/api/marketplace/installs/${installId}`,
      { method: "DELETE" },
    ),
  submit: (input: MarketplaceAppSubmit) =>
    request<MarketplaceApp>("/api/marketplace/apps/submit", {
      method: "POST",
      body: JSON.stringify(input),
    }),
};

// ── Creator dashboard (Phase 6 phase 3) ────────────────────────────────────
//
// Revenue share + earnings ledger. Matches the ``/creator/*`` routes in
// :mod:`backend.routers.marketplace`. ``status`` walks
// ``pending → available → paid_out`` with ``refunded`` as terminal.

export type MarketplaceEarningStatus =
  | "pending"
  | "available"
  | "paid_out"
  | "refunded";

export interface MarketplaceEarning {
  id: string;
  app_id: string;
  install_id: string | null;
  creator_user_id: string;
  buyer_tenant_id: string;
  gross_cents: number;
  creator_cents: number;
  platform_cents: number;
  currency: string;
  status: MarketplaceEarningStatus;
  available_at: string | null;
  paid_out_at: string | null;
  created_at: string;
  // Joined from marketplace_apps so the dashboard table doesn't N+1.
  app_slug?: string;
  app_name?: string;
}

export interface CreatorSummary {
  total_apps: number;
  total_installs: number;
  pending_cents: number;
  available_cents: number;
  paid_out_cents: number;
}

export interface CreatorEarningsResponse {
  summary: CreatorSummary;
  earnings: MarketplaceEarning[];
}

// A creator's own app row — includes ``moderation_status`` so the dashboard
// can surface pending / rejected submissions the public listing hides.
export interface CreatorApp {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  category: string | null;
  kind: "flow" | "script";
  version: string;
  install_count: number;
  is_official: boolean;
  is_public: boolean;
  moderation_status: "approved" | "pending" | "rejected";
  moderation_notes: string | null;
  price_cents: number;
  revenue_share_pct: number;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
}

export const marketplaceCreator = {
  earnings: () =>
    request<CreatorEarningsResponse>("/api/marketplace/creator/earnings"),
  apps: () => request<CreatorApp[]>("/api/marketplace/creator/apps"),
};

// ── Admin moderation (Phase 6 phase 4 — M5) ────────────────────────────────
//
// Surfaces the ``/admin/*`` routes in :mod:`backend.routers.marketplace`.
// Phase 6 has no super-admin role, so the backend gates these on bare
// auth — multi-tenant deploys need a real role gate added later.
//
// ``list_pending`` returns rows via ``SELECT *`` so the pending payload
// includes the full ``dsl_json`` / ``script_code`` body that the public
// listing strips out. We extend ``MarketplaceApp`` with the extra moderation
// fields so the admin queue can render submitter metadata and preview the
// payload without a second fetch.
export interface PendingMarketplaceApp extends MarketplaceApp {
  moderation_status: "pending" | "approved" | "rejected";
  moderation_notes: string | null;
  submitted_at: string | null;
  submitted_by_user_id: string | null;
  dsl_json: Record<string, unknown> | null;
  script_language: string | null;
  script_code: string | null;
}

export const marketplaceAdmin = {
  listPending: () =>
    request<PendingMarketplaceApp[]>("/api/marketplace/admin/pending"),
  approve: (id: string, notes?: string) =>
    request<PendingMarketplaceApp>(
      `/api/marketplace/admin/apps/${id}/approve`,
      {
        method: "POST",
        body: JSON.stringify({ notes: notes ?? null }),
      },
    ),
  reject: (id: string, notes: string) =>
    request<PendingMarketplaceApp>(
      `/api/marketplace/admin/apps/${id}/reject`,
      {
        method: "POST",
        body: JSON.stringify({ notes }),
      },
    ),
};
