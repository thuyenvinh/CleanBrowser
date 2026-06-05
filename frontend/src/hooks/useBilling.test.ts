import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useBilling } from "./useBilling";

vi.mock("../lib/billing", () => ({
  billing: {
    getSubscription: vi.fn(),
    listPlans: vi.fn(),
    listInvoices: vi.fn(),
    startCheckout: vi.fn(),
    openPortal: vi.fn(),
    startVnpayCheckout: vi.fn(),
  },
}));

import { billing } from "../lib/billing";

const mockBilling = billing as unknown as {
  getSubscription: ReturnType<typeof vi.fn>;
  listPlans: ReturnType<typeof vi.fn>;
  listInvoices: ReturnType<typeof vi.fn>;
  startCheckout: ReturnType<typeof vi.fn>;
  openPortal: ReturnType<typeof vi.fn>;
  startVnpayCheckout: ReturnType<typeof vi.fn>;
};

const fakeStatus = {
  subscription: null,
  plan: {
    id: "free",
    name: "Free",
    description: null,
    price_cents: 0,
    interval: "month",
    max_profiles: 5,
    max_concurrent_runs: 1,
    max_workspace_members: 1,
    max_automation_minutes: 60,
    max_storage_gb: 1,
    allow_regions: [],
    is_public: true,
    sort_order: 0,
  },
  usage: {
    profile_count: 0,
    concurrent_runs_peak: 0,
    automation_minutes_used: 0,
    storage_gb_used: 0,
    workspace_members_count: 1,
  },
};

beforeEach(() => {
  mockBilling.getSubscription.mockResolvedValue(fakeStatus);
  mockBilling.listPlans.mockResolvedValue([fakeStatus.plan]);
  mockBilling.listInvoices.mockResolvedValue([]);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useBilling", () => {
  it("starts in loading state", () => {
    const { result } = renderHook(() => useBilling());
    expect(result.current.loading).toBe(true);
  });

  it("fetches subscription + plans + invoices on mount", async () => {
    const { result } = renderHook(() => useBilling());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(mockBilling.getSubscription).toHaveBeenCalled();
    expect(mockBilling.listPlans).toHaveBeenCalled();
    expect(mockBilling.listInvoices).toHaveBeenCalled();
    expect(result.current.status).toEqual(fakeStatus);
    expect(result.current.plans).toHaveLength(1);
  });

  it("upgrade redirects to returned checkout url", async () => {
    mockBilling.startCheckout.mockResolvedValue({
      url: "https://stripe.test/c",
      session_id: "cs",
    });
    const hrefSetter = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        get href() {
          return "";
        },
        set href(v: string) {
          hrefSetter(v);
        },
      },
    });

    const { result } = renderHook(() => useBilling());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.upgrade("plan-pro");
    });

    expect(mockBilling.startCheckout).toHaveBeenCalledWith("plan-pro");
    expect(hrefSetter).toHaveBeenCalledWith("https://stripe.test/c");
  });

  it("managePortal redirects to portal url", async () => {
    mockBilling.openPortal.mockResolvedValue({ url: "https://portal/" });
    const hrefSetter = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        get href() {
          return "";
        },
        set href(v: string) {
          hrefSetter(v);
        },
      },
    });

    const { result } = renderHook(() => useBilling());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.managePortal();
    });

    expect(hrefSetter).toHaveBeenCalledWith("https://portal/");
  });

  it("payVnpay redirects to vnpay url", async () => {
    mockBilling.startVnpayCheckout.mockResolvedValue({
      url: "https://vnpay/c",
      vnp_TxnRef: "T1",
    });
    const hrefSetter = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        get href() {
          return "";
        },
        set href(v: string) {
          hrefSetter(v);
        },
      },
    });

    const { result } = renderHook(() => useBilling());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.payVnpay("plan-pro");
    });

    expect(mockBilling.startVnpayCheckout).toHaveBeenCalledWith("plan-pro");
    expect(hrefSetter).toHaveBeenCalledWith("https://vnpay/c");
  });
});
