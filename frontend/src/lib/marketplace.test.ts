import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  marketplace,
  marketplaceCreator,
  marketplaceAdmin,
} from "./marketplace";
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

describe("marketplace.listApps", () => {
  it("GETs /api/marketplace/apps without filter", async () => {
    const spy = mockFetch([{ status: 200, body: [] }]);
    await marketplace.listApps();
    expect(spy.mock.calls[0][0]).toBe("/api/marketplace/apps");
  });

  it("GETs with encoded category filter", async () => {
    const spy = mockFetch([{ status: 200, body: [] }]);
    await marketplace.listApps("data & scraping");
    expect(spy.mock.calls[0][0]).toBe(
      "/api/marketplace/apps?category=data%20%26%20scraping",
    );
  });
});

describe("marketplace.getApp", () => {
  it("GETs /api/marketplace/apps/{id}", async () => {
    const spy = mockFetch([{ status: 200, body: { id: "app-1" } }]);
    await marketplace.getApp("app-1");
    expect(spy.mock.calls[0][0]).toBe("/api/marketplace/apps/app-1");
  });
});

describe("marketplace.install", () => {
  it("POSTs workspace_id in body", async () => {
    const spy = mockFetch([{ status: 200, body: { id: "i1" } }]);
    await marketplace.install("app-1", "ws-2");
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe("/api/marketplace/apps/app-1/install");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ workspace_id: "ws-2" });
  });
});

describe("marketplace.listInstalls + uninstall", () => {
  it("listInstalls GETs /api/marketplace/installs", async () => {
    const spy = mockFetch([{ status: 200, body: [] }]);
    await marketplace.listInstalls();
    expect(spy.mock.calls[0][0]).toBe("/api/marketplace/installs");
  });

  it("uninstall DELETEs by install id", async () => {
    const spy = mockFetch([
      { status: 200, body: { uninstalled: true } },
    ]);
    await marketplace.uninstall("inst-1");
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe("/api/marketplace/installs/inst-1");
    expect(init.method).toBe("DELETE");
  });
});

describe("marketplaceCreator", () => {
  it("earnings GETs /api/marketplace/creator/earnings", async () => {
    const spy = mockFetch([
      {
        status: 200,
        body: {
          summary: {
            total_apps: 0,
            total_installs: 0,
            pending_cents: 0,
            available_cents: 0,
            paid_out_cents: 0,
          },
          earnings: [],
        },
      },
    ]);
    const res = await marketplaceCreator.earnings();
    expect(spy.mock.calls[0][0]).toBe("/api/marketplace/creator/earnings");
    expect(res.summary.total_apps).toBe(0);
  });

  it("apps GETs /api/marketplace/creator/apps", async () => {
    const spy = mockFetch([{ status: 200, body: [] }]);
    await marketplaceCreator.apps();
    expect(spy.mock.calls[0][0]).toBe("/api/marketplace/creator/apps");
  });
});

describe("marketplaceAdmin", () => {
  it("listPending GETs /api/marketplace/admin/pending", async () => {
    const spy = mockFetch([{ status: 200, body: [] }]);
    await marketplaceAdmin.listPending();
    expect(spy.mock.calls[0][0]).toBe("/api/marketplace/admin/pending");
  });

  it("approve POSTs notes to /admin/apps/{id}/approve", async () => {
    const spy = mockFetch([{ status: 200, body: { id: "app-1" } }]);
    await marketplaceAdmin.approve("app-1", "looks good");
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe(
      "/api/marketplace/admin/apps/app-1/approve",
    );
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ notes: "looks good" });
  });

  it("reject POSTs notes to /admin/apps/{id}/reject", async () => {
    const spy = mockFetch([{ status: 200, body: { id: "app-1" } }]);
    await marketplaceAdmin.reject("app-1", "spam");
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe(
      "/api/marketplace/admin/apps/app-1/reject",
    );
    expect(JSON.parse(init.body as string)).toEqual({ notes: "spam" });
  });
});
