import { useCallback, useEffect, useState } from "react";
import {
  schedule as scheduleApi,
  type Schedule,
  type ScheduleCreateInput,
  type ScheduleUpdateInput,
} from "../lib/automation";

/**
 * Hook for managing the cron schedules attached to a single automation.
 *
 * Pass ``null`` when no automation is selected (e.g. create-mode form):
 * the hook idles and exposes an empty list. When ``automationId`` flips
 * to a real id it fetches and caches the schedules; subsequent mutations
 * update local state without a refetch.
 */
export function useSchedules(automationId: string | null) {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!automationId) {
      setSchedules([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const rows = await scheduleApi.list(automationId);
      setSchedules(rows);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to fetch schedules",
      );
    } finally {
      setLoading(false);
    }
  }, [automationId]);

  useEffect(() => {
    setSchedules([]);
    if (automationId) {
      void refresh();
    }
  }, [automationId, refresh]);

  const create = useCallback(
    async (input: ScheduleCreateInput): Promise<void> => {
      if (!automationId) return;
      try {
        const created = await scheduleApi.create(automationId, input);
        setSchedules((prev) => [...prev, created]);
        setError(null);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to create schedule",
        );
        throw err;
      }
    },
    [automationId],
  );

  const update = useCallback(
    async (id: string, input: ScheduleUpdateInput): Promise<void> => {
      try {
        const updated = await scheduleApi.update(id, input);
        setSchedules((prev) =>
          prev.map((s) => (s.id === id ? updated : s)),
        );
        setError(null);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to update schedule",
        );
        throw err;
      }
    },
    [],
  );

  const remove = useCallback(async (id: string): Promise<void> => {
    try {
      await scheduleApi.delete(id);
      setSchedules((prev) => prev.filter((s) => s.id !== id));
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to delete schedule",
      );
      throw err;
    }
  }, []);

  return {
    schedules,
    loading,
    error,
    refresh,
    create,
    update,
    delete: remove,
  };
}
