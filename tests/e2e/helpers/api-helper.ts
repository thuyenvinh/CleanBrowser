import type { APIRequestContext } from "@playwright/test";

/**
 * Tạo signup qua API, trả về session cookie để inject vào browser context.
 * Nhanh hơn click qua UI mỗi test.
 */
export async function apiSignup(
  req: APIRequestContext,
  email: string,
  password = "password123",
): Promise<unknown> {
  const r = await req.post("/api/auth/signup", { data: { email, password } });
  if (!r.ok()) throw new Error(`signup failed ${r.status()}`);
  return await r.json();
}

export async function apiCreateProxy(
  req: APIRequestContext,
  sessionCookie: string,
  data: {
    name: string;
    type?: string;
    host: string;
    port: number;
    username?: string;
    password?: string;
  },
): Promise<unknown> {
  const r = await req.post("/api/proxies", {
    data: { type: "http", ...data },
    headers: { Cookie: sessionCookie },
  });
  if (!r.ok()) throw new Error(`create proxy failed ${r.status()}`);
  return await r.json();
}

export async function apiCreateProfile(
  req: APIRequestContext,
  sessionCookie: string,
  data: {
    name: string;
    proxy_id?: string;
  },
): Promise<unknown> {
  const r = await req.post("/api/profiles", {
    data,
    headers: { Cookie: sessionCookie },
  });
  if (!r.ok()) throw new Error(`create profile failed ${r.status()}`);
  return await r.json();
}

export async function apiCreateAutomation(
  req: APIRequestContext,
  sessionCookie: string,
  data: {
    name: string;
    kind?: "flow" | "script";
    description?: string;
  },
): Promise<unknown> {
  const r = await req.post("/api/automations", {
    data: { kind: "flow", ...data },
    headers: { Cookie: sessionCookie },
  });
  if (!r.ok()) throw new Error(`create automation failed ${r.status()}`);
  return await r.json();
}
