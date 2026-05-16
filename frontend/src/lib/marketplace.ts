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
};
