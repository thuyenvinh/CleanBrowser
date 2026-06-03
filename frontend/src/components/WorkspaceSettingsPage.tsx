import { useEffect, useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { workspaces as workspacesApi } from "../lib/workspaces";
import { auth, type Workspace } from "../lib/auth";
import { WorkspaceMembersTab } from "./WorkspaceMembersTab";

type Tab = "general" | "members" | "danger";

interface WorkspaceSettingsPageProps {
  workspace: Workspace;
  /** Called after a successful rename / delete so the parent can refetch. */
  onChanged: () => void;
  onClose: () => void;
}

/**
 * Modal containing the per-workspace admin surface: rename in General, member
 * CRUD in Members, and a confirm-by-typing deletion flow in Danger Zone.
 *
 * Rendering as an overlay keeps this isolated from App.tsx's tab system — the
 * caller just toggles ``open`` via state held in ``WorkspaceSelector``.
 */
export function WorkspaceSettingsPage({
  workspace,
  onChanged,
  onClose,
}: WorkspaceSettingsPageProps) {
  const [tab, setTab] = useState<Tab>("general");
  const [currentUserId, setCurrentUserId] = useState<string>("");

  useEffect(() => {
    // Single fetch — the selector already has the workspace list but doesn't
    // expose the caller's user id. Cheap enough to grab here on open.
    let cancelled = false;
    auth
      .me()
      .then((res) => {
        if (!cancelled) setCurrentUserId(res.user.id);
      })
      .catch(() => {
        /* membership table still renders; "self" detection just degrades */
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const [name, setName] = useState(workspace.name);
  const [saving, setSaving] = useState(false);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [generalNotice, setGeneralNotice] = useState<string | null>(null);

  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const role = workspace.role;
  const canMutate = role === "owner" || role === "admin";
  const canDelete = role === "owner";

  const handleRename = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || name.trim() === workspace.name) return;
    setSaving(true);
    setGeneralError(null);
    setGeneralNotice(null);
    try {
      await workspacesApi.rename(workspace.id, name.trim());
      setGeneralNotice("Workspace renamed.");
      onChanged();
    } catch (err) {
      setGeneralError(
        err instanceof Error ? err.message : "Failed to rename workspace",
      );
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (confirmText !== workspace.name) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await workspacesApi.delete(workspace.id);
      onChanged();
      onClose();
    } catch (err) {
      setDeleteError(
        err instanceof Error ? err.message : "Failed to delete workspace",
      );
      setDeleting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto bg-surface-1 border border-border rounded-lg shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-gray-500">
              Workspace settings
            </div>
            <div className="text-sm text-gray-100 font-medium">
              {workspace.name}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="h-7 w-7 inline-flex items-center justify-center rounded text-gray-400 hover:text-gray-100 hover:bg-surface-2"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex gap-1 px-5 pt-3 border-b border-border">
          {(
            [
              { id: "general", label: "General" },
              { id: "members", label: "Members" },
              { id: "danger", label: "Danger Zone" },
            ] as { id: Tab; label: string }[]
          ).map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={
                "px-3 py-2 text-xs rounded-t border-b-2 " +
                (tab === t.id
                  ? "text-gray-100 border-accent"
                  : "text-gray-400 border-transparent hover:text-gray-200")
              }
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="p-5">
          {tab === "general" && (
            <form onSubmit={handleRename} className="space-y-3 max-w-md">
              <div>
                <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">
                  Workspace name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  disabled={!canMutate}
                  className="w-full h-8 px-2 rounded bg-surface-2 border border-border text-xs text-gray-100 disabled:opacity-60"
                />
              </div>
              {!canMutate && (
                <div className="text-xs text-gray-500">
                  Only owners and admins can rename a workspace.
                </div>
              )}
              {generalError && (
                <div className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded px-3 py-2">
                  {generalError}
                </div>
              )}
              {generalNotice && (
                <div className="text-xs text-green-400 bg-green-950/30 border border-green-900 rounded px-3 py-2">
                  {generalNotice}
                </div>
              )}
              <button
                type="submit"
                disabled={
                  !canMutate ||
                  saving ||
                  !name.trim() ||
                  name.trim() === workspace.name
                }
                className="h-8 px-3 rounded bg-accent hover:bg-accent/80 disabled:opacity-50 text-xs text-white"
              >
                {saving ? "Saving…" : "Save changes"}
              </button>
            </form>
          )}

          {tab === "members" && (
            <WorkspaceMembersTab
              workspaceId={workspace.id}
              currentUserId={currentUserId}
            />
          )}

          {tab === "danger" && (
            <div className="space-y-4">
              <div className="rounded-md border border-red-900 bg-red-950/30 p-4 space-y-3">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 text-red-400 mt-0.5" />
                  <div>
                    <div className="text-sm text-red-200 font-medium">
                      Delete this workspace
                    </div>
                    <div className="text-xs text-gray-400 mt-1">
                      Permanently delete <strong>{workspace.name}</strong>{" "}
                      along with its profiles, proxies, automations, runs, and
                      member list. This cannot be undone.
                    </div>
                  </div>
                </div>
                {!canDelete ? (
                  <div className="text-xs text-gray-500">
                    Only the workspace owner can delete it.
                  </div>
                ) : (
                  <>
                    <label className="block text-[10px] uppercase tracking-wide text-gray-500">
                      Type <span className="text-gray-200">{workspace.name}</span>{" "}
                      to confirm
                    </label>
                    <input
                      type="text"
                      value={confirmText}
                      onChange={(e) => setConfirmText(e.target.value)}
                      className="w-full h-8 px-2 rounded bg-surface-2 border border-border text-xs text-gray-100"
                    />
                    {deleteError && (
                      <div className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded px-3 py-2">
                        {deleteError}
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={handleDelete}
                      disabled={deleting || confirmText !== workspace.name}
                      className="h-8 px-3 rounded bg-red-600 hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed text-xs text-white"
                    >
                      {deleting ? "Deleting…" : "Delete workspace"}
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
