/**
 * Multi-tenant auth client.
 *
 * Talks to /api/auth/* endpoints that will be implemented in Phase 2:
 *   POST /api/auth/signup  -> AuthResponse, sets httpOnly session cookie
 *   POST /api/auth/login   -> AuthResponse, sets httpOnly session cookie
 *   POST /api/auth/logout  -> 204
 *   GET  /api/auth/me      -> { user, workspaces } | 401
 *
 * Until the backend is ready these calls will fail; consumers must handle
 * errors / 404 gracefully. Legacy token login still lives in `api.login()`.
 */

export interface User {
  id: string;
  email: string;
  tenant_id: string;
}

export interface Workspace {
  id: string;
  name: string;
}

export interface AuthResponse {
  user: User;
  workspace: Workspace;
}

export interface MeResponse {
  user: User;
  workspaces: Workspace[];
}

export interface LoginInput {
  email: string;
  password: string;
}

export interface SignupInput {
  email: string;
  password: string;
  tenant_name?: string;
}

export class AuthError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "AuthError";
  }
}

export const AUTH_NOT_IMPLEMENTED = 404;

async function authRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      // ignore non-JSON error bodies
    }
    throw new AuthError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const auth = {
  signup: (input: SignupInput) =>
    authRequest<AuthResponse>("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  login: (input: LoginInput) =>
    authRequest<AuthResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  logout: () =>
    authRequest<void>("/api/auth/logout", { method: "POST" }),

  me: () => authRequest<MeResponse>("/api/auth/me"),
};
