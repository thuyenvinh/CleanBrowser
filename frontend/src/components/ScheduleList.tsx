/**
 * Table of automation schedules with inline create/edit form.
 *
 * TEMP LOCAL TYPES: ``Schedule``, ``ScheduleCreateInput`` and
 * ``ScheduleUpdateInput`` are duplicated here because Agent JJ has not yet
 * landed ``lib/automation.ts``. Once that module exists, replace the local
 * declarations with:
 *
 *     import type {
 *       Schedule,
 *       ScheduleCreateInput,
 *       ScheduleUpdateInput,
 *     } from "../lib/automation";
 *
 * and delete the local versions.
 */
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { ScheduleForm } from "./ScheduleForm";

// --- TEMP LOCAL TYPES (replace with import from "../lib/automation") --------
export interface Schedule {
  id: string;
  automation_id: string;
  profile_id?: string | null;
  cron: string;
  timezone: string;
  enabled: boolean;
  next_fire_at?: string | null;
  last_fire_at?: string | null;
  created_at: string;
}

export interface ScheduleCreateInput {
  cron: string;
  profile_id?: string | null;
  timezone?: string;
  enabled?: boolean;
}

export type ScheduleUpdateInput = Partial<ScheduleCreateInput>;
// ---------------------------------------------------------------------------

interface ScheduleListProps {
  automationId: string;
  schedules: Schedule[];
  profiles: { id: string; name: string }[];
  loading?: boolean;
  onCreate: (input: ScheduleCreateInput) => Promise<void>;
  onUpdate: (id: string, input: ScheduleUpdateInput) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

type Mode =
  | { kind: "none" }
  | { kind: "create" }
  | { kind: "edit"; id: string };

function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export function ScheduleList({
  automationId,
  schedules,
  profiles,
  loading,
  onCreate,
  onUpdate,
  onDelete,
}: ScheduleListProps) {
  const [mode, setMode] = useState<Mode>({ kind: "none" });

  const profileNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const p of profiles) m.set(p.id, p.name);
    return m;
  }, [profiles]);

  const editingSchedule =
    mode.kind === "edit"
      ? schedules.find((s) => s.id === mode.id) ?? null
      : null;

  const handleCreate = async (input: ScheduleCreateInput | ScheduleUpdateInput) => {
    // In create mode the form always supplies cron; cast is safe.
    await onCreate(input as ScheduleCreateInput);
    setMode({ kind: "none" });
  };

  const handleUpdate = async (
    id: string,
    input: ScheduleCreateInput | ScheduleUpdateInput,
  ) => {
    await onUpdate(id, input);
    setMode({ kind: "none" });
  };

  const handleDelete = async (id: string) => {
    await onDelete(id);
    setMode({ kind: "none" });
  };

  const toggleEnabled = async (s: Schedule) => {
    await onUpdate(s.id, { enabled: !s.enabled });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Schedules</h2>
        {mode.kind === "none" && (
          <button
            type="button"
            onClick={() => setMode({ kind: "create" })}
            className="btn-primary flex items-center gap-1.5"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>Add schedule</span>
          </button>
        )}
      </div>

      {mode.kind === "create" && (
        <ScheduleForm
          automationId={automationId}
          schedule={null}
          profiles={profiles}
          onSave={handleCreate}
          onCancel={() => setMode({ kind: "none" })}
        />
      )}

      {mode.kind === "edit" && editingSchedule && (
        <ScheduleForm
          automationId={automationId}
          schedule={editingSchedule}
          profiles={profiles}
          onSave={(input) => handleUpdate(editingSchedule.id, input)}
          onDelete={() => handleDelete(editingSchedule.id)}
          onCancel={() => setMode({ kind: "none" })}
        />
      )}

      {loading ? (
        <p className="text-xs text-gray-500">Loading...</p>
      ) : schedules.length === 0 ? (
        <div className="border border-border border-dashed rounded p-6 text-center">
          <p className="text-sm text-gray-400">
            No schedules. Add one to run on a cron timer.
          </p>
        </div>
      ) : (
        <div className="border border-border rounded overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-surface-0">
              <tr className="text-left text-xs uppercase text-gray-400">
                <th className="px-3 py-2 font-medium">Cron</th>
                <th className="px-3 py-2 font-medium">Timezone</th>
                <th className="px-3 py-2 font-medium">Profile</th>
                <th className="px-3 py-2 font-medium">Enabled</th>
                <th className="px-3 py-2 font-medium">Next fire</th>
                <th className="px-3 py-2 font-medium">Last fire</th>
                <th className="px-3 py-2 font-medium w-px">Actions</th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((s) => {
                const isEditingThis =
                  mode.kind === "edit" && mode.id === s.id;
                return (
                  <tr
                    key={s.id}
                    onClick={() => {
                      if (mode.kind === "none")
                        setMode({ kind: "edit", id: s.id });
                    }}
                    className={`border-t border-border cursor-pointer hover:bg-surface-0 ${
                      isEditingThis ? "bg-surface-0" : ""
                    }`}
                  >
                    <td className="px-3 py-2 font-mono text-xs">{s.cron}</td>
                    <td className="px-3 py-2 text-xs">{s.timezone}</td>
                    <td className="px-3 py-2 text-xs">
                      {s.profile_id
                        ? profileNameById.get(s.profile_id) ?? s.profile_id
                        : "—"}
                    </td>
                    <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                      <label className="inline-flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={s.enabled}
                          onChange={() => void toggleEnabled(s)}
                        />
                        <span className="text-xs text-gray-400">
                          {s.enabled ? "on" : "off"}
                        </span>
                      </label>
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-400">
                      {formatTime(s.next_fire_at)}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-400">
                      {formatTime(s.last_fire_at)}
                    </td>
                    <td
                      className="px-3 py-2"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setMode({ kind: "edit", id: s.id })}
                          className="text-gray-400 hover:text-gray-200 p-1"
                          title="Edit"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            if (confirm("Delete this schedule?"))
                              void handleDelete(s.id);
                          }}
                          className="text-gray-400 hover:text-red-400 p-1"
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
        </div>
      )}
    </div>
  );
}
