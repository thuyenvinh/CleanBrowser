import { useState } from "react";
import { Key, Plus, Trash2, Copy, AlertTriangle, X, Check, RefreshCw, Shield } from "lucide-react";
import { useApiKeys } from "../hooks/useApiKeys";
import { apiKeys as apiKeysClient, type ApiKeyCreateResult } from "../lib/apikeys";
import { MfaSetupPage } from "./MfaSetupPage";

const AVAILABLE_SCOPES: { value: string; label: string; description: string }[] = [
  { value: "*", label: "Full access", description: "All API operations" },
  { value: "profiles:read", label: "Profiles (read)", description: "List + inspect browser profiles" },
  { value: "profiles:write", label: "Profiles (write)", description: "Create / update / delete profiles" },
  { value: "profiles:launch", label: "Profiles (launch)", description: "Start + stop running browsers" },
  { value: "automations:read", label: "Automations (read)", description: "List automations + runs" },
  { value: "automations:write", label: "Automations (write)", description: "Edit and trigger automations" },
];

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function formatRelative(iso: string | null): string {
  if (!iso) return "never";
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const minutes = Math.floor(diff / 60_000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  } catch {
    return iso;
  }
}

function CreateKeyModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (name: string, scopes: string[]) => Promise<ApiKeyCreateResult | null>;
}) {
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set(["*"]));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleScope = (scope: string) => {
    const next = new Set(selected);
    if (next.has(scope)) {
      next.delete(scope);
    } else {
      // Selecting "*" clears everything else; selecting any other clears "*".
      if (scope === "*") {
        next.clear();
      } else {
        next.delete("*");
      }
      next.add(scope);
    }
    if (next.size === 0) next.add("*");
    setSelected(next);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    setSubmitting(true);
    setError(null);
    const result = await onCreate(name.trim(), Array.from(selected));
    setSubmitting(false);
    if (!result) {
      setError("Failed to create key — check the network tab.");
      return;
    }
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-surface-1 border border-border rounded-lg w-full max-w-md p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold">Create new API key</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300">
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-xs text-gray-400 mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. CI deploy bot"
              maxLength={100}
              className="w-full px-2 py-1.5 bg-surface-0 border border-border rounded text-sm"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-2">Scopes</label>
            <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
              {AVAILABLE_SCOPES.map((s) => (
                <label
                  key={s.value}
                  className="flex items-start gap-2 text-xs cursor-pointer hover:bg-surface-2 rounded p-1.5"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(s.value)}
                    onChange={() => toggleScope(s.value)}
                    className="mt-0.5"
                  />
                  <div>
                    <div className="text-gray-200">{s.label}</div>
                    <div className="text-gray-500">{s.description}</div>
                  </div>
                </label>
              ))}
            </div>
          </div>
          {error && (
            <div className="text-red-400 text-xs">{error}</div>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs disabled:opacity-50"
            >
              {submitting ? "Creating..." : "Create key"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function NewTokenBanner({
  token,
  warning,
  onDismiss,
}: {
  token: string;
  warning: string;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable */
    }
  };
  return (
    <div className="border border-yellow-500/40 bg-yellow-500/10 rounded-lg p-4 mb-4">
      <div className="flex items-start gap-2 mb-3">
        <AlertTriangle className="h-4 w-4 text-yellow-400 mt-0.5 flex-shrink-0" />
        <div className="flex-1">
          <div className="text-sm font-medium text-yellow-300">Save your API key now</div>
          <p className="text-xs text-yellow-200/80 mt-1">{warning}</p>
        </div>
        <button
          onClick={onDismiss}
          className="text-yellow-400/60 hover:text-yellow-300"
          title="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex items-center gap-2 bg-surface-0 border border-border rounded px-3 py-2">
        <code className="flex-1 text-xs font-mono break-all text-emerald-300">{token}</code>
        <button
          onClick={copy}
          className="flex items-center gap-1 px-2 py-1 text-xs bg-surface-2 hover:bg-surface-3 rounded"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

export function ApiKeysPage() {
  const { keys, loading, error, create, revoke, refresh } = useApiKeys();
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState<ApiKeyCreateResult | null>(null);
  const [rotateError, setRotateError] = useState<string | null>(null);
  const [rotatingId, setRotatingId] = useState<string | null>(null);

  const handleCreate = async (name: string, scopes: string[]) => {
    const result = await create(name, scopes);
    if (result) setNewKey(result);
    return result;
  };

  const handleRevoke = async (id: string, name: string) => {
    if (!window.confirm(`Revoke API key "${name}"? Clients using it will stop working immediately.`)) {
      return;
    }
    await revoke(id);
  };

  // Rotate flow (M11): mint a replacement with the same name + scopes and
  // revoke the original. The server does this atomically; the UI shows the
  // new plaintext via the same NewTokenBanner as create, then refreshes
  // the list so the old row flips to "Revoked" and the new row appears.
  const handleRotate = async (id: string, name: string) => {
    if (
      !window.confirm(
        `Rotate API key "${name}"? A new token will be issued and "${name}" will be revoked — existing clients must switch to the new token immediately.`,
      )
    ) {
      return;
    }
    setRotatingId(id);
    setRotateError(null);
    try {
      const result = await apiKeysClient.rotate(id);
      setNewKey(result);
      await refresh();
    } catch (e) {
      setRotateError(e instanceof Error ? e.message : "Failed to rotate API key");
    } finally {
      setRotatingId(null);
    }
  };

  const exampleCurl = `curl -H "Authorization: Bearer YOUR_API_KEY" \\
  ${window.location.origin}/api/profiles`;

  if (loading) {
    return <div className="p-8 text-center text-gray-500 text-sm">Loading API keys...</div>;
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Shield className="h-5 w-5 text-gray-400" /> Security
          </h2>
          <p className="text-xs text-gray-500 mt-1">
            Manage two-factor authentication and personal API access tokens (Playwright / Puppeteer scripts, CI/CD).
          </p>
        </div>
        <button
          onClick={() => setCreating(true)}
          className="flex items-center gap-1 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs"
        >
          <Plus className="h-3 w-3" />
          Create new key
        </button>
      </div>

      {error && (
        <div className="bg-red-600/15 border border-red-600/30 text-red-400 px-3 py-2 rounded text-xs">
          {error}
        </div>
      )}

      {rotateError && (
        <div className="bg-red-600/15 border border-red-600/30 text-red-400 px-3 py-2 rounded text-xs">
          {rotateError}
        </div>
      )}

      {newKey && (
        <NewTokenBanner
          token={newKey.token}
          warning={newKey.warning}
          onDismiss={() => setNewKey(null)}
        />
      )}

      {/* M1: MFA enrolment lives in the same "Security" tab so users have
          a single place to manage credentials. */}
      <MfaSetupPage />

      <div>
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
          <Key className="h-4 w-4 text-gray-400" /> API keys
        </h3>
      <section className="border border-border rounded-lg bg-surface-1 overflow-hidden">
        {keys.length === 0 ? (
          <div className="p-8 text-center">
            <Key className="h-8 w-8 text-gray-600 mx-auto mb-2" />
            <p className="text-sm text-gray-400 mb-1">No API keys yet</p>
            <p className="text-xs text-gray-500">
              Use API keys to authenticate programmatic access (Playwright/Puppeteer scripts, CI/CD pipelines).
            </p>
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-gray-500">
                <th className="text-left px-4 py-2 font-medium">Name</th>
                <th className="text-left px-4 py-2 font-medium">Scopes</th>
                <th className="text-left px-4 py-2 font-medium">Created</th>
                <th className="text-left px-4 py-2 font-medium">Last used</th>
                <th className="text-left px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => {
                const revoked = !!k.revoked_at;
                return (
                  <tr key={k.id} className="border-t border-border">
                    <td className="px-4 py-2 font-medium text-gray-200">{k.name}</td>
                    <td className="px-4 py-2">
                      <div className="flex flex-wrap gap-1">
                        {k.scopes.map((s) => (
                          <span key={s} className="px-1.5 py-0.5 bg-surface-2 rounded text-gray-300 font-mono">
                            {s}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-2 text-gray-400" title={formatDate(k.created_at)}>
                      {formatRelative(k.created_at)}
                    </td>
                    <td className="px-4 py-2 text-gray-400" title={k.last_used_at ? formatDate(k.last_used_at) : "never used"}>
                      {formatRelative(k.last_used_at)}
                    </td>
                    <td className="px-4 py-2">
                      {revoked ? (
                        <span className="text-red-400">Revoked</span>
                      ) : (
                        <span className="text-emerald-400">Active</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      {!revoked && (
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => handleRotate(k.id, k.name)}
                            disabled={rotatingId === k.id}
                            className="text-gray-500 hover:text-emerald-400 p-1 disabled:opacity-50"
                            title="Rotate key (replace with a new token, revoke old)"
                          >
                            <RefreshCw className={`h-3.5 w-3.5 ${rotatingId === k.id ? "animate-spin" : ""}`} />
                          </button>
                          <button
                            onClick={() => handleRevoke(k.id, k.name)}
                            className="text-gray-500 hover:text-red-400 p-1"
                            title="Revoke key"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
      </div>

      <section>
        <h3 className="text-sm font-semibold mb-2">Example usage</h3>
        <div className="bg-surface-0 border border-border rounded p-3">
          <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap break-all">{exampleCurl}</pre>
        </div>
        <p className="text-xs text-gray-500 mt-2">
          Pass your API key in the <code className="text-gray-400">Authorization: Bearer</code> header.
          The same endpoints available through the web UI accept API key authentication.
        </p>
      </section>

      {creating && (
        <CreateKeyModal
          onClose={() => setCreating(false)}
          onCreate={handleCreate}
        />
      )}
    </div>
  );
}
