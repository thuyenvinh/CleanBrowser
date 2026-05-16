import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Layers } from "lucide-react";
import type { Workspace } from "../lib/auth";

interface WorkspaceSelectorProps {
  workspaces: Workspace[];
  currentWorkspaceId: string | null;
  onSwitch: (id: string) => void;
}

export function WorkspaceSelector({
  workspaces,
  currentWorkspaceId,
  onSwitch,
}: WorkspaceSelectorProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  // Nothing to render until the auth bootstrap has fetched the workspace
  // list — avoids flashing a stale placeholder. All hooks must be called
  // before this early return.
  if (workspaces.length === 0) return null;
  const current: Workspace =
    workspaces.find((w) => w.id === currentWorkspaceId) ?? workspaces[0]!;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 h-7 px-2 rounded-md bg-surface-2 hover:bg-surface-3 border border-border text-xs text-gray-200"
        title="Switch workspace"
      >
        <Layers className="h-3.5 w-3.5 text-gray-500" />
        <span className="truncate max-w-[10rem]">{current.name}</span>
        <ChevronDown className="h-3 w-3 text-gray-500" />
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-56 rounded-md bg-surface-2 border border-border shadow-sm z-20 py-1">
          <div className="px-3 py-1 text-[10px] uppercase tracking-wide text-gray-500">
            Workspaces
          </div>
          {workspaces.map((w) => {
            const active = w.id === current.id;
            return (
              <button
                key={w.id}
                type="button"
                onClick={() => {
                  onSwitch(w.id);
                  setOpen(false);
                }}
                className="w-full flex items-center justify-between gap-2 px-3 py-1.5 text-xs text-gray-200 hover:bg-surface-3"
              >
                <span className="truncate">{w.name}</span>
                {active && <Check className="h-3.5 w-3.5 text-accent" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
