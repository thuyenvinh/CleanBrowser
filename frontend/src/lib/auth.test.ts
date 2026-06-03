import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  auth,
  AuthError,
  oauth,
  mfa,
  passwordReset,
  verification,
} from "./auth";

function mockFetch(responses: Array<{ status: number; body: unknown }>) {
  let i = 0;
  return vi.spyOn(global, "fetch").mockImplementation(async () => {
    const r = responses[i++] || { status: 500, body: {} };
    return {
      ok: r.status >= 200 && r.status < 300,
      status: r.status,
      statusText: r.status === 200 ? "OK" : "Error",
      text: async () => JSON.stringify(r.body),
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

describe("auth.signup", () => {
  it("POSTs to /api/auth/signup with JSON body", async () => {
    const spy = mockFetch([
      { status: 200, body: { user: { id: "u1" }, workspaces: [] } },
    ]);
    await auth.signup({ email: "a@b.c", password: "secret" });
    const [url, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/auth/signup");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      email: "a@b.c",
      password: "secret",
    });
  });
});

describe("auth.login", () => {
  it("POSTs to /api/auth/login and returns body", async () => {
    mockFetch([
      { status: 200, body: { user: { id: "u1" }, workspaces: [{ id: "w1" }] } },
    ]);
    const res = await auth.login({ email: "a@b.c", password: "x" });
    expect(res.user.id).toBe("u1");
    expect(res.workspaces[0].id).toBe("w1");
  });

  it("throws AuthError on 401", async () => {
    mockFetch([{ status: 401, body: { detail: "Invalid credentials" } }]);
    await expect(
      auth.login({ email: "a@b.c", password: "x" }),
    ).rejects.toBeInstanceOf(AuthError);
  });
});

describe("oauth.startUrl", () => {
  it("returns the correct provider path", () => {
    expect(oauth.startUrl("google")).toBe("/api/auth/oauth/google/start");
    expect(oauth.startUrl("github")).toBe("/api/auth/oauth/github/start");
  });
});

describe("mfa", () => {
  it("setup POSTs to /api/auth/mfa/setup", async () => {
    const spy = mockFetch([
      { status: 200, body: { secret: "S", qr_provisioning_uri: "uri" } },
    ]);
    await mfa.setup();
    expect(spy.mock.calls[0][0]).toBe("/api/auth/mfa/setup");
    expect((spy.mock.calls[0][1] as RequestInit).method).toBe("POST");
  });

  it("enable POSTs secret+code", async () => {
    const spy = mockFetch([{ status: 200, body: { enabled: true } }]);
    await mfa.enable("S", "123456");
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe("/api/auth/mfa/enable");
    expect(JSON.parse(init.body as string)).toEqual({
      secret: "S",
      code: "123456",
    });
  });

  it("disable POSTs password+code", async () => {
    const spy = mockFetch([{ status: 200, body: { enabled: false } }]);
    await mfa.disable("pw", "111111");
    expect(spy.mock.calls[0][0]).toBe("/api/auth/mfa/disable");
  });
});

describe("passwordReset", () => {
  it("forgot POSTs email", async () => {
    const spy = mockFetch([{ status: 200, body: { message: "ok" } }]);
    await passwordReset.forgot("a@b.c");
    expect(spy.mock.calls[0][0]).toBe("/api/auth/forgot-password");
    expect(
      JSON.parse((spy.mock.calls[0][1] as RequestInit).body as string),
    ).toEqual({ email: "a@b.c" });
  });

  it("reset POSTs token+new_password", async () => {
    const spy = mockFetch([{ status: 200, body: { reset: true } }]);
    await passwordReset.reset("tok", "newpw");
    expect(spy.mock.calls[0][0]).toBe("/api/auth/reset-password");
  });
});

describe("verification.resend", () => {
  it("POSTs to /api/auth/resend-verification", async () => {
    const spy = mockFetch([{ status: 200, body: { sent: true } }]);
    const res = await verification.resend();
    expect(spy.mock.calls[0][0]).toBe("/api/auth/resend-verification");
    expect(res.sent).toBe(true);
  });
});
