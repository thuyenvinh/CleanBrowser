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

/**
 * Password reset client. Backed by the endpoints added in
 * ``backend/routers/auth.py`` for the bug C6 closure:
 *
 *   POST /api/auth/forgot-password   { email }       → always 200 (anti-enumeration)
 *   POST /api/auth/reset-password    { token, new_password } → { reset: true } | 400
 *
 * Both are unauthenticated — the reset link in the email is the proof of
 * email control, the same way the email-verification GET works.
 */
export interface ForgotPasswordResult {
  message: string;
}

export interface ResetPasswordResult {
  reset: boolean;
}

export const passwordReset = {
  forgot: (email: string) =>
    authRequest<ForgotPasswordResult>("/api/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  reset: (token: string, new_password: string) =>
    authRequest<ResetPasswordResult>("/api/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, new_password }),
    }),
};

/**
 * OAuth (social login) client helpers.
 *
 * The full OAuth dance is server-driven — the frontend's only jobs are to
 *   1. discover which providers are configured (so we can hide buttons that
 *      would otherwise 503 at /start), and
 *   2. navigate the top-level window to /api/auth/oauth/{provider}/start.
 *      We deliberately use ``window.location.href`` rather than ``fetch``
 *      because the IdP redirect chain needs to drive the user-agent itself
 *      (and have access to cross-site cookies on the way back) — fetching
 *      ``/start`` from JavaScript would leave the response 302 stranded.
 */
export type OAuthProviderName = "google" | "github";

export interface OAuthProvidersStatus {
  google: boolean;
  github: boolean;
}

export const oauth = {
  /** GET /api/auth/oauth/providers → { google, github } */
  getProvidersStatus: () =>
    authRequest<OAuthProvidersStatus>("/api/auth/oauth/providers"),

  /** Build the URL the browser should navigate to for the auth-code flow. */
  startUrl: (provider: OAuthProviderName) =>
    `/api/auth/oauth/${provider}/start`,
};
