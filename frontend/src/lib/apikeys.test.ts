import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiKeys } from "./apikeys";

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
  vi.restoreAllMocks();
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("apiKeys.list", () => {
  it("GETs /api/auth/api-keys", async () => {
    const spy = mockFetch([{ status: 200, body: [{ id: "k1" }] }]);
    const out = await apiKeys.list();
    expect(spy.mock.calls[0][0]).toBe("/api/auth/api-keys");
    expect(out).toEqual([{ id: "k1" }]);
  });
});

describe("apiKeys.create", () => {
  it("POSTs name+scopes and returns plaintext token + key", async () => {
    const body = {
      key: {
        id: "k1",
        name: "ci",
        scopes: ["read"],
        last_used_at: null,
        created_at: "2026-01-01T00:00:00Z",
        revoked_at: null,
      },
      token: "tok_plaintext_XYZ",
      warning: "store this securely",
    };
    const spy = mockFetch([{ status: 200, body }]);
    const out = await apiKeys.create("ci", ["read"]);
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe("/api/auth/api-keys");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      name: "ci",
      scopes: ["read"],
    });
    expect(out.token).toBe("tok_plaintext_XYZ");
    expect(out.key.id).toBe("k1");
  });
});

describe("apiKeys.revoke", () => {
  it("DELETEs /api/auth/api-keys/{id}", async () => {
    const spy = mockFetch([{ status: 204, body: undefined }]);
    await apiKeys.revoke("k1");
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe("/api/auth/api-keys/k1");
    expect(init.method).toBe("DELETE");
  });
});

describe("apiKeys.rotate", () => {
  it("POSTs to /rotate and returns new token + warning", async () => {
    const body = {
      key: {
        id: "k1",
        name: "ci",
        scopes: ["read"],
        last_used_at: null,
        created_at: "2026-01-01T00:00:00Z",
        revoked_at: null,
      },
      token: "tok_new_plaintext",
      warning: "old token revoked",
    };
    const spy = mockFetch([{ status: 200, body }]);
    const out = await apiKeys.rotate("k1");
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe("/api/auth/api-keys/k1/rotate");
    expect(init.method).toBe("POST");
    expect(out.token).toBe("tok_new_plaintext");
    expect(out.warning).toBe("old token revoked");
  });
});

describe("apiKeys error handling", () => {
  it("surfaces detail from 4xx JSON body and throws on 5xx", async () => {
    mockFetch([
      { status: 403, body: { detail: "forbidden" } },
      { status: 500, body: { detail: "boom" } },
    ]);
    await expect(apiKeys.list()).rejects.toThrow(/403.*forbidden/);
    await expect(apiKeys.list()).rejects.toThrow(/500/);
  });
});
