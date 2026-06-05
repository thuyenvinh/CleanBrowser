/**
 * Modal panel that shows the full detail of a single automation run.
 *
 * Types come from ``lib/automation.ts`` (owned by agent JJ). If that module
 * regresses or is rolled back, fall back to declaring ``AutomationRun`` /
 * ``AutomationRunStatus`` locally — see the matching note in
 * ``ScheduleForm.tsx`` for the local-type shape.
 */
import { RefreshCw, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { AutomationRun, AutomationRunStatus } from "../lib/automation";

interface RunViewerProps {
  run: AutomationRun;
  onClose: () => void;
  onRefresh?: () => Promise<void> | void;
  onCancel?: () => Promise<void> | void;
}

const STATUS_CLASSES: Record<AutomationRunStatus, string> = {
  success: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  failure: "bg-red-500/15 text-red-300 border-red-500/30",
  running: "bg-yellow-500/15 text-yellow-300 border-yellow-500/30",
  queued: "bg-gray-500/15 text-gray-300 border-gray-500/30",
  cancelled: "bg-gray-500/15 text-gray-300 border-gray-500/30",
};

function formatDuration(startISO: string, endISO: string | null): string {
  if (!endISO) return "—";
  const start = new Date(startISO).getTime();
  const end = new Date(endISO).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return "—";
  const ms = end - start;
  if (ms < 1000) return `${ms} ms`;
  const sec = ms / 1000;
  if (sec < 60) return `${sec.toFixed(1)} s`;
  const min = Math.floor(sec / 60);
  const rem = Math.round(sec - min * 60);
  return `${min}m ${rem}s`;
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export function RunViewer({ run, onClose, onRefresh, onCancel }: RunViewerProps) {
  const [refreshing, setRefreshing] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const isActive = run.status === "queued" || run.status === "running";

  const handleRefresh = async () => {
    if (!onRefresh) return;
    setRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setRefreshing(false);
    }
  };

  const handleCancel = async () => {
    if (!onCancel) return;
    setCancelling(true);
    try {
      await onCancel();
    } finally {
      setCancelling(false);
    }
  };

  // Auto-refresh while the run is still in flight so the UI converges to
  // the terminal state without the user having to mash the Refresh button.
  // We poll every 2s — fast enough for short flows, slow enough that a
  // dozen open tabs won't hammer the API. The effect tears down as soon
  // as the status flips out of queued/running, or onRefresh disappears.
  useEffect(() => {
    if (!isActive || !onRefresh) return;
    const id = setInterval(() => {
      void onRefresh();
    }, 2000);
    return () => clearInterval(id);
  }, [isActive, onRefresh]);

  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose();
  };

  const statusClass =
    STATUS_CLASSES[run.status] ?? STATUS_CLASSES.queued;

  const resultJsonPretty = run.result_json
    ? JSON.stringify(run.result_json, null, 2)
    : null;

  return (
    <div
      onClick={handleBackdropClick}
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
    >
      <div className="bg-surface-1 border border-border w-[800px] max-w-full max-h-[90vh] overflow-y-auto rounded shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border sticky top-0 bg-surface-1 z-10">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-semibold">
              Run <span className="font-mono text-sm text-gray-400">{run.id}</span>
            </h2>
            <span
              className={`text-xs px-2 py-0.5 rounded border uppercase tracking-wider ${statusClass}`}
            >
              {run.status}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {onRefresh && (
              <button
                type="button"
                onClick={handleRefresh}
                disabled={refreshing}
                className="btn-secondary flex items-center gap-1.5"
              >
                <RefreshCw
                  className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`}
                />
                <span>{refreshing ? "Refreshing..." : "Refresh"}</span>
              </button>
            )}
            {onCancel && isActive && (
              <button
                type="button"
                onClick={handleCancel}
                disabled={cancelling}
                className="btn-secondary flex items-center gap-1.5 text-red-300 border-red-500/40 hover:bg-red-500/10"
              >
                <span>{cancelling ? "Cancelling..." : "Cancel"}</span>
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="text-gray-400 hover:text-gray-200 p-1"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="p-5 space-y-5">
          {/* Times */}
          <section>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
              Timing
            </h3>
            <dl className="grid grid-cols-3 gap-3 text-sm">
              <div>
                <dt className="text-xs text-gray-500">Started</dt>
                <dd>{formatTime(run.started_at)}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">Ended</dt>
                <dd>{formatTime(run.ended_at)}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">Duration</dt>
                <dd>{formatDuration(run.started_at, run.ended_at)}</dd>
              </div>
            </dl>
          </section>

          {/* Trigger info */}
          <section>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
              Trigger
            </h3>
            <dl className="grid grid-cols-3 gap-3 text-sm">
              <div>
                <dt className="text-xs text-gray-500">Source</dt>
                <dd className="capitalize">{run.triggered_by}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">User</dt>
                <dd className="font-mono text-xs">
                  {run.triggered_by_user_id ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">Profile</dt>
                <dd className="font-mono text-xs">
                  {run.profile_id ?? "—"}
                </dd>
              </div>
            </dl>
          </section>

          {/* Error */}
          {run.error_message && (
            <section>
              <h3 className="text-xs font-semibold text-red-400 uppercase tracking-wider mb-2">
                Error
              </h3>
              <div className="bg-red-500/10 border border-red-500/30 text-red-200 rounded p-3 text-sm whitespace-pre-wrap font-mono">
                {run.error_message}
              </div>
            </section>
          )}

          {/* Log text */}
          <section>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
              Log
            </h3>
            {run.log_text ? (
              <pre className="bg-surface-0 border border-border rounded p-3 text-xs font-mono overflow-auto max-h-[400px] whitespace-pre-wrap">
                {run.log_text}
              </pre>
            ) : (
              <p className="text-xs text-gray-500 italic">(no log output)</p>
            )}
          </section>

          {/* Result JSON */}
          <section>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
              Result
            </h3>
            {resultJsonPretty ? (
              <pre className="bg-surface-0 border border-border rounded p-3 text-xs font-mono overflow-auto max-h-[400px]">
                {resultJsonPretty}
              </pre>
            ) : (
              <p className="text-xs text-gray-500 italic">(no result)</p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
