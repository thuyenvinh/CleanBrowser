import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { automation, schedule, webhooks, ai } from "./automation";
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

describe("automation CRUD", () => {
  it("list GETs /api/automations", async () => {
    const spy = mockFetch([{ status: 200, body: [{ id: "a1" }] }]);
    await automation.list();
    expect(spy.mock.calls[0][0]).toBe("/api/automations");
  });

  it("create POSTs body", async () => {
    const spy = mockFetch([{ status: 200, body: { id: "a1" } }]);
    await automation.create({ name: "N", kind: "flow" });
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ name: "N", kind: "flow" });
  });

  it("update PUTs to /api/automations/{id}", async () => {
    const spy = mockFetch([{ status: 200, body: { id: "a1" } }]);
    await automation.update("a1", { name: "X" });
    expect(spy.mock.calls[0][0]).toBe("/api/automations/a1");
    expect((spy.mock.calls[0][1] as RequestInit).method).toBe("PUT");
  });

  it("delete DELETEs /api/automations/{id}", async () => {
    const spy = mockFetch([{ status: 204, body: undefined }]);
    await automation.delete("a1");
    expect(spy.mock.calls[0][0]).toBe("/api/automations/a1");
    expect((spy.mock.calls[0][1] as RequestInit).method).toBe("DELETE");
  });
});

describe("automation versions and runs", () => {
  it("createVersion POSTs to /versions", async () => {
    const spy = mockFetch([{ status: 200, body: { id: "v1" } }]);
    await automation.createVersion("a1", { dsl_json: { foo: 1 } });
    expect(spy.mock.calls[0][0]).toBe("/api/automations/a1/versions");
  });

  it("listRuns sends query params", async () => {
    const spy = mockFetch([{ status: 200, body: [] }]);
    await automation.listRuns("a1", 50, 10);
    expect(spy.mock.calls[0][0]).toBe(
      "/api/automations/a1/runs?limit=50&offset=10",
    );
  });

  it("getRun GETs run by id", async () => {
    const spy = mockFetch([{ status: 200, body: { id: "r1" } }]);
    await automation.getRun("r1");
    expect(spy.mock.calls[0][0]).toBe("/api/automations/runs/r1");
  });

  it("run POSTs with profile_id", async () => {
    const spy = mockFetch([
      { status: 200, body: { run_id: "r1", status: "queued" } },
    ]);
    await automation.run("a1", "pr1");
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe("/api/automations/a1/run");
    expect(JSON.parse(init.body as string)).toEqual({ profile_id: "pr1" });
  });

  it("cancelRun POSTs to runs/{id}/cancel", async () => {
    const spy = mockFetch([
      { status: 200, body: { cancelled: true, run_id: "r1" } },
    ]);
    const res = await automation.cancelRun("r1");
    expect(res.cancelled).toBe(true);
    expect(spy.mock.calls[0][0]).toBe("/api/automations/runs/r1/cancel");
  });
});

describe("schedule", () => {
  it("list GETs schedules for an automation", async () => {
    const spy = mockFetch([{ status: 200, body: [] }]);
    await schedule.list("a1");
    expect(spy.mock.calls[0][0]).toBe("/api/automations/a1/schedules");
  });

  it("create POSTs", async () => {
    const spy = mockFetch([{ status: 200, body: { id: "s1" } }]);
    await schedule.create("a1", { cron: "* * * * *" });
    expect(spy.mock.calls[0][0]).toBe("/api/automations/a1/schedules");
    expect((spy.mock.calls[0][1] as RequestInit).method).toBe("POST");
  });

  it("update PUTs", async () => {
    const spy = mockFetch([{ status: 200, body: { id: "s1" } }]);
    await schedule.update("s1", { enabled: false });
    expect(spy.mock.calls[0][0]).toBe("/api/automations/schedules/s1");
    expect((spy.mock.calls[0][1] as RequestInit).method).toBe("PUT");
  });

  it("delete DELETEs", async () => {
    const spy = mockFetch([{ status: 204, body: undefined }]);
    await schedule.delete("s1");
    expect(spy.mock.calls[0][0]).toBe("/api/automations/schedules/s1");
  });
});

describe("webhooks", () => {
  it("list GETs webhooks for automation", async () => {
    const spy = mockFetch([{ status: 200, body: [] }]);
    await webhooks.list("a1");
    expect(spy.mock.calls[0][0]).toBe("/api/automations/a1/webhooks");
  });

  it("create POSTs", async () => {
    const spy = mockFetch([{ status: 200, body: { id: "wh1", token: "T" } }]);
    await webhooks.create("a1", { name: "n" });
    expect(spy.mock.calls[0][0]).toBe("/api/automations/a1/webhooks");
    expect((spy.mock.calls[0][1] as RequestInit).method).toBe("POST");
  });

  it("delete DELETEs", async () => {
    const spy = mockFetch([{ status: 204, body: undefined }]);
    await webhooks.delete("wh1");
    expect(spy.mock.calls[0][0]).toBe("/api/automations/webhooks/wh1");
  });
});

describe("ai.buildAutomation", () => {
  it("POSTs prompt to /api/ai/build-automation", async () => {
    const spy = mockFetch([
      { status: 200, body: { dsl: {}, configured: true } },
    ]);
    const res = await ai.buildAutomation("scrape google");
    expect(res.configured).toBe(true);
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe("/api/ai/build-automation");
    expect(JSON.parse(init.body as string)).toEqual({ prompt: "scrape google" });
  });
});
