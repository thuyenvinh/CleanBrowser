import { useCallback, useEffect, useState } from "react";
import { apiKeys, type ApiKey, type ApiKeyCreateResult } from "../lib/apikeys";

export function useApiKeys() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiKeys.list();
      setKeys(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load API keys");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const create = useCallback(
    async (name: string, scopes?: string[]): Promise<ApiKeyCreateResult | null> => {
      setError(null);
      try {
        const result = await apiKeys.create(name, scopes);
        // Prepend the new key so it shows up at the top of the list. The
        // plaintext token itself stays in the caller's hand (modal), not in
        // the shared list state.
        setKeys((prev) => [result.key, ...prev]);
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to create API key");
        return null;
      }
    },
    [],
  );

  const revoke = useCallback(async (id: string) => {
    setError(null);
    try {
      await apiKeys.revoke(id);
      // Optimistically stamp the row as revoked rather than removing it — the
      // user may want to see the audit trail of revoked keys.
      setKeys((prev) =>
        prev.map((k) =>
          k.id === id && !k.revoked_at
            ? { ...k, revoked_at: new Date().toISOString() }
            : k,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to revoke API key");
    }
  }, []);

  return { keys, loading, error, refresh, create, revoke };
}
