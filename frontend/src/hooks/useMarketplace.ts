import { useCallback, useEffect, useState } from "react";
import {
  marketplace,
  marketplaceAdmin,
  type MarketplaceApp,
  type MarketplaceAppSubmit,
  type PendingMarketplaceApp,
  type TenantAppInstall,
} from "../lib/marketplace";

/**
 * Hook for browsing marketplace apps + tracking which ones are installed in
 * the current workspace.
 *
 * Mirrors useProxies / useAutomations: ``currentWorkspaceId`` is a refetch
 * trigger only; server-side scoping happens via the ``X-Workspace-Id`` header
 * injected by ``lib/api`` (which ``lib/marketplace`` reuses).
 */
export function useMarketplace(currentWorkspaceId?: string | null) {
  const [apps, setApps] = useState<MarketplaceApp[]>([]);
  const [installs, setInstalls] = useState<TenantAppInstall[]>([]);
  const [category, setCategory] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (cat?: string | null) => {
    try {
      const [appList, installList] = await Promise.all([
        marketplace.listApps(cat ?? undefined),
        marketplace.listInstalls().catch(() => [] as TenantAppInstall[]),
      ]);
      setApps(appList);
      setInstalls(installList);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load marketplace");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    setApps([]);
    setInstalls([]);
    refresh(category);
  }, [refresh, currentWorkspaceId, category]);

  const install = useCallback(
    async (appId: string): Promise<TenantAppInstall | undefined> => {
      try {
        const created = await marketplace.install(
          appId,
          currentWorkspaceId ?? undefined,
        );
        setInstalls((prev) => [created, ...prev]);
        // Bump install_count locally so the card reflects the change without
        // a full refetch.
        setApps((prev) =>
          prev.map((a) =>
            a.id === appId ? { ...a, install_count: a.install_count + 1 } : a,
          ),
        );
        setError(null);
        return created;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to install app");
      }
    },
    [currentWorkspaceId],
  );

  const uninstall = useCallback(async (installId: string) => {
    try {
      const removed = installs.find((i) => i.id === installId);
      await marketplace.uninstall(installId);
      setInstalls((prev) => prev.filter((i) => i.id !== installId));
      if (removed) {
        setApps((prev) =>
          prev.map((a) =>
            a.id === removed.app_id
              ? { ...a, install_count: Math.max(0, a.install_count - 1) }
              : a,
          ),
        );
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to uninstall app");
    }
  }, [installs]);

  const submit = useCallback(
    async (input: MarketplaceAppSubmit): Promise<MarketplaceApp | undefined> => {
      try {
        const created = await marketplace.submit(input);
        // Submission lands in 'pending' so it doesn't appear in the public
        // listing — no need to splice it into ``apps``. Just clear errors so
        // the dialog can close cleanly.
        setError(null);
        return created;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to submit app");
        throw err;
      }
    },
    [],
  );

  return {
    apps,
    installs,
    category,
    setCategory,
    loading,
    error,
    refresh,
    install,
    uninstall,
    submit,
  };
}

/**
 * Hook for the admin moderation queue.
 *
 * Mirrors :func:`useMarketplace` shape (loading/error/refresh) so the
 * AdminModerationPage can render with the same skeleton patterns. Approve
 * and reject auto-refresh — the queue is short enough (≤ pending +
 * recently-rejected) that a full reload is cheaper than reconciling diffs.
 *
 * Phase 6 known limitation: backend gates these routes on bare auth, so any
 * authenticated user sees the queue. Phase 7+ should introduce a
 * platform-admin role and tighten the route + the link in MarketplacePage.
 */
export function useAdminPending() {
  const [apps, setApps] = useState<PendingMarketplaceApp[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      const list = await marketplaceAdmin.listPending();
      setApps(list);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load moderation queue",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const approve = useCallback(
    async (id: string, notes?: string) => {
      try {
        await marketplaceAdmin.approve(id, notes);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to approve app");
        throw err;
      }
    },
    [refresh],
  );

  const reject = useCallback(
    async (id: string, notes: string) => {
      try {
        await marketplaceAdmin.reject(id, notes);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to reject app");
        throw err;
      }
    },
    [refresh],
  );

  return { apps, loading, error, refresh, approve, reject };
}
