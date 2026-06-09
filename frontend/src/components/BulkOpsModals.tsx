import { useState } from "react";
import { X } from "lucide-react";
import type { Automation } from "../lib/automation";
import type { BulkProfileResult } from "../lib/api";

interface BulkResizeModalProps {
  count: number;
  onClose: () => void;
  onConfirm: (width: number, height: number) => void;
}

const PRESETS: { label: string; width: number; height: number }[] = [
  { label: "1280 × 720 (HD)", width: 1280, height: 720 },
  { label: "1366 × 768 (HD+)", width: 1366, height: 768 },
  { label: "1440 × 900", width: 1440, height: 900 },
  { label: "1600 × 900", width: 1600, height: 900 },
  { label: "1920 × 1080 (Full HD)", width: 1920, height: 1080 },
  { label: "2560 × 1440 (QHD)", width: 2560, height: 1440 },
  { label: "3840 × 2160 (4K)", width: 3840, height: 2160 },
];

export function BulkResizeModal({ count, onClose, onConfirm }: BulkResizeModalProps) {
  const [width, setWidth] = useState<number>(1920);
  const [height, setHeight] = useState<number>(1080);

  const apply = () => {
    if (width < 320 || width > 7680 || height < 240 || height > 4320) {
      return;
    }
    onConfirm(width, height);
  };

  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-surface-1 border border-border rounded-lg w-full max-w-md p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Resize viewport — {count} profile{count === 1 ? "" : "s"}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {PRESETS.map((p) => (
            <button
              key={p.label}
              type="button"
              onClick={() => {
                setWidth(p.width);
                setHeight(p.height);
              }}
              className={`px-2 py-1.5 text-xs rounded border ${
                width === p.width && height === p.height
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border hover:border-border-hover text-gray-300"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-xs text-gray-400">
            Width
            <input
              type="number"
              min={320}
              max={7680}
              value={width}
              onChange={(e) => setWidth(parseInt(e.target.value, 10) || 0)}
              className="input mt-1"
            />
          </label>
          <label className="text-xs text-gray-400">
            Height
            <input
              type="number"
              min={240}
              max={4320}
              value={height}
              onChange={(e) => setHeight(parseInt(e.target.value, 10) || 0)}
              className="input mt-1"
            />
          </label>
        </div>
        <div className="text-[11px] text-gray-500">
          Persists to <code>screen_width / screen_height</code>. Running profiles will be live-resized via CDP best-effort; failures don&apos;t roll back the saved size.
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="btn-secondary">Cancel</button>
          <button onClick={apply} className="btn-primary">Apply</button>
        </div>
      </div>
    </div>
  );
}


interface BulkRunAutomationModalProps {
  count: number;
  automations: Automation[];
  onClose: () => void;
  onConfirm: (automationId: string) => void;
}

export function BulkRunAutomationModal({
  count,
  automations,
  onClose,
  onConfirm,
}: BulkRunAutomationModalProps) {
  const usable = automations.filter((a) => Boolean(a.latest_version_id));
  const [picked, setPicked] = useState<string>(usable[0]?.id ?? "");

  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-surface-1 border border-border rounded-lg w-full max-w-md p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">
            Run automation on {count} profile{count === 1 ? "" : "s"}
          </h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300">
            <X className="h-4 w-4" />
          </button>
        </div>
        {usable.length === 0 ? (
          <div className="text-xs text-gray-400">
            No automation has a saved version yet. Create one in the Automations tab first.
          </div>
        ) : (
          <select
            value={picked}
            onChange={(e) => setPicked(e.target.value)}
            className="input w-full"
          >
            {usable.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.kind})
              </option>
            ))}
          </select>
        )}
        <div className="text-[11px] text-gray-500">
          One run is queued per profile against the automation&apos;s latest version. Counts against the tenant&apos;s automation-minutes quota.
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="btn-secondary">Cancel</button>
          <button
            onClick={() => picked && onConfirm(picked)}
            disabled={!picked}
            className="btn-primary disabled:opacity-50"
          >
            Queue runs
          </button>
        </div>
      </div>
    </div>
  );
}


interface BulkResultBannerProps {
  title: string;
  result: BulkProfileResult;
  onDismiss: () => void;
}

export function BulkResultBanner({ title, result, onDismiss }: BulkResultBannerProps) {
  return (
    <div className="fixed top-4 right-4 z-40 max-w-md bg-surface-1 border border-border rounded-lg shadow-lg p-3 space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold">{title}</h4>
        <button onClick={onDismiss} className="text-gray-500 hover:text-gray-300">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="text-xs text-gray-300">
        <span className="text-emerald-400">{result.succeeded} ok</span>
        {result.failed > 0 && (
          <span className="text-red-400 ml-2">{result.failed} failed</span>
        )}
      </div>
      {result.failed > 0 && (
        <ul className="text-[11px] text-gray-400 max-h-32 overflow-y-auto space-y-0.5">
          {result.results
            .filter((r) => !r.ok)
            .slice(0, 5)
            .map((r) => (
              <li key={r.profile_id} className="truncate">
                <span className="text-red-400">✗</span> {r.profile_id.slice(0, 8)}…: {r.error}
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
