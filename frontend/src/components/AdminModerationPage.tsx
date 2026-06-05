import { useMemo, useState } from "react";
import {
  ShieldCheck,
  Loader2,
  X,
  Check,
  Ban,
  Eye,
  Inbox,
  ArrowLeft,
} from "lucide-react";
import { useAdminPending } from "../hooks/useMarketplace";
import type { PendingMarketplaceApp } from "../lib/marketplace";

interface AdminModerationPageProps {
  onClose: () => void;
}

type Mode =
  | { kind: "list" }
  | { kind: "detail"; app: PendingMarketplaceApp }
  | { kind: "approve"; app: PendingMarketplaceApp }
  | { kind: "reject"; app: PendingMarketplaceApp };

/**
 * Admin moderation queue — lists pending (+ recently rejected) submissions
 * and lets a moderator approve or reject them.
 *
 * Backed by ``GET /api/marketplace/admin/pending`` plus the
 * ``/admin/apps/{id}/approve`` and ``.../reject`` actions. The queue auto
 * refreshes after each action so the table reflects the new state without
 * extra clicks.
 *
 * Phase 6 known limitation: the backend gates these routes on bare auth
 * only — any authenticated user can see this queue. Phase 7+ should add a
 * platform-admin role and tighten the route plus the launcher button in
 * MarketplacePage. Acceptable today for solo / single-tenant deploys; a
 * multi-tenant SaaS deployment must layer a super-admin gate before
 * shipping this surface.
 */
export function AdminModerationPage({ onClose }: AdminModerationPageProps) {
  const { apps, loading, error, refresh, approve, reject } = useAdminPending();
  const [mode, setMode] = useState<Mode>({ kind: "list" });

  const pending = useMemo(
    () => apps.filter((a) => a.moderation_status === "pending"),
    [apps],
  );

  function backToList() {
    setMode({ kind: "list" });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-surface-1 border border-border rounded-lg w-full max-w-5xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-2">
            {mode.kind !== "list" && (
              <button
                onClick={backToList}
                className="text-gray-400 hover:text-gray-200 p-1"
                aria-label="Back to queue"
              >
                <ArrowLeft className="h-4 w-4" />
              </button>
            )}
            <div>
              <h2 className="text-lg font-medium text-gray-100 flex items-center gap-2">
                <ShieldCheck className="h-5 w-5" />
                Marketplace Moderation Queue
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">
                Review pending app submissions. {pending.length} awaiting
                review.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-200 p-1"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {error && (
            <div className="mb-3 px-3 py-2 bg-red-600/15 border border-red-600/30 text-red-400 text-sm rounded">
              {error}
            </div>
          )}

          {loading ? (
            <div className="flex items-center justify-center py-16 text-sm text-gray-500 gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading queue...
            </div>
          ) : mode.kind === "list" ? (
            <QueueTable
              apps={apps}
              onView={(app) => setMode({ kind: "detail", app })}
              onApprove={(app) => setMode({ kind: "approve", app })}
              onReject={(app) => setMode({ kind: "reject", app })}
            />
          ) : mode.kind === "detail" ? (
            <DetailView app={mode.app} />
          ) : mode.kind === "approve" ? (
            <ApproveDialog
              app={mode.app}
              onCancel={backToList}
              onConfirm={async (notes) => {
                await approve(mode.app.id, notes);
                backToList();
              }}
            />
          ) : (
            <RejectDialog
              app={mode.app}
              onCancel={backToList}
              onConfirm={async (notes) => {
                await reject(mode.app.id, notes);
                backToList();
              }}
            />
          )}
        </div>

        {mode.kind === "list" && (
          <div className="px-6 py-3 border-t border-border flex items-center justify-end">
            <button
              onClick={() => refresh()}
              className="px-3 py-1.5 text-xs rounded border border-border text-gray-200 hover:bg-surface-2"
            >
              Refresh
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

interface QueueTableProps {
  apps: PendingMarketplaceApp[];
  onView: (app: PendingMarketplaceApp) => void;
  onApprove: (app: PendingMarketplaceApp) => void;
  onReject: (app: PendingMarketplaceApp) => void;
}

function QueueTable({ apps, onView, onApprove, onReject }: QueueTableProps) {
  if (apps.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <Inbox className="h-10 w-10 text-gray-600 mb-3" />
        <p className="text-gray-400 text-sm">No apps awaiting review.</p>
        <p className="text-gray-600 text-xs mt-1">
          Submissions appear here when creators publish from the marketplace.
        </p>
      </div>
    );
  }
  return (
    <div className="overflow-x-auto border border-border rounded-md">
      <table className="w-full text-xs">
        <thead className="bg-surface-2 text-gray-400">
          <tr>
            <th className="text-left px-3 py-2 font-medium">Submitted</th>
            <th className="text-left px-3 py-2 font-medium">Submitter</th>
            <th className="text-left px-3 py-2 font-medium">Name / slug</th>
            <th className="text-left px-3 py-2 font-medium">Category</th>
            <th className="text-left px-3 py-2 font-medium">Kind</th>
            <th className="text-left px-3 py-2 font-medium">Status</th>
            <th className="text-right px-3 py-2 font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {apps.map((app) => {
            const isPending = app.moderation_status === "pending";
            return (
              <tr key={app.id} className="border-t border-border align-top">
                <td className="px-3 py-2 text-gray-400 whitespace-nowrap">
                  {formatDate(app.submitted_at ?? app.created_at)}
                </td>
                <td className="px-3 py-2 text-gray-300">
                  {app.creator_name ?? "—"}
                </td>
                <td className="px-3 py-2 text-gray-100">
                  <div>{app.name}</div>
                  <div className="text-[11px] text-gray-500">{app.slug}</div>
                </td>
                <td className="px-3 py-2 text-gray-400">
                  {app.category ?? "—"}
                </td>
                <td className="px-3 py-2 text-gray-300 uppercase tracking-wide">
                  {app.kind}
                </td>
                <td className="px-3 py-2">
                  <ModerationBadge status={app.moderation_status} />
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <div className="inline-flex items-center gap-1.5">
                    <button
                      onClick={() => onView(app)}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded border border-border text-gray-200 hover:bg-surface-2"
                    >
                      <Eye className="h-3 w-3" />
                      View
                    </button>
                    <button
                      onClick={() => onApprove(app)}
                      disabled={!isPending}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded bg-emerald-600/20 text-emerald-300 border border-emerald-600/40 hover:bg-emerald-600/30 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <Check className="h-3 w-3" />
                      Approve
                    </button>
                    <button
                      onClick={() => onReject(app)}
                      disabled={!isPending}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded bg-red-600/20 text-red-300 border border-red-600/40 hover:bg-red-600/30 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <Ban className="h-3 w-3" />
                      Reject
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function DetailView({ app }: { app: PendingMarketplaceApp }) {
  const payload = useMemo(() => {
    if (app.kind === "flow") {
      return app.dsl_json
        ? JSON.stringify(app.dsl_json, null, 2)
        : "(no dsl_json submitted)";
    }
    return app.script_code ?? "(no script_code submitted)";
  }, [app]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
        <Field label="Name" value={app.name} />
        <Field label="Slug" value={app.slug} />
        <Field label="Kind" value={app.kind} />
        <Field label="Category" value={app.category ?? "—"} />
        <Field label="Version" value={app.version} />
        <Field label="Submitter" value={app.creator_name ?? "—"} />
        <Field
          label="Submitted at"
          value={formatDate(app.submitted_at ?? app.created_at)}
        />
        <Field
          label="Status"
          value={app.moderation_status}
        />
      </div>

      <div>
        <div className="text-xs text-gray-400 mb-1">Description</div>
        <div className="p-3 rounded border border-border bg-surface-2 text-xs text-gray-200 whitespace-pre-wrap">
          {app.long_description || app.description || "(no description)"}
        </div>
      </div>

      {app.moderation_notes && (
        <div>
          <div className="text-xs text-gray-400 mb-1">Moderation notes</div>
          <div className="p-3 rounded border border-border bg-surface-2 text-xs text-gray-200 whitespace-pre-wrap">
            {app.moderation_notes}
          </div>
        </div>
      )}

      <div>
        <div className="text-xs text-gray-400 mb-1">
          {app.kind === "flow" ? "DSL JSON" : "Script code"}
          {app.kind === "script" && app.script_language && (
            <span className="text-gray-500"> · {app.script_language}</span>
          )}
        </div>
        <pre className="p-3 rounded border border-border bg-black/30 text-[11px] text-gray-200 overflow-auto max-h-80">
          {payload}
        </pre>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-gray-500">{label}</div>
      <div className="text-gray-100 mt-0.5 break-words">{value}</div>
    </div>
  );
}

interface ApproveDialogProps {
  app: PendingMarketplaceApp;
  onCancel: () => void;
  onConfirm: (notes?: string) => Promise<void>;
}

function ApproveDialog({ app, onCancel, onConfirm }: ApproveDialogProps) {
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      await onConfirm(notes.trim() || undefined);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to approve");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-xl mx-auto">
      <h3 className="text-sm font-medium text-gray-100 mb-1">
        Approve "{app.name}"?
      </h3>
      <p className="text-xs text-gray-500 mb-3">
        Flips moderation status to approved and makes the app publicly
        listable in the marketplace.
      </p>
      <label className="block text-xs text-gray-400 mb-1">
        Notes (optional)
      </label>
      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        rows={4}
        className="w-full bg-surface-2 border border-border rounded px-2 py-1.5 text-xs text-gray-100"
        placeholder="Internal notes attached to the moderation record."
      />
      {err && (
        <div className="mt-2 text-xs text-red-400">{err}</div>
      )}
      <div className="mt-4 flex items-center justify-end gap-2">
        <button
          onClick={onCancel}
          disabled={busy}
          className="px-3 py-1.5 text-xs rounded border border-border text-gray-200 hover:bg-surface-2"
        >
          Cancel
        </button>
        <button
          onClick={submit}
          disabled={busy}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
          Approve
        </button>
      </div>
    </div>
  );
}

interface RejectDialogProps {
  app: PendingMarketplaceApp;
  onCancel: () => void;
  onConfirm: (notes: string) => Promise<void>;
}

function RejectDialog({ app, onCancel, onConfirm }: RejectDialogProps) {
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const trimmed = notes.trim();

  async function submit() {
    if (!trimmed) {
      setErr("Rejection notes are required.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await onConfirm(trimmed);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to reject");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-xl mx-auto">
      <h3 className="text-sm font-medium text-gray-100 mb-1">
        Reject "{app.name}"?
      </h3>
      <p className="text-xs text-gray-500 mb-3">
        Notes are required — the creator sees them in their submission
        history so they can fix the issue and resubmit.
      </p>
      <label className="block text-xs text-gray-400 mb-1">
        Notes <span className="text-red-400">*</span>
      </label>
      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        rows={4}
        className="w-full bg-surface-2 border border-border rounded px-2 py-1.5 text-xs text-gray-100"
        placeholder="Why is this submission being rejected?"
      />
      {err && <div className="mt-2 text-xs text-red-400">{err}</div>}
      <div className="mt-4 flex items-center justify-end gap-2">
        <button
          onClick={onCancel}
          disabled={busy}
          className="px-3 py-1.5 text-xs rounded border border-border text-gray-200 hover:bg-surface-2"
        >
          Cancel
        </button>
        <button
          onClick={submit}
          disabled={busy || !trimmed}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-red-600 text-white hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Ban className="h-3 w-3" />}
          Reject
        </button>
      </div>
    </div>
  );
}

function ModerationBadge({
  status,
}: {
  status: PendingMarketplaceApp["moderation_status"];
}) {
  const config: Record<
    PendingMarketplaceApp["moderation_status"],
    string
  > = {
    approved: "bg-emerald-600/15 text-emerald-300 border-emerald-600/30",
    pending: "bg-amber-600/15 text-amber-300 border-amber-600/30",
    rejected: "bg-red-600/15 text-red-300 border-red-600/30",
  };
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded-full border text-[11px] ${config[status]}`}
    >
      {status}
    </span>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
