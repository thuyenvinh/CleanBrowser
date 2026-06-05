/**
 * Automation API client.
 *
 * Mirrors ``lib/proxy.ts`` (workspace header injection, 401 -> session-expired
 * hook). Backend routes live under ``/api/automations`` (see backend commit
 * 2c08f34).
 */
import { getWorkspaceId } from "./api";

export type AutomationKind = "flow" | "script";
export type AutomationRunStatus =
  | "queued"
  | "running"
  | "success"
  | "failure"
  | "cancelled";
export type AutomationScriptLanguage = "python" | "javascript";
export type AutomationTriggeredBy = "manual" | "schedule" | "webhook" | "api";

export interface Automation {
  id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  kind: AutomationKind;
  latest_version_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface AutomationVersion {
  id: string;
  automation_id: string;
  version: number;
  kind: AutomationKind;
  dsl_json: unknown | null;
  script_language: AutomationScriptLanguage | null;
  script_code: string | null;
  created_at: string;
  created_by_user_id: string | null;
}

export interface AutomationDetail {
  automation: Automation;
  versions: AutomationVersion[];
}

export interface AutomationRun {
  id: string;
  automation_version_id: string;
  profile_id: string | null;
  status: AutomationRunStatus;
  started_at: string;
  ended_at: string | null;
  log_text: string | null;
  result_json: unknown | null;
  error_message: string | null;
  triggered_by: AutomationTriggeredBy;
  triggered_by_user_id: string | null;
}

export interface AutomationCreateInput {
  name: string;
  kind: AutomationKind;
  description?: string | null;
}

export interface AutomationUpdateInput {
  name?: string;
  description?: string | null;
}

export interface AutomationVersionInput {
  dsl_json?: unknown;
  script_language?: AutomationScriptLanguage;
  script_code?: string;
}

export interface AutomationRunResponse {
  run_id: string;
  status: AutomationRunStatus;
}

// ---------------------------------------------------------------------------
// Shared interface contracts with sibling components (agent KK builds these).
// Re-declared here so callers can import a single source of truth, but the
// components themselves are owned by KK's PR.
// ---------------------------------------------------------------------------
export interface RunViewerProps {
  run: AutomationRun;
  onClose: () => void;
  onRefresh?: () => void;
}

export class AutomationApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "AutomationApiError";
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
    throw new AutomationApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export const automation = {
  list: () => request<Automation[]>("/api/automations"),
  create: (input: AutomationCreateInput) =>
    request<Automation>("/api/automations", { method: "POST", body: input }),
  get: (id: string) =>
    request<AutomationDetail>(`/api/automations/${id}`),
  update: (id: string, input: AutomationUpdateInput) =>
    request<Automation>(`/api/automations/${id}`, {
      method: "PUT",
      body: input,
    }),
  delete: (id: string) =>
    request<void>(`/api/automations/${id}`, { method: "DELETE" }),
  createVersion: (id: string, input: AutomationVersionInput) =>
    request<AutomationVersion>(`/api/automations/${id}/versions`, {
      method: "POST",
      body: input,
    }),
  listRuns: (id: string, limit = 100, offset = 0) =>
    request<AutomationRun[]>(
      `/api/automations/${id}/runs?limit=${limit}&offset=${offset}`,
    ),
  run: (id: string, profile_id?: string | null) =>
    request<AutomationRunResponse>(`/api/automations/${id}/run`, {
      method: "POST",
      body: { profile_id: profile_id ?? null },
    }),
  getRun: (run_id: string) =>
    request<AutomationRun>(`/api/automations/runs/${run_id}`),
  cancelRun: (run_id: string) =>
    request<{ cancelled: boolean; run_id: string }>(
      `/api/automations/runs/${run_id}/cancel`,
      { method: "POST" },
    ),
};

// ---------------------------------------------------------------------------
// Schedules
// ---------------------------------------------------------------------------
//
// Mirrors backend ``automation_schedules``. ``next_fire_at`` /
// ``last_fire_at`` are server-managed (the cron reconcile loop owns them)
// — clients only read.

export interface Schedule {
  id: string;
  automation_id: string;
  profile_id: string | null;
  cron: string;
  timezone: string;
  enabled: boolean;
  next_fire_at: string | null;
  last_fire_at: string | null;
  created_at: string;
}

export interface ScheduleCreateInput {
  cron: string;
  profile_id?: string | null;
  timezone?: string;
  enabled?: boolean;
}

export type ScheduleUpdateInput = Partial<ScheduleCreateInput>;

// ---------------------------------------------------------------------------
// AI assistant (Phase 6, task QQQ)
// ---------------------------------------------------------------------------
//
// Calls ``POST /api/ai/build-automation`` which feeds the prompt into an LLM
// and returns a DSL flow JSON. ``configured=false`` means the server has no
// ANTHROPIC_API_KEY and returned a dev-mode placeholder — the UI surfaces
// this as a warning banner.

export interface AiBuildResponse {
  dsl: unknown;
  configured: boolean;
}

export const ai = {
  buildAutomation: (prompt: string) =>
    request<AiBuildResponse>("/api/ai/build-automation", {
      method: "POST",
      body: { prompt },
    }),
};

export const schedule = {
  list: (automationId: string) =>
    request<Schedule[]>(`/api/automations/${automationId}/schedules`),
  create: (automationId: string, input: ScheduleCreateInput) =>
    request<Schedule>(`/api/automations/${automationId}/schedules`, {
      method: "POST",
      body: input,
    }),
  update: (id: string, input: ScheduleUpdateInput) =>
    request<Schedule>(`/api/automations/schedules/${id}`, {
      method: "PUT",
      body: input,
    }),
  delete: (id: string) =>
    request<void>(`/api/automations/schedules/${id}`, { method: "DELETE" }),
};

// ---------------------------------------------------------------------------
// Webhooks (token-authenticated triggers)
// ---------------------------------------------------------------------------
//
// One row per webhook trigger bound to an automation. The ``token`` is the
// URL-embedded credential — external services POST to
// ``/api/webhooks/automation/{token}`` to fire a run. The list endpoint
// returns the token plaintext so the UI can render the full URL with a
// Copy button; treat it as a secret and rotate (delete + recreate) if
// it ever leaks.

export interface AutomationWebhook {
  id: string;
  automation_id: string;
  token: string;
  name: string | null;
  enabled: boolean;
  profile_id: string | null;
  created_at: string;
  created_by_user_id: string | null;
  last_triggered_at: string | null;
  trigger_count: number;
}

export interface WebhookCreateInput {
  name?: string | null;
  profile_id?: string | null;
}

export const webhooks = {
  list: (automationId: string) =>
    request<AutomationWebhook[]>(
      `/api/automations/${automationId}/webhooks`,
    ),
  create: (automationId: string, input: WebhookCreateInput) =>
    request<AutomationWebhook>(
      `/api/automations/${automationId}/webhooks`,
      { method: "POST", body: input },
    ),
  delete: (id: string) =>
    request<void>(`/api/automations/webhooks/${id}`, { method: "DELETE" }),
};
