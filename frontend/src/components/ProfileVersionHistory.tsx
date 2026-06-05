import { History, RotateCcw } from "lucide-react";
import { useProfileVersions } from "../hooks/useProfileVersions";

interface Props {
  profileId: string;
}

function formatBytes(n: number | null): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

function formatTime(s: string): string {
  try {
    return new Date(s).toLocaleString();
  } catch {
    return s;
  }
}

export function ProfileVersionHistory({ profileId }: Props) {
  const { versions, loading, error, unsupported, restore, refresh } =
    useProfileVersions(profileId);

  if (unsupported) {
    return (
      <div className="text-xs text-gray-500 py-3">
        Cloud snapshots are not yet enabled on this server. Configure
        STORAGE_BUCKET to start saving versions on profile stop.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-gray-400">
          <History className="h-3.5 w-3.5" /> Version history
        </div>
        <button
          type="button"
          onClick={refresh}
          className="text-xs text-gray-500 hover:text-gray-300"
        >
          Refresh
        </button>
      </div>
      {loading && <div className="text-xs text-gray-500">Loading versions...</div>}
      {error && <div className="text-xs text-red-400">{error}</div>}
      {!loading && versions.length === 0 && (
        <div className="text-xs text-gray-500 py-2">
          No snapshots yet. The first one will be created when you stop a running
          session.
        </div>
      )}
      {versions.length > 0 && (
        <div className="border border-border rounded divide-y divide-border">
          {versions.map((v) => (
            <div
              key={v.id}
              className="px-3 py-2 flex items-center justify-between text-xs"
            >
              <div>
                <div className="font-mono text-gray-300">v{v.version}</div>
                <div className="text-gray-500">
                  {formatTime(v.created_at)} · {formatBytes(v.size_bytes)}
                </div>
                {v.notes && (
                  <div className="text-gray-400 mt-1 italic">{v.notes}</div>
                )}
              </div>
              <button
                type="button"
                onClick={async () => {
                  if (
                    !confirm(
                      `Restore version ${v.version}? This will overwrite current profile data.`,
                    )
                  )
                    return;
                  const ok = await restore(v.id);
                  if (ok) alert(`Restored v${v.version}`);
                }}
                className="flex items-center gap-1 px-2 py-1 bg-surface-2 hover:bg-surface-3 rounded text-gray-300"
                title="Restore this version"
              >
                <RotateCcw className="h-3 w-3" /> Restore
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
