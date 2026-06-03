import { useState } from "react";
import { Shield, ShieldCheck, ShieldOff, AlertTriangle, Check, Copy } from "lucide-react";
import { mfa, AuthError } from "../lib/auth";

/**
 * Two-factor (TOTP) enrolment page (M1).
 *
 * Render a self-contained MFA management section: a setup wizard (Enable
 * MFA → show QR + secret → confirm with 6-digit code) and a teardown form
 * (password + current code → disable).
 *
 * State model:
 *   - ``mode = "idle"``     : initial — show two cards ("Enable" / "Disable").
 *                              Persisted ``enabled`` in localStorage is the
 *                              hint we use to mark which card is the
 *                              "currently relevant" one. This is a UX hint
 *                              only — the server is always the source of
 *                              truth (e.g. enable will 400 if already on, and
 *                              disable will 401 if MFA isn't set).
 *   - ``mode = "setup"``    : /setup ran; QR + secret + code input visible.
 *   - ``mode = "disable"``  : disable form (password + code).
 *
 * The provisioning URI is rendered as a QR via a public third-party service
 * (qrserver.com) to avoid pulling in a QR-codegen npm dep just for this page.
 * The image is requested with ``referrerpolicy="no-referrer"`` to avoid
 * leaking the SPA origin in the request log — the URI itself already
 * contains the secret, so an interception of the request URL would be
 * the actual compromise. In a higher-trust deployment, swap this for a
 * locally-rendered QR.
 */

const LS_KEY = "cleanbrowser.mfa_enabled_hint";

function readEnabledHint(): boolean {
  try {
    return window.localStorage.getItem(LS_KEY) === "1";
  } catch {
    return false;
  }
}

function writeEnabledHint(enabled: boolean) {
  try {
    if (enabled) window.localStorage.setItem(LS_KEY, "1");
    else window.localStorage.removeItem(LS_KEY);
  } catch {
    /* localStorage may be blocked — UX hint only, safe to drop */
  }
}

function qrImageSrc(uri: string): string {
  // qrserver.com renders the otpauth:// URI as a 200×200 PNG. We keep the
  // size modest so the page still works on small screens.
  return `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(uri)}`;
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable */
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      className="flex items-center gap-1 px-2 py-1 text-xs bg-surface-2 hover:bg-surface-3 rounded"
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

type Mode = "idle" | "setup" | "disable";

export function MfaSetupPage() {
  const [mode, setMode] = useState<Mode>("idle");
  const [enabledHint, setEnabledHint] = useState(readEnabledHint);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Setup-flow state.
  const [secret, setSecret] = useState<string>("");
  const [uri, setUri] = useState<string>("");
  const [setupCode, setSetupCode] = useState("");

  // Disable-flow state.
  const [disablePassword, setDisablePassword] = useState("");
  const [disableCode, setDisableCode] = useState("");

  const resetToIdle = () => {
    setMode("idle");
    setError(null);
    setSecret("");
    setUri("");
    setSetupCode("");
    setDisablePassword("");
    setDisableCode("");
  };

  const startSetup = async () => {
    setBusy(true);
    setError(null);
    try {
      const { secret: s, qr_provisioning_uri } = await mfa.setup();
      setSecret(s);
      setUri(qr_provisioning_uri);
      setMode("setup");
    } catch (e) {
      const msg = e instanceof AuthError ? e.message : "Failed to start MFA setup";
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const confirmEnable = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!setupCode.trim()) {
      setError("Enter the 6-digit code from your authenticator app");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await mfa.enable(secret, setupCode.trim());
      writeEnabledHint(true);
      setEnabledHint(true);
      resetToIdle();
    } catch (e) {
      const msg =
        e instanceof AuthError
          ? e.message
          : "Failed to enable MFA — double-check the code and try again";
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const confirmDisable = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!disablePassword || !disableCode.trim()) {
      setError("Both password and code are required");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await mfa.disable(disablePassword, disableCode.trim());
      writeEnabledHint(false);
      setEnabledHint(false);
      resetToIdle();
    } catch (e) {
      const msg =
        e instanceof AuthError
          ? e.message
          : "Failed to disable MFA";
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="border border-border rounded-lg bg-surface-1 p-5">
      <div className="flex items-center gap-2 mb-1">
        <Shield className="h-4 w-4 text-gray-400" />
        <h3 className="text-sm font-semibold">Two-factor authentication</h3>
        {enabledHint && (
          <span className="ml-2 px-1.5 py-0.5 bg-emerald-600/15 text-emerald-300 rounded text-[10px] uppercase tracking-wide">
            Enabled
          </span>
        )}
      </div>
      <p className="text-xs text-gray-500 mb-4">
        Pair an authenticator app (Google Authenticator, 1Password, Authy) with
        your account. After enabling, login will ask for a 6-digit code in
        addition to your password.
      </p>

      {error && (
        <div className="bg-red-600/15 border border-red-600/30 text-red-400 px-3 py-2 rounded text-xs mb-4">
          {error}
        </div>
      )}

      {mode === "idle" && (
        <div className="grid sm:grid-cols-2 gap-3">
          <button
            type="button"
            onClick={startSetup}
            disabled={busy}
            className="text-left border border-border rounded p-3 hover:bg-surface-2 disabled:opacity-50"
          >
            <div className="flex items-center gap-2 mb-1">
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
              <span className="text-sm font-medium">Enable MFA</span>
            </div>
            <p className="text-xs text-gray-500">
              Scan a QR code with your authenticator and confirm with a code.
            </p>
          </button>
          <button
            type="button"
            onClick={() => {
              setMode("disable");
              setError(null);
            }}
            className="text-left border border-border rounded p-3 hover:bg-surface-2"
          >
            <div className="flex items-center gap-2 mb-1">
              <ShieldOff className="h-4 w-4 text-amber-400" />
              <span className="text-sm font-medium">Disable MFA</span>
            </div>
            <p className="text-xs text-gray-500">
              Confirm your password and a current code to turn off MFA.
            </p>
          </button>
        </div>
      )}

      {mode === "setup" && (
        <form onSubmit={confirmEnable} className="space-y-4">
          <div className="flex items-start gap-4 flex-wrap">
            <div className="bg-white p-2 rounded">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={qrImageSrc(uri)}
                alt="MFA provisioning QR code"
                width={200}
                height={200}
                referrerPolicy="no-referrer"
              />
            </div>
            <div className="flex-1 min-w-[200px] space-y-2">
              <div className="text-xs text-gray-400">
                Scan the QR with your authenticator. Can't scan? Type this
                secret manually:
              </div>
              <div className="flex items-center gap-2 bg-surface-0 border border-border rounded px-3 py-2">
                <code className="flex-1 text-xs font-mono break-all text-emerald-300">
                  {secret}
                </code>
                <CopyButton value={secret} />
              </div>
              <div className="flex items-start gap-2 bg-yellow-500/10 border border-yellow-500/30 rounded p-2">
                <AlertTriangle className="h-3.5 w-3.5 text-yellow-400 mt-0.5 flex-shrink-0" />
                <p className="text-[11px] text-yellow-200/80">
                  Save the secret in a password manager before continuing —
                  it's the only way to recover access if you lose your
                  authenticator device.
                </p>
              </div>
            </div>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Enter the 6-digit code from your authenticator
            </label>
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              value={setupCode}
              onChange={(e) => setSetupCode(e.target.value.replace(/\D/g, ""))}
              placeholder="123456"
              className="w-full px-2 py-1.5 bg-surface-0 border border-border rounded text-sm font-mono"
              autoFocus
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={resetToIdle}
              className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy || setupCode.length !== 6}
              className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs disabled:opacity-50"
            >
              {busy ? "Verifying..." : "Confirm and enable"}
            </button>
          </div>
        </form>
      )}

      {mode === "disable" && (
        <form onSubmit={confirmDisable} className="space-y-3">
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Current password
            </label>
            <input
              type="password"
              value={disablePassword}
              onChange={(e) => setDisablePassword(e.target.value)}
              className="w-full px-2 py-1.5 bg-surface-0 border border-border rounded text-sm"
              autoComplete="current-password"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Current 6-digit code
            </label>
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              value={disableCode}
              onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, ""))}
              placeholder="123456"
              className="w-full px-2 py-1.5 bg-surface-0 border border-border rounded text-sm font-mono"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={resetToIdle}
              className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy || !disablePassword || disableCode.length !== 6}
              className="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded text-xs disabled:opacity-50"
            >
              {busy ? "Disabling..." : "Disable MFA"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
