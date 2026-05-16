import { useState, type FormEvent } from "react";
import { UserPlus } from "lucide-react";
import { auth, AuthError, type AuthResponse } from "../lib/auth";

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
