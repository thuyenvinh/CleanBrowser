import { useCallback, useEffect, useState } from "react";
import { versions as api, type ProfileVersion, VersionsApiError } from "../lib/versions";

export function useProfileVersions(profileId: string | null) {
  const [list, setList] = useState<ProfileVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unsupported, setUnsupported] = useState(false);

  const refresh = useCallback(async () => {
    if (!profileId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.list(profileId);
      setList(data);
      setUnsupported(false);
    } catch (e) {
      if (e instanceof VersionsApiError && e.status === 404) {
        setUnsupported(true);
        setList([]);
      } else if (e instanceof Error) {
        setError(e.message);
      }
    } finally {
      setLoading(false);
    }
  }, [profileId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const restore = useCallback(
    async (versionId: string) => {
      if (!profileId) return false;
      try {
        await api.restore(profileId, versionId);
        return true;
      } catch (e) {
        if (e instanceof VersionsApiError && e.status === 404) {
          setUnsupported(true);
        }
        setError(e instanceof Error ? e.message : "Restore failed");
        return false;
      }
    },
    [profileId],
  );

  return { versions: list, loading, error, unsupported, refresh, restore };
}
