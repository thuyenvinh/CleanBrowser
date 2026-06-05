import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { proxy, ProxyApiError } from "./proxy";
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

describe("proxy.list", () => {
  it("GETs /api/proxies with workspace header", async () => {
    const spy = mockFetch([{ status: 200, body: [{ id: "p1" }] }]);
    const out = await proxy.list();
    expect(out).toEqual([{ id: "p1" }]);
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe("/api/proxies");
    expect((init.headers as Record<string, string>)["X-Workspace-Id"]).toBe(
      "ws-1",
    );
  });
});

describe("proxy.create", () => {
  it("POSTs body to /api/proxies", async () => {
    const spy = mockFetch([{ status: 200, body: { id: "p2", name: "n" } }]);
    await proxy.create({ name: "n", type: "http", host: "h", port: 8080 });
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe("/api/proxies");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string).name).toBe("n");
  });
});

describe("proxy.update", () => {
  it("PUTs to /api/proxies/{id}", async () => {
    const spy = mockFetch([{ status: 200, body: { id: "p1" } }]);
    await proxy.update("p1", { name: "renamed" });
    expect(spy.mock.calls[0][0]).toBe("/api/proxies/p1");
    expect((spy.mock.calls[0][1] as RequestInit).method).toBe("PUT");
  });
});

describe("proxy.delete", () => {
  it("DELETEs /api/proxies/{id}", async () => {
    const spy = mockFetch([{ status: 204, body: undefined }]);
    await proxy.delete("p1");
    expect(spy.mock.calls[0][0]).toBe("/api/proxies/p1");
    expect((spy.mock.calls[0][1] as RequestInit).method).toBe("DELETE");
  });
});

describe("proxy.bulkCreate", () => {
  it("POSTs proxies array to /api/proxies/bulk", async () => {
    const spy = mockFetch([
      { status: 200, body: { created: 1, failed: [], proxies: [] } },
    ]);
    await proxy.bulkCreate([
      { name: "a", type: "http", host: "h", port: 8 },
    ]);
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe("/api/proxies/bulk");
    expect(JSON.parse(init.body as string).proxies).toHaveLength(1);
  });
});

describe("proxy.test", () => {
  it("POSTs to /api/proxies/{id}/test", async () => {
    const spy = mockFetch([{ status: 200, body: { status: "ok", latency_ms: 42 } }]);
    const res = await proxy.test("p1");
    expect(res.status).toBe("ok");
    expect(spy.mock.calls[0][0]).toBe("/api/proxies/p1/test");
    expect((spy.mock.calls[0][1] as RequestInit).method).toBe("POST");
  });
});

describe("proxy.getUsage", () => {
  it("GETs /api/proxies/{id}/usage", async () => {
    const spy = mockFetch([
      { status: 200, body: { profiles: [{ id: "pr1", name: "A" }] } },
    ]);
    const res = await proxy.getUsage("p1");
    expect(res.profiles).toHaveLength(1);
    expect(spy.mock.calls[0][0]).toBe("/api/proxies/p1/usage");
  });
});

describe("proxy error handling", () => {
  it("throws ProxyApiError on 401", async () => {
    mockFetch([{ status: 401, body: { detail: "Unauthorized" } }]);
    await expect(proxy.list()).rejects.toBeInstanceOf(ProxyApiError);
  });
});
