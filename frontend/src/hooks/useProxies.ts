import { useCallback, useEffect, useState } from "react";
import {
  proxy as proxyApi,
  type Proxy,
  type ProxyCreateInput,
  type ProxyUpdateInput,
  type ProxyTestResult,
} from "../lib/proxy";

/**
 * Hook for managing the proxy pool of the current workspace.
 *
 * Mirrors ``useProfiles``: ``currentWorkspaceId`` is a refetch trigger only;
 * server-side scoping happens via the ``X-Workspace-Id`` header injected by
 * ``lib/api`` (which ``lib/proxy`` reuses).
 */
export function useProxies(currentWorkspaceId?: string | null) {
  const [proxies, setProxies] = useState<Proxy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await proxyApi.list();
      setProxies(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch proxies");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    setProxies([]);
    refresh();
  }, [refresh, currentWorkspaceId]);

  const create = useCallback(
    async (input: ProxyCreateInput): Promise<Proxy | undefined> => {
      try {
        const created = await proxyApi.create(input);
        setProxies((prev) => [created, ...prev]);
        setError(null);
        return created;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to create proxy");
      }
    },
    [],
  );

  const update = useCallback(
    async (id: string, input: ProxyUpdateInput): Promise<Proxy | undefined> => {
      try {
        const updated = await proxyApi.update(id, input);
        setProxies((prev) => prev.map((p) => (p.id === id ? updated : p)));
        setError(null);
        return updated;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to update proxy");
      }
    },
    [],
  );

  const remove = useCallback(async (id: string) => {
    try {
      await proxyApi.delete(id);
      setProxies((prev) => prev.filter((p) => p.id !== id));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete proxy");
    }
  }, []);

  const test = useCallback(
    async (id: string): Promise<ProxyTestResult | undefined> => {
      try {
        const result = await proxyApi.test(id);
        // Reflect the test result in the row immediately. The backend also
        // persists ``status``/``latency_ms``/``last_check_at``/``last_error``,
        // so a follow-up ``refresh()`` would yield the same values — but
        // updating locally avoids waiting for the round trip.
        setProxies((prev) =>
          prev.map((p) =>
            p.id === id
              ? {
                  ...p,
                  status: result.status,
                  latency_ms: result.latency_ms ?? null,
                  country_code: result.country_code ?? p.country_code,
                  last_error: result.error ?? null,
                  last_check_at: new Date().toISOString(),
                }
              : p,
          ),
        );
        setError(null);
        return result;
      } catch (err) {
        // Re-throw so the caller can map specific status codes (e.g. 503).
        if (err instanceof Error) setError(err.message);
        throw err;
      }
    },
    [],
  );

  return {
    proxies,
    loading,
    error,
    refresh,
    create,
    update,
    delete: remove,
    test,
  };
}
