import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ProxyForm } from "./ProxyForm";
import type { Proxy } from "../lib/proxy";

beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

const existingProxy: Proxy = {
  id: "px1",
  workspace_id: "ws-1",
  name: "Old",
  type: "socks5",
  host: "1.2.3.4",
  port: 1080,
  username: "u",
  provider: "smartproxy",
  country_code: "US",
  status: "ok",
  latency_ms: 100,
  last_check_at: "2026-01-01T00:00:00Z",
  last_error: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function submitForm(container: HTMLElement) {
  fireEvent.submit(container.querySelector("form")!);
}

describe("ProxyForm", () => {
  it("renders create mode with empty fields and default type http", () => {
    render(
      <ProxyForm
        proxy={null}
        onSave={vi.fn().mockResolvedValue(undefined)}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText(/new proxy/i)).toBeTruthy();
    const nameInput = screen.getByPlaceholderText(
      /us residential/i,
    ) as HTMLInputElement;
    expect(nameInput.value).toBe("");
    // Type select defaults to HTTP (uppercased option label).
    expect(screen.getByDisplayValue("HTTP")).toBeTruthy();
  });

  it("renders edit mode with fields populated from the proxy prop", async () => {
    render(
      <ProxyForm
        proxy={existingProxy}
        onSave={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn().mockResolvedValue(undefined)}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText(/edit proxy/i)).toBeTruthy();
    await waitFor(() => {
      const nameInput = screen.getByPlaceholderText(
        /us residential/i,
      ) as HTMLInputElement;
      expect(nameInput.value).toBe("Old");
    });
    expect(screen.getByDisplayValue("SOCKS5")).toBeTruthy();
    const hostInput = screen.getByPlaceholderText(
      /proxy\.example\.com/i,
    ) as HTMLInputElement;
    expect(hostInput.value).toBe("1.2.3.4");
  });

  it("renders all four proxy type options (http/https/socks4/socks5)", () => {
    render(
      <ProxyForm
        proxy={null}
        onSave={vi.fn().mockResolvedValue(undefined)}
        onCancel={vi.fn()}
      />,
    );

    const typeSelect = screen.getByDisplayValue("HTTP") as HTMLSelectElement;
    const labels = Array.from(typeSelect.options).map((o) => o.value);
    expect(labels).toEqual(["http", "https", "socks4", "socks5"]);
  });

  it("shows validation error when port is outside 1-65535", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <ProxyForm
        proxy={null}
        onSave={onSave}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText(/us residential/i), {
      target: { value: "P" },
    });
    fireEvent.change(screen.getByPlaceholderText(/proxy\.example\.com/i), {
      target: { value: "h" },
    });
    // Out-of-range port — validate() should reject and onSave should never fire.
    fireEvent.change(screen.getByPlaceholderText("8080"), {
      target: { value: "99999" },
    });
    submitForm(container);

    await screen.findByText(/Port must be 1-65535/i);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("calls onSave with a fully populated payload on valid submit", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <ProxyForm
        proxy={null}
        onSave={onSave}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText(/us residential/i), {
      target: { value: "My Proxy" },
    });
    fireEvent.change(screen.getByPlaceholderText(/proxy\.example\.com/i), {
      target: { value: "proxy.example.com" },
    });
    fireEvent.change(screen.getByPlaceholderText("8080"), {
      target: { value: "8080" },
    });

    submitForm(container);

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).toMatchObject({
      name: "My Proxy",
      type: "http",
      host: "proxy.example.com",
      port: 8080,
    });
  });
});
