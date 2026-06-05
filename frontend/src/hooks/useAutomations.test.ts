import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useAutomations } from "./useAutomations";

vi.mock("../lib/automation", () => ({
  automation: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    createVersion: vi.fn(),
    run: vi.fn(),
    cancelRun: vi.fn(),
  },
}));

import { automation as automationApi } from "../lib/automation";

const mockAuto = automationApi as unknown as {
  list: ReturnType<typeof vi.fn>;
  create: ReturnType<typeof vi.fn>;
  update: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
  createVersion: ReturnType<typeof vi.fn>;
  run: ReturnType<typeof vi.fn>;
  cancelRun: ReturnType<typeof vi.fn>;
};

const fakeAutomation = {
  id: "a1",
  workspace_id: "ws-1",
  name: "A1",
  description: null,
  kind: "flow" as const,
  latest_version_id: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => {
  mockAuto.list.mockResolvedValue([fakeAutomation]);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useAutomations", () => {
  it("starts loading with empty list", () => {
    const { result } = renderHook(() => useAutomations("ws-1"));
    expect(result.current.loading).toBe(true);
    expect(result.current.automations).toEqual([]);
  });

  it("fetches automations on mount", async () => {
    const { result } = renderHook(() => useAutomations("ws-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.automations).toEqual([fakeAutomation]);
    expect(mockAuto.list).toHaveBeenCalled();
  });

  it("create prepends to list", async () => {
    const created = { ...fakeAutomation, id: "a2", name: "A2" };
    mockAuto.create.mockResolvedValue(created);

    const { result } = renderHook(() => useAutomations("ws-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.create({ name: "A2", kind: "flow" });
    });

    expect(result.current.automations[0].id).toBe("a2");
    expect(mockAuto.create).toHaveBeenCalledWith({
      name: "A2",
      kind: "flow",
    });
  });

  it("update replaces row in list", async () => {
    const updated = { ...fakeAutomation, name: "Renamed" };
    mockAuto.update.mockResolvedValue(updated);

    const { result } = renderHook(() => useAutomations("ws-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.update("a1", { name: "Renamed" });
    });

    expect(result.current.automations[0].name).toBe("Renamed");
  });

  it("delete removes row", async () => {
    mockAuto.delete.mockResolvedValue(undefined);

    const { result } = renderHook(() => useAutomations("ws-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.automations).toHaveLength(1);

    await act(async () => {
      await result.current.delete("a1");
    });

    expect(result.current.automations).toHaveLength(0);
  });

  it("cancelRun calls API and returns true on success", async () => {
    mockAuto.cancelRun.mockResolvedValue({ cancelled: true, run_id: "r1" });

    const { result } = renderHook(() => useAutomations("ws-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    let ok = false;
    await act(async () => {
      ok = await result.current.cancelRun("r1");
    });

    expect(ok).toBe(true);
    expect(mockAuto.cancelRun).toHaveBeenCalledWith("r1");
  });

  it("cancelRun returns false and surfaces error on failure", async () => {
    mockAuto.cancelRun.mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useAutomations("ws-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    let ok = true;
    await act(async () => {
      ok = await result.current.cancelRun("r1");
    });

    expect(ok).toBe(false);
    expect(result.current.error).toBe("boom");
  });

  it("touch replaces a row (used after createVersion refresh)", async () => {
    const bumped = {
      ...fakeAutomation,
      latest_version_id: "v2",
    };

    const { result } = renderHook(() => useAutomations("ws-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.touch(bumped);
    });

    expect(result.current.automations[0].latest_version_id).toBe("v2");
  });
});
