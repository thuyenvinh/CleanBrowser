import { useCallback, useEffect, useRef, useState } from "react";
import {
  auth,
  AuthError,
  type LoginInput,
  type SignupInput,
  type User,
  type Workspace,
} from "../lib/auth";
import { setWorkspaceId } from "../lib/api";

const WORKSPACE_KEY = "cb.currentWorkspaceId";

function readStoredWorkspace(): string | null {
  try {
    return localStorage.getItem(WORKSPACE_KEY);
  } catch {
    return null;
  }
}

function persistWorkspace(id: string | null) {
  try {
    if (id) localStorage.setItem(WORKSPACE_KEY, id);
    else localStorage.removeItem(WORKSPACE_KEY);
  } catch {
    // localStorage may be unavailable (private mode etc.) — ignore.
  }
}

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [currentWorkspaceId, setCurrentWorkspaceId] = useState<string | null>(
    () => readStoredWorkspace(),
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Mirror of ``workspaces`` for synchronous access inside callbacks that
  // don't want to take it as a dep (e.g. ``switchWorkspace``).
  const workspacesRef = useRef<Workspace[]>([]);
  workspacesRef.current = workspaces;

  /**
   * Apply a freshly-fetched session: pick a current workspace (preserve the
   * persisted one if still valid, otherwise fall back to the first), and
   * sync localStorage + the API client header.
   */
  const applySession = useCallback((u: User, ws: Workspace[]) => {
    setUser(u);
    setWorkspaces(ws);
    setCurrentWorkspaceId((prev) => {
      const stored = prev ?? readStoredWorkspace();
      const next =
        stored && ws.some((w) => w.id === stored) ? stored : ws[0]?.id ?? null;
      persistWorkspace(next);
      setWorkspaceId(next);
      return next;
    });
  }, []);

  const clearSession = useCallback(() => {
    setUser(null);
    setWorkspaces([]);
    setCurrentWorkspaceId(null);
    persistWorkspace(null);
    setWorkspaceId(null);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const me = await auth.me();
      // Prefer the dedicated /api/workspaces endpoint (richer fields like
      // ``role``); fall back to whatever ``/api/auth/me`` returned.
      let ws: Workspace[] = me.workspaces;
      try {
        ws = await auth.listWorkspaces();
      } catch {
        // Falling back to me.workspaces is fine; the user is still
        // authenticated and we have at least the id/name we need.
      }
      applySession(me.user, ws);
      setError(null);
    } catch (err) {
      if (err instanceof AuthError && err.status === 401) {
        clearSession();
      } else {
        setError(err instanceof Error ? err.message : "Auth check failed");
      }
    } finally {
      setLoading(false);
    }
  }, [applySession, clearSession]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const signup = useCallback(
    async (input: SignupInput) => {
      setError(null);
      const res = await auth.signup(input);
      applySession(res.user, res.workspaces);
      return res;
    },
    [applySession],
  );

  const login = useCallback(
    async (input: LoginInput) => {
      setError(null);
      const res = await auth.login(input);
      applySession(res.user, res.workspaces);
      return res;
    },
    [applySession],
  );

  const logout = useCallback(async () => {
    try {
      await auth.logout();
    } catch {
      /* ignore — clear local state regardless */
    }
    clearSession();
  }, [clearSession]);

  const switchWorkspace = useCallback((id: string) => {
    if (!workspacesRef.current.some((w) => w.id === id)) {
      throw new Error(`Unknown workspace id: ${id}`);
    }
    setCurrentWorkspaceId(id);
    persistWorkspace(id);
    setWorkspaceId(id);
  }, []);

  return {
    user,
    workspaces,
    currentWorkspaceId,
    loading,
    error,
    signup,
    login,
    logout,
    switchWorkspace,
    refresh,
  };
}
