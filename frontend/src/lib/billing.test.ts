import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { billing } from "./billing";
import { setWorkspaceId } from "./api";

function mockFetch(responses: Array<{ status: number; body: unknown }>) {
  let i = 0;
  return vi.spyOn(global, "fetch").mockImplementation(async () => {
    const r = responses[i++] || { status: 500, body: {} };
    return {
      ok: r.status >= 200 && r.status < 300,
      status: r.status,
      statusText: r.status === 200 ? "OK" : "Error",
      text: async () => (r.body === undefined ? "" : JSON.stringify(r.body)),
      json: async () => r.body,
    } as Response;
  });
}

beforeEach(() => {
  setWorkspaceId("ws-1");
  vi.restoreAllMocks();
});

afterEach(() => {
  setWorkspaceId(null);
  vi.restoreAllMocks();
});

describe("billing.listPlans", () => {
  it("GETs /api/billing/plans with workspace header", async () => {
    const spy = mockFetch([{ status: 200, body: [{ id: "p1" }] }]);
    const plans = await billing.listPlans();
    expect(plans).toEqual([{ id: "p1" }]);
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe("/api/billing/plans");
    expect((init.headers as Record<string, string>)["X-Workspace-Id"]).toBe(
      "ws-1",
    );
  });
});

describe("billing.listPublicPlans", () => {
  it("GETs /api/billing/plans/public without workspace header", async () => {
    const spy = mockFetch([{ status: 200, body: [{ id: "free" }] }]);
    const plans = await billing.listPublicPlans();
    expect(plans).toEqual([{ id: "free" }]);
    expect(spy.mock.calls[0][0]).toBe("/api/billing/plans/public");
    // No headers param (or no X-Workspace-Id) — the call uses bare fetch.
    const init = spy.mock.calls[0][1] as RequestInit | undefined;
    const headers = (init?.headers ?? {}) as Record<string, string>;
    expect(headers["X-Workspace-Id"]).toBeUndefined();
  });
});

describe("billing.getSubscription", () => {
  it("GETs /api/billing/subscription", async () => {
    const spy = mockFetch([
      { status: 200, body: { subscription: null, plan: { id: "free" }, usage: {} } },
    ]);
    const s = await billing.getSubscription();
    expect(s.plan.id).toBe("free");
    expect(spy.mock.calls[0][0]).toBe("/api/billing/subscription");
  });
});

describe("billing.startCheckout", () => {
  it("POSTs plan_id and returns url", async () => {
    const spy = mockFetch([
      { status: 200, body: { url: "https://stripe.test/c", session_id: "cs_1" } },
    ]);
    const res = await billing.startCheckout("plan-pro");
    expect(res.url).toBe("https://stripe.test/c");
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe("/api/billing/checkout");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ plan_id: "plan-pro" });
  });
});

describe("billing.startVnpayCheckout", () => {
  it("POSTs plan_id to vnpay endpoint", async () => {
    const spy = mockFetch([
      { status: 200, body: { url: "https://vnpay/c", vnp_TxnRef: "T1" } },
    ]);
    const res = await billing.startVnpayCheckout("plan-pro");
    expect(res.vnp_TxnRef).toBe("T1");
    expect(spy.mock.calls[0][0]).toBe("/api/billing/vnpay/checkout");
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ plan_id: "plan-pro" });
  });
});

describe("billing.listInvoices", () => {
  it("GETs /api/billing/invoices", async () => {
    const spy = mockFetch([{ status: 200, body: [{ id: "inv1" }] }]);
    const inv = await billing.listInvoices();
    expect(inv).toEqual([{ id: "inv1" }]);
    expect(spy.mock.calls[0][0]).toBe("/api/billing/invoices");
  });

  it("throws on 500", async () => {
    mockFetch([{ status: 500, body: { detail: "boom" } }]);
    await expect(billing.listInvoices()).rejects.toThrow(/boom/);
  });
});
