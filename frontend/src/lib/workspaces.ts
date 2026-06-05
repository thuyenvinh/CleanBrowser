/**
 * Workspace API client.
 *
 * Backed by the ``/api/workspaces`` routes (CRUD + member management). The
 * ``request`` helper mirrors the pattern in ``lib/proxy.ts``: inject the
 * ``X-Workspace-Id`` header, surface backend ``detail`` strings as the error
 * message, and tolerate empty 204 responses.
 */
import { getWorkspaceId } from "./api";

export type WorkspaceRole = "owner" | "admin" | "editor" | "launcher" | "viewer";

export interface Workspace {
  id: string;
  tenant_id: string;
  name: string;
  owner_user_id: string;
  default_region?: string;
  created_at: string;
  role?: WorkspaceRole;
}

export interface WorkspaceMember {
  user_id: string;
  email: string;
  role: WorkspaceRole;
  created_at: string;
}

export interface WorkspaceWithMembers extends Workspace {
  members: WorkspaceMember[];
}

export class WorkspaceApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "WorkspaceApiError";
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
    throw new WorkspaceApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export const workspaces = {
  list: () => request<Workspace[]>("/api/workspaces"),
  get: (id: string) =>
    request<WorkspaceWithMembers>(`/api/workspaces/${id}`),
  create: (name: string) =>
    request<Workspace>("/api/workspaces", { method: "POST", body: { name } }),
  rename: (id: string, name: string) =>
    request<Workspace>(`/api/workspaces/${id}`, {
      method: "PUT",
      body: { name },
    }),
  delete: (id: string) =>
    request<void>(`/api/workspaces/${id}`, { method: "DELETE" }),
  invite: (id: string, email: string, role: WorkspaceRole) =>
    request<WorkspaceMember>(`/api/workspaces/${id}/members`, {
      method: "POST",
      body: { email, role },
    }),
  updateRole: (id: string, userId: string, role: WorkspaceRole) =>
    request<WorkspaceMember>(`/api/workspaces/${id}/members/${userId}`, {
      method: "PATCH",
      body: { role },
    }),
  removeMember: (id: string, userId: string) =>
    request<void>(`/api/workspaces/${id}/members/${userId}`, {
      method: "DELETE",
    }),
};
