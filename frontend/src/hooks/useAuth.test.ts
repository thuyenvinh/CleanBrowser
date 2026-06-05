import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useAuth } from "./useAuth";
import { AuthError } from "../lib/auth";

vi.mock("../lib/auth", async () => {
  const actual = await vi.importActual<typeof import("../lib/auth")>(
    "../lib/auth",
  );
  return {
    ...actual,
    auth: {
      signup: vi.fn(),
      login: vi.fn(),
      logout: vi.fn(),
      me: vi.fn(),
      listWorkspaces: vi.fn(),
    },
  };
});

vi.mock("../lib/api", () => ({
  setWorkspaceId: vi.fn(),
  getWorkspaceId: vi.fn(() => null),
}));

import { auth } from "../lib/auth";
import { setWorkspaceId } from "../lib/api";

const mockAuth = auth as unknown as {
  signup: ReturnType<typeof vi.fn>;
  login: ReturnType<typeof vi.fn>;
  logout: ReturnType<typeof vi.fn>;
  me: ReturnType<typeof vi.fn>;
  listWorkspaces: ReturnType<typeof vi.fn>;
};

const fakeUser = { id: "u1", email: "a@b.c", tenant_id: "t1" };
const fakeWs = { id: "w1", name: "WS One" };
const fakeWs2 = { id: "w2", name: "WS Two" };

beforeEach(() => {
  // Default: 401 (not logged in) so initial render lands at loading=false / user=null.
  mockAuth.me.mockRejectedValue(new AuthError(401, "Unauthorized"));
  mockAuth.listWorkspaces.mockResolvedValue([]);
  mockAuth.logout.mockResolvedValue(undefined);
  try {
    localStorage.clear();
  } catch {
    /* jsdom always provides localStorage */
  }
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useAuth", () => {
  it("starts with loading=true and user=null", () => {
    const { result } = renderHook(() => useAuth());
    expect(result.current.loading).toBe(true);
    expect(result.current.user).toBeNull();
  });

  it("on mount, fetches /me and sets user when authenticated", async () => {
    mockAuth.me.mockResolvedValue({ user: fakeUser, workspaces: [fakeWs] });
    mockAuth.listWorkspaces.mockResolvedValue([fakeWs]);

    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toEqual(fakeUser);
    expect(result.current.workspaces).toEqual([fakeWs]);
    expect(result.current.currentWorkspaceId).toBe("w1");
  });

  it("on 401, user stays null and no error is surfaced", async () => {
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("signup sets user + workspaces", async () => {
    mockAuth.signup.mockResolvedValue({
      user: fakeUser,
      workspaces: [fakeWs],
    });

    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.signup({ email: "a@b.c", password: "x" });
    });

    expect(result.current.user).toEqual(fakeUser);
    expect(result.current.workspaces).toEqual([fakeWs]);
    expect(result.current.currentWorkspaceId).toBe("w1");
  });

  it("login sets user", async () => {
    mockAuth.login.mockResolvedValue({
      user: fakeUser,
      workspaces: [fakeWs, fakeWs2],
    });

    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.login({ email: "a@b.c", password: "x" });
    });

    expect(result.current.user).toEqual(fakeUser);
    expect(result.current.workspaces).toHaveLength(2);
  });

  it("logout clears user", async () => {
    mockAuth.me.mockResolvedValue({ user: fakeUser, workspaces: [fakeWs] });
    mockAuth.listWorkspaces.mockResolvedValue([fakeWs]);

    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.user).toEqual(fakeUser));

    await act(async () => {
      await result.current.logout();
    });

    expect(result.current.user).toBeNull();
    expect(result.current.workspaces).toEqual([]);
    expect(result.current.currentWorkspaceId).toBeNull();
  });

  it("switchWorkspace updates currentWorkspaceId + localStorage + api header", async () => {
    mockAuth.me.mockResolvedValue({
      user: fakeUser,
      workspaces: [fakeWs, fakeWs2],
    });
    mockAuth.listWorkspaces.mockResolvedValue([fakeWs, fakeWs2]);

    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.user).toEqual(fakeUser));

    act(() => {
      result.current.switchWorkspace("w2");
    });

    expect(result.current.currentWorkspaceId).toBe("w2");
    expect(localStorage.getItem("cb.currentWorkspaceId")).toBe("w2");
    expect(setWorkspaceId).toHaveBeenCalledWith("w2");
  });
});
