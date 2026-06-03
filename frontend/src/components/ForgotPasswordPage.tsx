import { useState, type FormEvent } from "react";
import { Mail } from "lucide-react";
import { passwordReset, AuthError } from "../lib/auth";

interface ForgotPasswordPageProps {
  /** Return to the login form. */
  onSwitchToLogin: () => void;
}

/**
 * Step 1 of the forgot-password flow.
 *
 * Backed by ``POST /api/auth/forgot-password`` which always returns 200 with
 * a generic message — we mirror that here by showing the same "check your
 * email" screen regardless of whether the email exists. That's the whole
 * anti-enumeration point; surfacing per-email errors here would defeat it.
 */
export function ForgotPasswordPage({ onSwitchToLogin }: ForgotPasswordPageProps) {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await passwordReset.forgot(email);
      setSubmitted(true);
    } catch (err) {
      // Rate-limit (429) or transport errors are the only signals we surface.
      // Specifically NOT echoing whether the email exists — see comment above.
      if (err instanceof AuthError && err.status === 429) {
        setError("Too many requests. Please try again later.");
      } else {
        setError(err instanceof Error ? err.message : "Request failed");
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
            <Mail className="h-5 w-5 text-accent" />
          </div>
          <h1 className="text-lg font-semibold text-gray-100">
            Reset your password
          </h1>
          <p className="text-xs text-gray-500 mt-1">
            {submitted ? "Check your email" : "We'll email you a reset link"}
          </p>
        </div>

        {submitted ? (
          <div className="text-center space-y-4">
            <p className="text-sm text-gray-300">
              If an account exists for{" "}
              <span className="text-gray-100">{email}</span>, a reset link has
              been sent. Check your inbox (and spam folder).
            </p>
            <p className="text-xs text-gray-500">The link expires in 1 hour.</p>
            <button
              type="button"
              onClick={onSwitchToLogin}
              className="btn-secondary w-full"
            >
              Back to login
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <input
              type="email"
              className="input mb-3"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              autoFocus
              required
            />
            {error && <p className="text-red-400 text-xs mb-3">{error}</p>}
            <button
              type="submit"
              disabled={loading || !email}
              className="btn-primary w-full disabled:opacity-50"
            >
              {loading ? "Sending..." : "Send reset link"}
            </button>
            <div className="mt-4 text-center">
              <button
                type="button"
                onClick={onSwitchToLogin}
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
