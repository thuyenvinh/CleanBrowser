import { useCallback, useEffect, useState } from "react";
import {
  workspaces as workspacesApi,
  type WorkspaceMember,
  type WorkspaceRole,
} from "../lib/workspaces";

/**
 * Hook for managing the members of a single workspace.
 *
 * Refetches whenever ``workspaceId`` changes. All mutating helpers return the
 * resulting record (or ``undefined`` on failure) and surface the error message
 * via ``error``.
 */
export function useWorkspaceMembers(workspaceId: string | null) {
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!workspaceId) {
      setMembers([]);
      setLoading(false);
      return;
    }
    try {
      const ws = await workspacesApi.get(workspaceId);
      setMembers(ws.members ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch members");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    setLoading(true);
    setMembers([]);
    refresh();
  }, [refresh]);

  const invite = useCallback(
    async (
      email: string,
      role: WorkspaceRole,
    ): Promise<WorkspaceMember | undefined> => {
      if (!workspaceId) return;
      try {
        const created = await workspacesApi.invite(workspaceId, email, role);
        // Backend may omit ``created_at`` on the invite response — refetch to
        // keep the rendered table consistent.
        await refresh();
        setError(null);
        return created;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to invite member");
      }
    },
    [workspaceId, refresh],
  );

  const updateRole = useCallback(
    async (
      userId: string,
      role: WorkspaceRole,
    ): Promise<WorkspaceMember | undefined> => {
      if (!workspaceId) return;
      try {
        const updated = await workspacesApi.updateRole(
          workspaceId,
          userId,
          role,
        );
        setMembers((prev) =>
          prev.map((m) => (m.user_id === userId ? { ...m, role } : m)),
        );
        setError(null);
        return updated;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to update role");
      }
    },
    [workspaceId],
  );

  const remove = useCallback(
    async (userId: string): Promise<boolean> => {
      if (!workspaceId) return false;
      try {
        await workspacesApi.removeMember(workspaceId, userId);
        setMembers((prev) => prev.filter((m) => m.user_id !== userId));
        setError(null);
        return true;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to remove member");
        return false;
      }
    },
    [workspaceId],
  );

  return {
    members,
    loading,
    error,
    refresh,
    invite,
    updateRole,
    remove,
    clearError: () => setError(null),
  };
}
