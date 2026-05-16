import { getWorkspaceId } from "./api";

export interface Region {
  code: string;
  label: string;
  available: boolean;
}

export interface RegionList {
  regions: Region[];
  default: string;
}

export const regionsApi = {
  list: async (): Promise<RegionList> => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    const wsId = getWorkspaceId();
    if (wsId) headers["X-Workspace-Id"] = wsId;
    const res = await fetch("/api/regions", {
      headers,
      credentials: "same-origin",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },
};
