import { useState, type FormEvent } from "react";
import { KeyRound } from "lucide-react";
import { passwordReset, AuthError } from "../lib/auth";

interface ResetPasswordPageProps {
  /** Token pulled from ``?token=`` on the URL the email link landed on. */
  token: string;
  /** Called after a successful password update so the host can route the
   *  user back to login (we don't auto-issue a session). */
  onSuccess: () => void;
  /** Bail out without resetting — used by the "Back to login" link. */
  onCancel: () => void;
}

/**
 * Step 2 of the forgot-password flow.
 *
 * The token comes from the URL — we don't ask the user to copy it; the
 * email link delivers it via ``?token=``. We collect the new password
 * twice (confirm field) to catch typos before consuming the one-shot
 * token; the backend also enforces ``min_length=8``.
 *
 * We intentionally do NOT auto-login on success: the user just proved
 * they control the email, not that they want to be logged in on this
 * particular device, and forcing them back through /login lets them pick
 * which credential autofill entry to use.
 */
export function ResetPasswordPage({ token, onSuccess, onCancel }: ResetPasswordPageProps) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  const validate = (): string | null => {
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
      await passwordReset.reset(token, password);
      setDone(true);
    } catch (err) {
      if (err instanceof AuthError && err.status === 400) {
        setError(
          "This reset link is invalid or has expired. Request a new one from the login page.",
        );
      } else if (err instanceof AuthError && err.status === 429) {
        setError("Too many attempts. Please try again later.");
      } else {
        setError(err instanceof Error ? err.message : "Reset failed");
      }
    } finally {
      setLoading(false);
    }
  };

  // Defensive: if the page is mounted without a ``?token=`` the user
  // clearly didn't come from the email — show a clear error rather than
  // letting them submit a blank token to the backend.
  if (!token) {
    return (
      <div className="h-screen flex items-center justify-center bg-surface-0">
        <div className="w-80 text-center">
          <p className="text-red-400 text-sm mb-3">Missing reset token</p>
          <p className="text-xs text-gray-500 mb-4">
            Please use the link from your reset email, or request a new one.
          </p>
          <button type="button" onClick={onCancel} className="btn-secondary w-full">
            Back to login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex items-center justify-center bg-surface-0">
      <div className="w-80">
        <div className="flex flex-col items-center mb-6">
          <div className="h-10 w-10 rounded-lg bg-accent/10 flex items-center justify-center mb-3">
            <KeyRound className="h-5 w-5 text-accent" />
          </div>
          <h1 className="text-lg font-semibold text-gray-100">
            Choose a new password
          </h1>
          <p className="text-xs text-gray-500 mt-1">
            {done ? "Password updated" : "Pick something you'll remember"}
          </p>
        </div>

        {done ? (
          <div className="text-center space-y-4">
            <p className="text-sm text-gray-300">
              Your password has been updated. Sign in with your new password.
            </p>
            <button
              type="button"
              onClick={onSuccess}
              className="btn-primary w-full"
            >
              Go to login
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <input
              type="password"
              className="input mb-3"
              placeholder="New password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              autoFocus
              required
            />
            <input
              type="password"
              className="input mb-3"
              placeholder="Confirm new password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              required
            />
            {error && <p className="text-red-400 text-xs mb-3">{error}</p>}
            <button
              type="submit"
              disabled={loading || !password || !confirm}
              className="btn-primary w-full disabled:opacity-50"
            >
              {loading ? "Updating..." : "Reset password"}
            </button>
            <div className="mt-4 text-center">
              <button
                type="button"
                onClick={onCancel}
                className="text-xs text-gray-500 hover:text-gray-300 underline"
              >
                Back to login
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
