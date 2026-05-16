import { getWorkspaceId } from "./api";

export interface Plan {
  id: string; name: string; description: string | null;
  price_cents: number; interval: string;
  max_profiles: number | null;
  max_concurrent_runs: number | null;
  max_workspace_members: number | null;
  max_automation_minutes: number | null;
  max_storage_gb: number | null;
  allow_regions: string[];
  is_public: boolean;
  sort_order: number;
}

export interface Subscription {
  id: string; tenant_id: string; plan_id: string; status: string;
  payment_provider: string | null;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  trial_end: string | null;
  created_at: string;
}

export interface Usage {
  profile_count: number;
  concurrent_runs_peak: number;
  automation_minutes_used: number;
  storage_gb_used: number;
  workspace_members_count: number;
}

export interface SubscriptionStatus {
  subscription: Subscription | null;
  plan: Plan;
  usage: Usage;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const wsId = getWorkspaceId();
  if (wsId) headers["X-Workspace-Id"] = wsId;
  const res = await fetch(path, {
    method: init.method ?? "GET", headers, credentials: "same-origin", body: init.body,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { const b = await res.json(); if (b?.detail) detail = b.detail; } catch {}
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return text ? JSON.parse(text) : (undefined as T);
}

export interface Invoice {
  id: string;
  tenant_id: string;
  subscription_id: string | null;
  provider: string;
  provider_invoice_id: string;
  number: string | null;
  amount_cents: number;
  currency: string;
  status: string;
  hosted_invoice_url: string | null;
  invoice_pdf_url: string | null;
  period_start: string | null;
  period_end: string | null;
  paid_at: string | null;
  created_at: string;
}

export const billing = {
  listPlans: () => request<Plan[]>("/api/billing/plans"),
  getSubscription: () => request<SubscriptionStatus>("/api/billing/subscription"),
  startCheckout: (planId: string) =>
    request<{url: string, session_id: string}>("/api/billing/checkout", {
      method: "POST",
      body: JSON.stringify({ plan_id: planId }),
    }),
  openPortal: () => request<{url: string}>("/api/billing/portal", { method: "POST" }),
  listInvoices: () => request<Invoice[]>("/api/billing/invoices"),
};
