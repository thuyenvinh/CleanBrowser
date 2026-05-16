import { useState } from "react";
import { verification } from "../lib/auth";

/**
 * Top-of-app banner shown to users whose ``email_verified_at`` is still
 * null. Lets them re-trigger the verification email via
 * ``POST /api/auth/resend-verification``.
 *
 * The component is intentionally self-contained: it owns its own loading +
 * status state so the parent (``App.tsx``) just decides whether to mount it
 * at all based on ``authCtx.user.email_verified_at``.
 */
interface Props {
  email: string;
  onDismiss?: () => void;
}

export function EmailVerificationBanner({ email, onDismiss }: Props) {
  const [sending, setSending] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const handleResend = async () => {
    setSending(true);
    setStatus(null);
    try {
      const r = await verification.resend();
      if (r.already_verified) {
        setStatus("Already verified — please refresh");
      } else if (r.sent) {
        setStatus("Verification email sent");
      } else {
        setStatus("Failed to send");
      }
    } catch {
      setStatus("Failed to send");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="bg-yellow-500/10 border-b border-yellow-500/30 px-4 py-2 text-yellow-300 text-sm flex items-center justify-between">
      <span>
        Your email <strong>{email}</strong> is not verified. Check your inbox
        for the verification link.
      </span>
      <div className="flex items-center gap-3">
        {status && (
          <span className="text-yellow-200 text-xs">{status}</span>
        )}
        <button
          onClick={handleResend}
          disabled={sending}
          className="px-2 py-0.5 bg-yellow-500/20 hover:bg-yellow-500/30 rounded text-xs disabled:opacity-50"
        >
          {sending ? "Sending..." : "Resend verification email"}
        </button>
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="text-yellow-200/70 hover:text-yellow-200 text-xs"
            title="Dismiss"
          >
            ×
          </button>
        )}
      </div>
    </div>
  );
}
