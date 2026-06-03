import { useCallback, useEffect, useState } from "react";
import { useAutomations } from "../hooks/useAutomations";
import { AutomationList } from "./AutomationList";
import { AutomationForm } from "./AutomationForm";
import { RunViewer } from "./RunViewer";
import {
  automation as automationApi,
  schedule as scheduleApi,
  webhooks as webhookApi,
  type Automation,
  type AutomationCreateInput,
  type AutomationRun,
  type AutomationUpdateInput,
} from "../lib/automation";
import { api, type Profile } from "../lib/api";

interface AutomationPageProps {
  currentWorkspaceId: string | null;
}

export function AutomationPage({ currentWorkspaceId }: AutomationPageProps) {
  const {
    automations,
    loading,
    error,
    create,
    update,
    delete: remove,
    touch,
    cancelRun,
  } = useAutomations(currentWorkspaceId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<"empty" | "create" | "edit">("empty");
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [activeRun, setActiveRun] = useState<AutomationRun | null>(null);

  // Load profiles for the "Run on profile" picker. We rely on the shared
  // ``api`` client (which injects the workspace header), so this refetches
  // whenever the workspace changes.
  useEffect(() => {
    let cancelled = false;
    api
      .listProfiles()
      .then((data) => {
        if (!cancelled) setProfiles(data);
      })
      .catch(() => {
        // Non-fatal: the picker just shows "(none)".
        if (!cancelled) setProfiles([]);
      });
    return () => {
      cancelled = true;
    };
  }, [currentWorkspaceId]);

  const selected: Automation | null =
    automations.find((a) => a.id === selectedId) ?? null;

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
    setMode("edit");
  }, []);

  const handleNew = useCallback(() => {
    setSelectedId(null);
    setMode("create");
  }, []);

  const handleCreate = useCallback(
    async (data: AutomationCreateInput) => {
      const a = await create(data);
      if (a) {
        setSelectedId(a.id);
        setMode("edit");
      }
      return a;
    },
    [create],
  );

  const handleUpdate = useCallback(
    async (data: AutomationUpdateInput) => {
      if (!selectedId) return undefined;
      return await update(selectedId, data);
    },
    [selectedId, update],
  );

  // Shared delete-with-impact-check. Fetches schedules + webhooks first so
  // the confirm dialog warns the user that those will cascade-delete (M9).
  const confirmAndDelete = useCallback(
    async (id: string, name: string) => {
      let scheduleCount = 0;
      let webhookCount = 0;
      try {
        const [schedules, hooks] = await Promise.all([
          scheduleApi.list(id),
          webhookApi.list(id),
        ]);
        scheduleCount = schedules.length;
        webhookCount = hooks.length;
      } catch {
        // Non-fatal: fall through to the basic confirm if the lookup fails.
      }
      let msg = `Delete automation "${name}"?`;
      if (scheduleCount > 0 || webhookCount > 0) {
        const parts: string[] = [];
        if (scheduleCount > 0) {
          parts.push(
            `${scheduleCount} schedule${scheduleCount === 1 ? "" : "s"}`,
          );
        }
        if (webhookCount > 0) {
          parts.push(
            `${webhookCount} webhook${webhookCount === 1 ? "" : "s"}`,
          );
        }
        msg =
          `Delete automation "${name}"?\n\n` +
          `This will permanently delete ${parts.join(" and ")} too.`;
      }
      if (!confirm(msg)) return false;
      await remove(id);
      return true;
    },
    [remove],
  );

  const handleDelete = useCallback(async () => {
    if (!selectedId) return;
    const name = automations.find((a) => a.id === selectedId)?.name ?? "";
    const ok = await confirmAndDelete(selectedId, name);
    if (ok) {
      setSelectedId(null);
      setMode("empty");
    }
  }, [selectedId, automations, confirmAndDelete]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-gray-500 text-sm">Loading automations...</div>
      </div>
    );
  }

  return (
    <div className="h-full flex">
      <div className="w-80 border-r border-border bg-surface-1 flex-shrink-0 overflow-y-auto">
        <AutomationList
          automations={automations}
          selectedId={selectedId}
          onSelect={handleSelect}
          onNew={handleNew}
          onDelete={(id) => {
            const name = automations.find((a) => a.id === id)?.name ?? "";
            void confirmAndDelete(id, name).then((ok) => {
              if (ok && id === selectedId) {
                setSelectedId(null);
                setMode("empty");
              }
            });
          }}
        />
      </div>
      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="px-4 py-2 bg-red-600/15 border-b border-red-600/30 text-red-400 text-sm">
            {error}
          </div>
        )}
        {mode === "empty" && (
          <div className="flex items-center justify-center h-full">
            <p className="text-gray-500 text-sm">
              Select an automation or create a new one
            </p>
          </div>
        )}
        {mode === "create" && (
          <AutomationForm
            automation={null}
            profiles={profiles}
            onCreate={handleCreate}
            onUpdate={handleUpdate}
            onCancel={() => setMode("empty")}
            onOpenRun={setActiveRun}
          />
        )}
        {mode === "edit" && selected && (
          <AutomationForm
            key={selected.id}
            automation={selected}
            profiles={profiles}
            onCreate={handleCreate}
            onUpdate={handleUpdate}
            onDelete={handleDelete}
            onCancel={() => {
              setSelectedId(null);
              setMode("empty");
            }}
            onVersionSaved={(a) => touch(a)}
            onOpenRun={setActiveRun}
          />
        )}
      </div>
      {activeRun && (
        <RunViewer
          run={activeRun}
          onClose={() => setActiveRun(null)}
          onRefresh={async () => {
            try {
              const fresh = await automationApi.getRun(activeRun.id);
              setActiveRun(fresh);
            } catch {
              // Surface failures silently in the modal — the run state will
              // simply stay stale until the user retries.
            }
          }}
          onCancel={async () => {
            const ok = await cancelRun(activeRun.id);
            if (!ok) return;
            try {
              const fresh = await automationApi.getRun(activeRun.id);
              setActiveRun(fresh);
            } catch {
              // Same fallthrough as the refresh handler above.
            }
          }}
        />
      )}
    </div>
  );
}
