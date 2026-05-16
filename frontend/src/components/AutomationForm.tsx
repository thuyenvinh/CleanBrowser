import { useCallback, useEffect, useMemo, useState } from "react";
import { ListChecks, Play, Save, Trash2 } from "lucide-react";
import {
  automation as automationApi,
  type Automation,
  type AutomationCreateInput,
  type AutomationDetail,
  type AutomationKind,
  type AutomationRun,
  type AutomationScriptLanguage,
  type AutomationUpdateInput,
  type AutomationVersion,
} from "../lib/automation";
import type { Profile } from "../lib/api";
import { ScheduleList } from "./ScheduleList";
import { useSchedules } from "../hooks/useSchedules";
// Agent OO owns ``./FlowEditor`` (wave 8). Once that PR lands the import
// resolves and the Visual tab below renders the graph editor. Until then
// the JSON tab still works — TypeScript will flag the import as missing,
// which is expected during the interleave window.
import { FlowEditor } from "./FlowEditor";

interface AutomationFormProps {
  automation: Automation | null; // null = create mode
  profiles: Profile[];
  onCreate: (data: AutomationCreateInput) => Promise<Automation | undefined>;
  onUpdate: (data: AutomationUpdateInput) => Promise<Automation | undefined>;
  onDelete?: () => Promise<void>;
  onCancel: () => void;
  onVersionSaved?: (a: Automation, v: AutomationVersion) => void;
  onOpenRun: (run: AutomationRun) => void;
}

const SCRIPT_LANGUAGES: AutomationScriptLanguage[] = ["python", "javascript"];

const EMPTY_DSL = `{
  "nodes": [],
  "edges": []
}`;

function detailIsCurrent(
  detail: AutomationDetail | null,
  automation: Automation | null,
): boolean {
  if (!detail || !automation) return false;
  return detail.automation.id === automation.id;
}

export function AutomationForm({
  automation,
  profiles,
  onCreate,
  onUpdate,
  onDelete,
  onCancel,
  onVersionSaved,
  onOpenRun,
}: AutomationFormProps) {
  const isEdit = automation !== null;

  // Basic fields
  const [name, setName] = useState("");
  const [kind, setKind] = useState<AutomationKind>("flow");
  const [description, setDescription] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Version editing
  const [detail, setDetail] = useState<AutomationDetail | null>(null);
  const [versionBody, setVersionBody] = useState("");
  const [scriptLanguage, setScriptLanguage] =
    useState<AutomationScriptLanguage>("python");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [versionSaving, setVersionSaving] = useState(false);
  const [versionMsg, setVersionMsg] = useState<string | null>(null);
  // Flow editor mode toggle. Visual hands off to ``FlowEditor`` (agent OO);
  // JSON edits the raw DSL text. Both write to ``versionBody`` so saving
  // is unchanged.
  const [editorMode, setEditorMode] = useState<"json" | "visual">("json");

  // Run controls
  const [selectedProfileId, setSelectedProfileId] = useState<string>("");
  const [running, setRunning] = useState(false);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  // Reset form when switching target automation.
  useEffect(() => {
    setNameError(null);
    setJsonError(null);
    setVersionMsg(null);
    setRunMsg(null);
    setRunError(null);
    if (automation) {
      setName(automation.name);
      setKind(automation.kind);
      setDescription(automation.description ?? "");
    } else {
      setName("");
      setKind("flow");
      setDescription("");
      setVersionBody(EMPTY_DSL);
      setScriptLanguage("python");
      setDetail(null);
    }
  }, [automation?.id]);

  // Load latest version detail on edit.
  useEffect(() => {
    let cancelled = false;
    if (!automation) {
      setDetail(null);
      return;
    }
    automationApi
      .get(automation.id)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
        const latest = d.versions[0];
        if (latest && latest.kind === "flow") {
          try {
            setVersionBody(JSON.stringify(latest.dsl_json ?? {}, null, 2));
          } catch {
            setVersionBody(EMPTY_DSL);
          }
        } else if (latest && latest.kind === "script") {
          setVersionBody(latest.script_code ?? "");
          if (latest.script_language) setScriptLanguage(latest.script_language);
        } else {
          setVersionBody(automation.kind === "flow" ? EMPTY_DSL : "");
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setVersionMsg(
            err instanceof Error ? err.message : "Failed to load version",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [automation?.id]);

  const validate = (): boolean => {
    if (!name.trim()) {
      setNameError("Name is required");
      return false;
    }
    setNameError(null);
    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    setSaving(true);
    try {
      if (isEdit) {
        await onUpdate({
          name: name.trim(),
          description: description.trim() ? description.trim() : null,
        });
      } else {
        await onCreate({
          name: name.trim(),
          kind,
          description: description.trim() ? description.trim() : null,
        });
      }
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!onDelete) return;
    if (!confirm("Delete this automation?")) return;
    setDeleting(true);
    try {
      await onDelete();
    } finally {
      setDeleting(false);
    }
  };

  const handleSaveVersion = useCallback(async () => {
    if (!automation) return;
    setVersionMsg(null);
    setJsonError(null);
    try {
      let payload: Parameters<typeof automationApi.createVersion>[1];
      if (automation.kind === "flow") {
        let parsed: unknown;
        try {
          parsed = JSON.parse(versionBody);
        } catch (err) {
          setJsonError(
            err instanceof Error ? err.message : "Invalid JSON",
          );
          return;
        }
        payload = { dsl_json: parsed };
      } else {
        if (!versionBody.trim()) {
          setJsonError("Script code is empty");
          return;
        }
        payload = {
          script_language: scriptLanguage,
          script_code: versionBody,
        };
      }
      setVersionSaving(true);
      const newVersion = await automationApi.createVersion(
        automation.id,
        payload,
      );
      // Refresh detail and propagate latest_version_id upward.
      const d = await automationApi.get(automation.id);
      setDetail(d);
      setVersionMsg(`Saved version ${newVersion.version}`);
      onVersionSaved?.(d.automation, newVersion);
    } catch (err) {
      setVersionMsg(
        err instanceof Error ? err.message : "Failed to save version",
      );
    } finally {
      setVersionSaving(false);
    }
  }, [automation, versionBody, scriptLanguage, onVersionSaved]);

  const handleRun = useCallback(async () => {
    if (!automation) return;
    setRunMsg(null);
    setRunError(null);
    setRunning(true);
    try {
      const res = await automationApi.run(
        automation.id,
        selectedProfileId || null,
      );
      setRunMsg(`Run queued: ${res.run_id}`);
      try {
        const run = await automationApi.getRun(res.run_id);
        onOpenRun(run);
      } catch {
        // Non-fatal: the queued ID is shown via toast.
      }
    } catch (err) {
      setRunError(
        err instanceof Error ? err.message : "Failed to queue run",
      );
    } finally {
      setRunning(false);
    }
  }, [automation, selectedProfileId, onOpenRun]);

  const handleViewRuns = useCallback(async () => {
    if (!automation) return;
    setRunError(null);
    try {
      const runs = await automationApi.listRuns(automation.id, 1, 0);
      const first = runs[0];
      if (!first) {
        setRunMsg("No runs yet.");
        return;
      }
      onOpenRun(first);
    } catch (err) {
      setRunError(
        err instanceof Error ? err.message : "Failed to load runs",
      );
    }
  }, [automation, onOpenRun]);

  const latestVersion = useMemo<AutomationVersion | null>(() => {
    if (!detailIsCurrent(detail, automation)) return null;
    return detail!.versions[0] ?? null;
  }, [detail, automation]);

  return (
    <form onSubmit={handleSubmit} className="p-6 max-w-2xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">
            {isEdit ? "Edit Automation" : "New Automation"}
          </h2>
          {isEdit && onDelete && (
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleting}
              className="btn-danger flex items-center gap-1.5"
            >
              <Trash2 className="h-3.5 w-3.5" />
              <span>{deleting ? "Deleting..." : "Delete"}</span>
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={onCancel} className="btn-secondary">
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="btn-primary flex items-center gap-1.5"
          >
            <Save className="h-3.5 w-3.5" />
            <span>{saving ? "Saving..." : isEdit ? "Save" : "Create"}</span>
          </button>
        </div>
      </div>

      <div className="space-y-6">
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
            Basic
          </h3>
          <div className="space-y-3">
            <div>
              <label className="label">Name</label>
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Daily login check"
              />
              {nameError && (
                <p className="text-xs text-red-400 mt-1">{nameError}</p>
              )}
            </div>
            <div>
              <label className="label">Kind</label>
              {isEdit ? (
                <input className="input" value={kind} disabled />
              ) : (
                <select
                  className="input"
                  value={kind}
                  onChange={(e) =>
                    setKind(e.target.value as AutomationKind)
                  }
                >
                  <option value="flow">flow (DSL)</option>
                  <option value="script">script (code)</option>
                </select>
              )}
              {isEdit && (
                <p className="text-xs text-gray-500 mt-1">
                  Kind is fixed at creation.
                </p>
              )}
            </div>
            <div>
              <label className="label">Description</label>
              <textarea
                className="input"
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="(optional)"
              />
            </div>
          </div>
        </section>

        {isEdit && automation && (
          <>
            <section>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                  Version
                </h3>
                {latestVersion ? (
                  <span className="text-[11px] text-gray-500">
                    Latest: v{latestVersion.version} (
                    {new Date(latestVersion.created_at).toLocaleString()})
                  </span>
                ) : (
                  <span className="text-[11px] text-gray-500">
                    No version yet
                  </span>
                )}
              </div>
              {automation.kind === "script" && (
                <div className="mb-2">
                  <label className="label">Language</label>
                  <select
                    className="input"
                    value={scriptLanguage}
                    onChange={(e) =>
                      setScriptLanguage(
                        e.target.value as AutomationScriptLanguage,
                      )
                    }
                  >
                    {SCRIPT_LANGUAGES.map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {automation.kind === "flow" && (
                <div className="flex items-center gap-2 mb-2">
                  <button
                    type="button"
                    onClick={() => setEditorMode("json")}
                    className={
                      editorMode === "json" ? "btn-primary" : "btn-secondary"
                    }
                  >
                    JSON
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditorMode("visual")}
                    className={
                      editorMode === "visual" ? "btn-primary" : "btn-secondary"
                    }
                  >
                    Visual
                  </button>
                </div>
              )}
              {(automation.kind !== "flow" || editorMode === "json") && (
                <textarea
                  className="input font-mono text-xs"
                  rows={14}
                  spellCheck={false}
                  value={versionBody}
                  onChange={(e) => {
                    setVersionBody(e.target.value);
                    if (automation.kind === "flow") {
                      try {
                        JSON.parse(e.target.value);
                        setJsonError(null);
                      } catch (err) {
                        setJsonError(
                          err instanceof Error ? err.message : "Invalid JSON",
                        );
                      }
                    }
                  }}
                  placeholder={
                    automation.kind === "flow"
                      ? "DSL JSON..."
                      : "Script source code..."
                  }
                />
              )}
              {automation.kind === "flow" && editorMode === "visual" && (
                <FlowEditor
                  value={(() => {
                    try {
                      return JSON.parse(versionBody);
                    } catch {
                      return { nodes: [], edges: [] };
                    }
                  })()}
                  onChange={(dsl: unknown) => {
                    setVersionBody(JSON.stringify(dsl, null, 2));
                    setJsonError(null);
                  }}
                />
              )}
              {jsonError && (
                <p className="text-xs text-red-400 mt-1">{jsonError}</p>
              )}
              {versionMsg && (
                <p className="text-xs text-gray-400 mt-1">{versionMsg}</p>
              )}
              <div className="mt-2 flex justify-end">
                <button
                  type="button"
                  onClick={handleSaveVersion}
                  disabled={versionSaving || !!jsonError}
                  className="btn-primary flex items-center gap-1.5"
                >
                  <Save className="h-3.5 w-3.5" />
                  <span>
                    {versionSaving ? "Saving..." : "Save new version"}
                  </span>
                </button>
              </div>
            </section>

            <section>
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                Run
              </h3>
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <label className="label">Profile (optional)</label>
                  <select
                    className="input"
                    value={selectedProfileId}
                    onChange={(e) => setSelectedProfileId(e.target.value)}
                  >
                    <option value="">(none)</option>
                    {profiles.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  type="button"
                  onClick={handleRun}
                  disabled={running || !latestVersion}
                  className="btn-primary flex items-center gap-1.5"
                  title={
                    latestVersion
                      ? "Queue a run"
                      : "Save a version before running"
                  }
                >
                  <Play className="h-3.5 w-3.5" />
                  <span>{running ? "Queuing..." : "Run"}</span>
                </button>
                <button
                  type="button"
                  onClick={handleViewRuns}
                  className="btn-secondary flex items-center gap-1.5"
                >
                  <ListChecks className="h-3.5 w-3.5" />
                  <span>View runs</span>
                </button>
              </div>
              {runMsg && (
                <p className="text-xs text-gray-400 mt-2">{runMsg}</p>
              )}
              {runError && (
                <p className="text-xs text-red-400 mt-2">{runError}</p>
              )}
            </section>

            <section>
              <SchedulesSection
                automationId={automation.id}
                workspaceProfiles={profiles}
              />
            </section>
          </>
        )}
      </div>
    </form>
  );
}

/**
 * Wraps ``useSchedules`` + ``ScheduleList`` for the automation edit form.
 *
 * Kept as a local helper rather than exported so the parent form stays
 * the single owner of the workspace-profile list (we just funnel it
 * through unchanged). ``useSchedules`` is keyed on ``automationId``: it
 * refetches when the user navigates between automations.
 */
function SchedulesSection({
  automationId,
  workspaceProfiles,
}: {
  automationId: string;
  workspaceProfiles: Profile[];
}) {
  const {
    schedules,
    loading,
    create,
    update,
    delete: remove,
  } = useSchedules(automationId);
  const profileOptions = useMemo(
    () => workspaceProfiles.map((p) => ({ id: p.id, name: p.name })),
    [workspaceProfiles],
  );
  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Schedules
      </h3>
      <ScheduleList
        automationId={automationId}
        schedules={schedules}
        profiles={profileOptions}
        loading={loading}
        onCreate={create}
        onUpdate={update}
        onDelete={remove}
      />
    </div>
  );
}
