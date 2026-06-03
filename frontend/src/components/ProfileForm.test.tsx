import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ProfileForm } from "./ProfileForm";
import type { Profile } from "../lib/api";

// regionsApi.list is fired in useEffect on mount — stub to a resolved empty
// list so the component renders deterministically without any real fetch.
vi.mock("../lib/regions", () => ({
  regionsApi: {
    list: vi.fn().mockResolvedValue({ regions: [] }),
  },
}));

// ProfileVersionHistory pulls in its own hook (and fetch) for edit mode —
// stub it out so we can focus on the form fields under test.
vi.mock("./ProfileVersionHistory", () => ({
  ProfileVersionHistory: () => null,
}));

// Stub native confirm so the Delete handler proceeds without prompting.
beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

const existingProfile: Profile = {
  id: "p1",
  name: "Existing",
  fingerprint_seed: 4242,
  proxy: null,
  timezone: null,
  locale: null,
  platform: "macos",
  user_agent: null,
  screen_width: 1920,
  screen_height: 1080,
  gpu_vendor: null,
  gpu_renderer: null,
  hardware_concurrency: null,
  humanize: false,
  human_preset: "default",
  headless: false,
  geoip: false,
  clipboard_sync: true,
  auto_launch: false,
  color_scheme: null,
  launch_args: [],
  notes: null,
  region: null,
  browser_type: "firefox",
  tags: [],
  status: "stopped",
  vnc_ws_port: null,
  cdp_url: null,
  user_data_dir: "/data/profiles/p1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function submitForm(container: HTMLElement) {
  // JSDOM doesn't bubble button[type=submit] clicks into form submit, so
  // dispatch the submit event explicitly to exercise handleSubmit.
  fireEvent.submit(container.querySelector("form")!);
}

describe("ProfileForm", () => {
  it("renders create mode with empty Name field and Browser engine select", () => {
    render(
      <ProfileForm
        profile={null}
        onSave={vi.fn().mockResolvedValue(undefined)}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText(/new profile/i)).toBeTruthy();
    const nameInput = screen.getByPlaceholderText(
      /amazon seller/i,
    ) as HTMLInputElement;
    expect(nameInput.value).toBe("");

    // Browser engine dropdown defaults to chromium and exposes firefox option.
    expect(screen.getByText(/Chromium \(CloakBrowser/i)).toBeTruthy();
    expect(screen.getByText(/^Firefox$/i)).toBeTruthy();
  });

  it("renders edit mode with fields populated from the profile prop", async () => {
    render(
      <ProfileForm
        profile={existingProfile}
        onSave={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn().mockResolvedValue(undefined)}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText(/edit profile/i)).toBeTruthy();
    await waitFor(() => {
      const nameInput = screen.getByPlaceholderText(
        /amazon seller/i,
      ) as HTMLInputElement;
      expect(nameInput.value).toBe("Existing");
    });

    // browser_type was firefox on the seed profile.
    const browserSelect = screen.getByDisplayValue(/^Firefox$/i) as HTMLSelectElement;
    expect(browserSelect.value).toBe("firefox");
  });

  it("calls onSave with the current form data when Save is clicked", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <ProfileForm
        profile={null}
        onSave={onSave}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText(/amazon seller/i), {
      target: { value: "My Profile" },
    });

    submitForm(container);

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).toMatchObject({
      name: "My Profile",
      browser_type: "chromium",
      platform: "windows",
    });
  });

  it("calls onDelete only in edit mode when Delete is clicked", async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(
      <ProfileForm
        profile={existingProfile}
        onSave={vi.fn().mockResolvedValue(undefined)}
        onDelete={onDelete}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /delete/i }));
    await waitFor(() => expect(onDelete).toHaveBeenCalledTimes(1));
  });

  it("does not render Delete button in create mode", () => {
    render(
      <ProfileForm
        profile={null}
        onSave={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn().mockResolvedValue(undefined)}
        onCancel={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /^delete$/i }),
    ).toBeNull();
  });

  it("calls onCancel when the Cancel button is clicked", () => {
    const onCancel = vi.fn();
    render(
      <ProfileForm
        profile={null}
        onSave={vi.fn().mockResolvedValue(undefined)}
        onCancel={onCancel}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("changing the Browser engine select updates the saved payload", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <ProfileForm
        profile={null}
        onSave={onSave}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText(/amazon seller/i), {
      target: { value: "B" },
    });

    // The Browser engine <select> currently shows the chromium label —
    // grab it by display value and switch to firefox.
    const browserSelect = screen.getByDisplayValue(
      /Chromium \(CloakBrowser/i,
    ) as HTMLSelectElement;
    fireEvent.change(browserSelect, { target: { value: "firefox" } });

    submitForm(container);

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].browser_type).toBe("firefox");
  });
});
