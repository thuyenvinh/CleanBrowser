import { useState } from "react";
import { Loader2, Pencil, Play, Plus, Search, Trash2 } from "lucide-react";
import type { Proxy, ProxyStatus } from "../lib/proxy";

interface ProxyListProps {
  proxies: Proxy[];
  selectedId: string | null;
  testingId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onTest: (id: string) => void;
  onDelete: (id: string) => void;
}

const STATUS_CLASS: Record<ProxyStatus, string> = {
  ok: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  fail: "bg-red-500/15 text-red-400 border-red-500/30",
  unchecked: "bg-gray-500/15 text-gray-400 border-gray-500/30",
};

function StatusBadge({ status }: { status: ProxyStatus }) {
  return (
    <span
      className={`inline-block text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border ${STATUS_CLASS[status]}`}
    >
      {status}
    </span>
  );
}

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n - 1) + "..." : s;
}

function formatLastCheck(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  const diff = Date.now() - d.getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function ProxyList({
  proxies,
  selectedId,
  testingId,
  onSelect,
  onNew,
  onTest,
  onDelete,
}: ProxyListProps) {
  const [search, setSearch] = useState("");
  const q = search.toLowerCase();
  const filtered = proxies.filter(
    (p) =>
      p.name.toLowerCase().includes(q) ||
      p.host.toLowerCase().includes(q) ||
      (p.provider ?? "").toLowerCase().includes(q),
  );

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-4 border-b border-border">
        <div>
          <h2 className="text-sm font-semibold">Proxy Pool</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            {proxies.length} {proxies.length === 1 ? "proxy" : "proxies"}
          </p>
        </div>
        <button
          onClick={onNew}
          className="btn-primary flex items-center gap-1.5"
        >
          <Plus className="h-3.5 w-3.5" />
          <span>New Proxy</span>
        </button>
      </div>

      <div className="px-4 pt-3">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
          <input
            type="text"
            placeholder="Search by name, host, provider..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input pl-8 py-1.5 text-xs"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {filtered.length === 0 ? (
          <div className="text-center text-gray-500 text-xs py-12">
            {proxies.length === 0
              ? "No proxies yet. Click \"New Proxy\" to add one."
              : "No matches"}
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-gray-500">
              <tr className="text-left">
                <th className="font-medium pb-2 px-2">Name</th>
                <th className="font-medium pb-2 px-2">Provider</th>
                <th className="font-medium pb-2 px-2">Host:Port</th>
                <th className="font-medium pb-2 px-2">Status</th>
                <th className="font-medium pb-2 px-2">Latency</th>
                <th className="font-medium pb-2 px-2">Country</th>
                <th className="font-medium pb-2 px-2">Last Check</th>
                <th className="font-medium pb-2 px-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p) => {
                const selected = p.id === selectedId;
                const isTesting = testingId === p.id;
                return (
                  <tr
                    key={p.id}
                    onClick={() => onSelect(p.id)}
                    className={`cursor-pointer border-t border-border/50 ${
                      selected ? "bg-surface-3" : "hover:bg-surface-2"
                    }`}
                  >
                    <td className="py-2 px-2 font-medium text-gray-100">
                      {p.name}
                    </td>
                    <td className="py-2 px-2 text-gray-400">
                      {p.provider ?? "-"}
                    </td>
                    <td className="py-2 px-2 text-gray-400 font-mono">
                      <span className="uppercase text-[10px] text-gray-500 mr-1">
                        {p.type}
                      </span>
                      {p.host}:{p.port}
                    </td>
                    <td className="py-2 px-2">
                      <div className="flex flex-col gap-1">
                        <StatusBadge status={p.status} />
                        {p.status === "fail" && p.last_error && (
                          <span
                            className="text-[10px] text-red-400/80"
                            title={p.last_error}
                          >
                            {truncate(p.last_error, 50)}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-2 px-2 text-gray-400">
                      {p.status === "ok" && p.latency_ms != null
                        ? `${p.latency_ms} ms`
                        : "-"}
                    </td>
                    <td className="py-2 px-2 text-gray-400">
                      {p.country_code ?? "-"}
                    </td>
                    <td className="py-2 px-2 text-gray-400">
                      {formatLastCheck(p.last_check_at)}
                    </td>
                    <td className="py-2 px-2">
                      <div
                        className="flex items-center justify-end gap-1"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          onClick={() => onSelect(p.id)}
                          className="p-1 rounded hover:bg-surface-4 text-gray-400 hover:text-gray-200"
                          title="Edit"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => onTest(p.id)}
                          disabled={isTesting}
                          className="p-1 rounded hover:bg-surface-4 text-gray-400 hover:text-gray-200 disabled:opacity-50"
                          title="Test connection"
                        >
                          {isTesting ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Play className="h-3.5 w-3.5" />
                          )}
                        </button>
                        <button
                          onClick={() => {
                            if (confirm(`Delete proxy "${p.name}"?`)) {
                              onDelete(p.id);
                            }
                          }}
                          className="p-1 rounded hover:bg-red-600/20 text-gray-400 hover:text-red-400"
                          title="Delete"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
