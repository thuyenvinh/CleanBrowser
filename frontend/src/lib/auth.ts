/**
 * Multi-tenant auth client.
 *
 * Talks to /api/auth/* endpoints implemented by the backend:
 *   POST /api/auth/signup  -> AuthResponse, sets httpOnly session cookie
 *   POST /api/auth/login   -> AuthResponse, sets httpOnly session cookie
 *   POST /api/auth/logout  -> 204
 *   GET  /api/auth/me      -> { user, workspaces } | 401
 *   GET  /api/workspaces   -> Workspace[]            | 401
 *
 * Auth endpoints do NOT carry an X-Workspace-Id header — they precede
 * workspace selection. See ``lib/api.ts`` for the workspace-scoped client.
 */

export interface User {
  id: string;
  email: string;
  tenant_id: string;
  /**
   * ISO timestamp when the user's email was verified, or ``null`` while
   * they're still in the unverified state. Used by ``EmailVerificationBanner``
   * to decide whether to nag.
   */
  email_verified_at?: string | null;
}

export interface Workspace {
  id: string;
  name: string;
  /** Optional fields returned by GET /api/workspaces. */
  tenant_id?: string;
  owner_user_id?: string;
  created_at?: string;
  role?: string;
}

/**
 * Successful signup/login response shape.
 *
 * The backend returns ``{user, workspaces}`` (workspaces is a list — even a
 * fresh signup yields a singleton list).
 */
export interface AuthResponse {
  user: User;
  workspaces: Workspace[];
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

  listWorkspaces: () => authRequest<Workspace[]>("/api/workspaces"),
};

/**
 * Email-verification client. Backed by the endpoints added in
 * ``backend/routers/auth.py`` for Phase 1 closure:
 *
 *   GET  /api/auth/verify-email?token=…  (used by the email link, not from JS)
 *   POST /api/auth/resend-verification   (banner-driven, requires session)
 *
 * The verify GET intentionally lives outside this module because it's a
 * server-rendered redirect, not a JSON endpoint.
 */
export interface ResendVerificationResult {
  sent?: boolean;
  already_verified?: boolean;
}

export const verification = {
  resend: () =>
    authRequest<ResendVerificationResult>("/api/auth/resend-verification", {
      method: "POST",
    }),
};
