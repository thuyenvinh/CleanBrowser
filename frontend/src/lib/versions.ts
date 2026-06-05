import { getWorkspaceId } from "./api";

export interface ProfileVersion {
  id: string;
  profile_id: string;
  version: number;
  storage_key: string;
  size_bytes: number | null;
  sha256: string | null;
  created_at: string;
  created_by_user_id: string | null;
  created_by_session_id: string | null;
  notes: string | null;
}

export class VersionsApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "VersionsApiError";
  }
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
      // ignore
    }
    throw new VersionsApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

export const versions = {
  list: (profileId: string) =>
    request<ProfileVersion[]>(`/api/profiles/${profileId}/versions`),
  restore: (profileId: string, versionId: string) =>
    request<{ restored: boolean }>(
      `/api/profiles/${profileId}/versions/${versionId}/restore`,
      { method: "POST" },
    ),
};
