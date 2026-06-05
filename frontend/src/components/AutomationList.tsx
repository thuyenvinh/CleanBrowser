import { useState } from "react";
import { Plus, Search, Trash2, Workflow } from "lucide-react";
import type { Automation, AutomationKind } from "../lib/automation";

interface AutomationListProps {
  automations: Automation[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

const KIND_CLASS: Record<AutomationKind, string> = {
  flow: "bg-indigo-500/15 text-indigo-300 border-indigo-500/30",
  script: "bg-amber-500/15 text-amber-300 border-amber-500/30",
};

function KindBadge({ kind }: { kind: AutomationKind }) {
  return (
    <span
      className={`inline-block text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border ${KIND_CLASS[kind]}`}
    >
      {kind}
    </span>
  );
}

export function AutomationList({
  automations,
  selectedId,
  onSelect,
  onNew,
  onDelete,
}: AutomationListProps) {
  const [search, setSearch] = useState("");
  const q = search.toLowerCase();
  const filtered = automations.filter(
    (a) =>
      a.name.toLowerCase().includes(q) ||
      (a.description ?? "").toLowerCase().includes(q),
  );

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-4 border-b border-border">
        <div>
          <h2 className="text-sm font-semibold flex items-center gap-1.5">
            <Workflow className="h-4 w-4" />
            Automations
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">
            {automations.length}{" "}
            {automations.length === 1 ? "automation" : "automations"}
          </p>
        </div>
        <button
          onClick={onNew}
          className="btn-primary flex items-center gap-1.5"
        >
          <Plus className="h-3.5 w-3.5" />
          <span>New</span>
        </button>
      </div>

      <div className="px-4 pt-3">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
          <input
            type="text"
            placeholder="Search by name or description..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input pl-8 py-1.5 text-xs"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {filtered.length === 0 ? (
          <div className="text-center text-gray-500 text-xs py-12">
            {automations.length === 0
              ? 'No automations yet. Click "New" to add one.'
              : "No matches"}
          </div>
        ) : (
          <ul className="space-y-1">
            {filtered.map((a) => {
              const selected = a.id === selectedId;
              return (
                <li key={a.id}>
                  <div
                    onClick={() => onSelect(a.id)}
                    className={`group cursor-pointer rounded px-3 py-2 border ${
                      selected
                        ? "bg-surface-3 border-border"
                        : "border-transparent hover:bg-surface-2"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm font-medium text-gray-100 truncate">
                            {a.name}
                          </span>
                          <KindBadge kind={a.kind} />
                        </div>
                        {a.description && (
                          <p className="text-[11px] text-gray-500 mt-0.5 line-clamp-2">
                            {a.description}
                          </p>
                        )}
                        <p className="text-[10px] text-gray-600 mt-0.5">
                          {a.latest_version_id
                            ? "has version"
                            : "no version yet"}
                        </p>
                      </div>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          if (confirm(`Delete automation "${a.name}"?`)) {
                            onDelete(a.id);
                          }
                        }}
                        className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-600/20 text-gray-400 hover:text-red-400"
                        title="Delete"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
