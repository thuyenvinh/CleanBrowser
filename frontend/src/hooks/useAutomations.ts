import { useCallback, useEffect, useState } from "react";
import {
  automation as automationApi,
  type Automation,
  type AutomationCreateInput,
  type AutomationUpdateInput,
} from "../lib/automation";

/**
 * Hook for managing the automations list of the current workspace.
 *
 * Mirrors ``useProxies``: ``currentWorkspaceId`` is a refetch trigger only;
 * server-side scoping happens via the ``X-Workspace-Id`` header injected by
 * ``lib/api`` (which ``lib/automation`` reuses).
 */
export function useAutomations(currentWorkspaceId?: string | null) {
  const [automations, setAutomations] = useState<Automation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await automationApi.list();
      setAutomations(data);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to fetch automations",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    setAutomations([]);
    refresh();
  }, [refresh, currentWorkspaceId]);

  const create = useCallback(
    async (input: AutomationCreateInput): Promise<Automation | undefined> => {
      try {
        const created = await automationApi.create(input);
        setAutomations((prev) => [created, ...prev]);
        setError(null);
        return created;
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to create automation",
        );
      }
    },
    [],
  );

  const update = useCallback(
    async (
      id: string,
      input: AutomationUpdateInput,
    ): Promise<Automation | undefined> => {
      try {
        const updated = await automationApi.update(id, input);
        setAutomations((prev) =>
          prev.map((a) => (a.id === id ? updated : a)),
        );
        setError(null);
        return updated;
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to update automation",
        );
      }
    },
    [],
  );

  const remove = useCallback(async (id: string) => {
    try {
      await automationApi.delete(id);
      setAutomations((prev) => prev.filter((a) => a.id !== id));
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to delete automation",
      );
    }
  }, []);

  // Used after createVersion to refresh ``latest_version_id`` on the row.
  const touch = useCallback((a: Automation) => {
    setAutomations((prev) => prev.map((row) => (row.id === a.id ? a : row)));
  }, []);

  return {
    automations,
    loading,
    error,
    refresh,
    create,
    update,
    delete: remove,
    touch,
  };
}
