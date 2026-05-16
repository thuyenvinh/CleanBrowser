import { useEffect, useState, type FormEvent } from "react";
import { Chrome, Github, Lock } from "lucide-react";
import { api } from "../lib/api";
import {
  auth,
  AuthError,
  oauth,
  type AuthResponse,
  type OAuthProviderName,
  type OAuthProvidersStatus,
} from "../lib/auth";

interface LoginPageProps {
  /** Called after a successful multi-tenant login. */
  onSuccess: (res: AuthResponse) => void;
  /** Called after a successful legacy single-token login (backward compat). */
  onLegacySuccess: () => void;
  /** Switch to the signup view. */
  onSwitchToSignup: () => void;
  /** If true, show only the legacy token field (no email/password). */
  legacyOnly?: boolean;
}

export function LoginPage({
  onSuccess,
  onLegacySuccess,
  onSwitchToSignup,
  legacyOnly = false,
}: LoginPageProps) {
  const [mode, setMode] = useState<"credentials" | "token">(
    legacyOnly ? "token" : "credentials",
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // OAuth providers status: ``null`` while we're still discovering, then
  // ``{google, github}`` booleans. Buttons stay hidden until we know — avoids
  // a flash of options that immediately disappear when the call resolves.
  const [providers, setProviders] = useState<OAuthProvidersStatus | null>(null);

  useEffect(() => {
    if (legacyOnly) return;
    // Best-effort: if discovery fails (e.g. backend missing the endpoint on
    // an older deployment) we just leave all buttons hidden, no error UI.
    oauth.getProvidersStatus().then(setProviders).catch(() => setProviders({ google: false, github: false }));
  }, [legacyOnly]);

  const startOAuth = (provider: OAuthProviderName) => {
    // Top-level navigation — see comment in lib/auth.ts on why fetch won't do.
    window.location.href = oauth.startUrl(provider);
  };

  const handleCredentialsSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await auth.login({ email, password });
      onSuccess(res);
    } catch (err) {
      if (err instanceof AuthError && err.status === 404) {
        setError("This server still uses legacy token auth. Use the link below.");
      } else {
        setError(err instanceof Error ? err.message : "Login failed");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleTokenSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await api.login(token);
      onLegacySuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-screen flex items-center justify-center bg-surface-0">
      <div className="w-80">
        <div className="flex flex-col items-center mb-6">
          <div className="h-10 w-10 rounded-lg bg-accent/10 flex items-center justify-center mb-3">
            <Lock className="h-5 w-5 text-accent" />
          </div>
          <h1 className="text-lg font-semibold text-gray-100">
            CloakBrowser Manager
          </h1>
          <p className="text-xs text-gray-500 mt-1">
            {mode === "credentials" ? "Sign in to your account" : "Enter your access token"}
          </p>
        </div>

        {mode === "credentials" && providers && (providers.google || providers.github) && (
          <div className="mb-4 space-y-2">
            {providers.google && (
              <button
                type="button"
                onClick={() => startOAuth("google")}
                className="btn-secondary w-full flex items-center justify-center gap-2"
              >
                <Chrome className="h-4 w-4" />
                Continue with Google
              </button>
            )}
            {providers.github && (
              <button
                type="button"
                onClick={() => startOAuth("github")}
                className="btn-secondary w-full flex items-center justify-center gap-2"
              >
                <Github className="h-4 w-4" />
                Continue with GitHub
              </button>
            )}
            <div className="flex items-center gap-3 pt-2 text-[10px] text-gray-600 uppercase">
              <div className="flex-1 h-px bg-gray-800" />
              <span>or</span>
              <div className="flex-1 h-px bg-gray-800" />
            </div>
          </div>
        )}

        {mode === "credentials" ? (
          <form onSubmit={handleCredentialsSubmit}>
            <input
              type="email"
              className="input mb-3"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              autoFocus
            />
            <input
              type="password"
              className="input mb-3"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
            {error && <p className="text-red-400 text-xs mb-3">{error}</p>}
            <button
              type="submit"
              disabled={loading || !email || !password}
              className="btn-primary w-full disabled:opacity-50"
            >
              {loading ? "Signing in..." : "Sign in"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleTokenSubmit}>
            <input
              type="password"
              className="input mb-3"
              placeholder="Access token"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoFocus
            />
            {error && <p className="text-red-400 text-xs mb-3">{error}</p>}
            <button
              type="submit"
              disabled={loading || !token}
              className="btn-primary w-full disabled:opacity-50"
            >
              {loading ? "Authenticating..." : "Unlock"}
            </button>
          </form>
        )}

        <div className="mt-4 text-center space-y-2">
          {mode === "credentials" && (
            <p className="text-xs text-gray-500">
              Don't have an account?{" "}
              <button
                type="button"
                onClick={onSwitchToSignup}
                className="text-accent hover:underline"
              >
                Sign up
              </button>
            </p>
          )}
          {!legacyOnly && (
            <button
              type="button"
              onClick={() => {
                setError(null);
                setMode((m) => (m === "credentials" ? "token" : "credentials"));
              }}
              className="text-[11px] text-gray-600 hover:text-gray-400 underline"
            >
              {mode === "credentials"
                ? "Use legacy token instead"
                : "Use email & password"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
