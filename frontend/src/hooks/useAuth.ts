import { useCallback, useEffect, useState } from "react";
import {
  auth,
  AuthError,
  type LoginInput,
  type SignupInput,
  type User,
  type Workspace,
} from "../lib/auth";

const WORKSPACE_KEY = "cb.currentWorkspaceId";

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [currentWorkspaceId, setCurrentWorkspaceId] = useState<string | null>(
    () => localStorage.getItem(WORKSPACE_KEY),
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const applySession = useCallback((u: User, ws: Workspace[]) => {
    setUser(u);
    setWorkspaces(ws);
    setCurrentWorkspaceId((prev) => {
      const next = prev && ws.some((w) => w.id === prev) ? prev : ws[0]?.id ?? null;
      if (next) localStorage.setItem(WORKSPACE_KEY, next);
      else localStorage.removeItem(WORKSPACE_KEY);
      return next;
    });
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const me = await auth.me();
      applySession(me.user, me.workspaces);
      setError(null);
    } catch (err) {
      if (err instanceof AuthError && err.status === 401) {
        setUser(null);
        setWorkspaces([]);
      } else {
        setError(err instanceof Error ? err.message : "Auth check failed");
      }
    } finally {
      setLoading(false);
    }
  }, [applySession]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const signup = useCallback(async (input: SignupInput) => {
    setError(null);
    const res = await auth.signup(input);
    applySession(res.user, [res.workspace]);
    return res;
  }, [applySession]);

  const login = useCallback(async (input: LoginInput) => {
    setError(null);
    const res = await auth.login(input);
    applySession(res.user, [res.workspace]);
    return res;
  }, [applySession]);

  const logout = useCallback(async () => {
    try { await auth.logout(); } catch { /* ignore */ }
    setUser(null);
    setWorkspaces([]);
    setCurrentWorkspaceId(null);
    localStorage.removeItem(WORKSPACE_KEY);
  }, []);

  const switchWorkspace = useCallback((id: string) => {
    setCurrentWorkspaceId(id);
    localStorage.setItem(WORKSPACE_KEY, id);
  }, []);

  return { user, workspaces, currentWorkspaceId, loading, error, signup, login, logout, switchWorkspace, refresh };
}
