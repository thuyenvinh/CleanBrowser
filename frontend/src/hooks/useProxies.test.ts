import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useProxies } from "./useProxies";

vi.mock("../lib/proxy", () => ({
  proxy: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    test: vi.fn(),
    bulkCreate: vi.fn(),
  },
}));

import { proxy as proxyApi } from "../lib/proxy";

const mockProxy = proxyApi as unknown as {
  list: ReturnType<typeof vi.fn>;
  create: ReturnType<typeof vi.fn>;
  update: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
  test: ReturnType<typeof vi.fn>;
  bulkCreate: ReturnType<typeof vi.fn>;
};

const fakeProxy = {
  id: "p1",
  workspace_id: "ws-1",
  name: "P1",
  type: "http",
  host: "1.2.3.4",
  port: 8080,
  username: null,
  provider: null,
  country_code: null,
  status: "unchecked" as const,
  latency_ms: null,
  last_check_at: null,
  last_error: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => {
  mockProxy.list.mockResolvedValue([fakeProxy]);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useProxies", () => {
  it("starts loading with empty list", () => {
    const { result } = renderHook(() => useProxies("ws-1"));
    expect(result.current.loading).toBe(true);
    expect(result.current.proxies).toEqual([]);
  });

  it("fetches proxies on mount", async () => {
    const { result } = renderHook(() => useProxies("ws-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.proxies).toEqual([fakeProxy]);
    expect(mockProxy.list).toHaveBeenCalled();
  });

  it("create prepends to list", async () => {
    const created = { ...fakeProxy, id: "p2", name: "P2" };
    mockProxy.create.mockResolvedValue(created);

    const { result } = renderHook(() => useProxies("ws-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.create({
        name: "P2",
        type: "http",
        host: "h",
        port: 1,
      });
    });

    expect(result.current.proxies[0].id).toBe("p2");
  });

  it("update replaces row in list", async () => {
    const updated = { ...fakeProxy, name: "Renamed" };
    mockProxy.update.mockResolvedValue(updated);

    const { result } = renderHook(() => useProxies("ws-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.update("p1", { name: "Renamed" });
    });

    expect(result.current.proxies[0].name).toBe("Renamed");
  });

  it("delete removes row", async () => {
    mockProxy.delete.mockResolvedValue(undefined);

    const { result } = renderHook(() => useProxies("ws-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.proxies).toHaveLength(1);

    await act(async () => {
      await result.current.delete("p1");
    });

    expect(result.current.proxies).toHaveLength(0);
  });

  it("test updates row status with returned latency", async () => {
    mockProxy.test.mockResolvedValue({
      status: "ok",
      latency_ms: 123,
      country_code: "US",
    });

    const { result } = renderHook(() => useProxies("ws-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.test("p1");
    });

    const row = result.current.proxies[0];
    expect(row.status).toBe("ok");
    expect(row.latency_ms).toBe(123);
    expect(row.country_code).toBe("US");
  });
});
