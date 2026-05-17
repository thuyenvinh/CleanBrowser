import { useEffect, useState, type FormEvent } from "react";
import { Chrome, Github, UserPlus } from "lucide-react";
import {
  auth,
  AuthError,
  oauth,
  type AuthResponse,
  type OAuthProviderName,
  type OAuthProvidersStatus,
} from "../lib/auth";

interface SignupPageProps {
  onSuccess: (res: AuthResponse) => void;
  onSwitchToLogin: () => void;
}

export function SignupPage({ onSuccess, onSwitchToLogin }: SignupPageProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [tenantName, setTenantName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // OAuth providers discovery — see LoginPage for the equivalent comment.
  const [providers, setProviders] = useState<OAuthProvidersStatus | null>(null);
  // Optional ``?plan=pro`` in the URL means the user came from the pricing
  // page — show a banner clarifying which trial they're about to start.
  // The trial is *always* Pro server-side (apply_signup_trial); we use the
  // URL param only to label the banner correctly when it ever isn't.
  const trialPlan = (() => {
    try {
      return new URLSearchParams(window.location.search).get("plan");
    } catch {
      return null;
    }
  })();

  useEffect(() => {
    oauth
      .getProvidersStatus()
      .then(setProviders)
      .catch(() => setProviders({ google: false, github: false }));
  }, []);

  const startOAuth = (provider: OAuthProviderName) => {
    window.location.href = oauth.startUrl(provider);
  };

  const validate = (): string | null => {
    if (!email.includes("@")) return "Enter a valid email address";
    if (password.length < 8) return "Password must be at least 8 characters";
    if (password !== confirm) return "Passwords do not match";
    return null;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const v = validate();
    if (v) {
      setError(v);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await auth.signup({
        email,
        password,
        tenant_name: tenantName.trim() || undefined,
      });
      onSuccess(res);
    } catch (err) {
      if (err instanceof AuthError && err.status === 404) {
        setError("Signup is not available yet — backend not deployed.");
      } else {
        setError(err instanceof Error ? err.message : "Signup failed");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-screen flex items-center justify-center bg-surface-0">
      <div className="w-80">
        <div className="flex flex-col items-center mb-6">
          <div className="h-10 w-10 rounded-lg bg-accent/10 flex items-center justify-center mb-3">
            <UserPlus className="h-5 w-5 text-accent" />
          </div>
          <h1 className="text-lg font-semibold text-gray-100">
            Create your account
          </h1>
          <p className="text-xs text-gray-500 mt-1">
            Sign up to manage browser profiles
          </p>
        </div>
        {trialPlan && (
          <div className="mb-4 px-3 py-2 rounded border border-accent/40 bg-accent/10 text-xs text-gray-200">
            Starting 14-day trial on{" "}
            <span className="font-semibold capitalize">{trialPlan}</span> plan
          </div>
        )}
        {providers && (providers.google || providers.github) && (
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

        <form onSubmit={handleSubmit}>
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
            placeholder="Password (min 8 characters)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
          <input
            type="password"
            className="input mb-3"
            placeholder="Confirm password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
          />
          <input
            type="text"
            className="input mb-3"
            placeholder="Workspace name (optional, e.g. Acme Co)"
            value={tenantName}
            onChange={(e) => setTenantName(e.target.value)}
          />
          {error && <p className="text-red-400 text-xs mb-3">{error}</p>}
          <button
            type="submit"
            disabled={loading || !email || !password || !confirm}
            className="btn-primary w-full disabled:opacity-50"
          >
            {loading ? "Creating account..." : "Sign up"}
          </button>
        </form>
        <p className="text-xs text-gray-500 mt-4 text-center">
          Already have an account?{" "}
          <button
            type="button"
            onClick={onSwitchToLogin}
            className="text-accent hover:underline"
          >
            Log in
          </button>
        </p>
      </div>
    </div>
  );
}
