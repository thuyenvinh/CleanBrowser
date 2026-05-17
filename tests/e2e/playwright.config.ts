import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for CleanBrowser E2E suite.
 *
 * Workers forced to 1 because the suite shares a single Postgres instance
 * (each spec signs up a fresh tenant, but ordering across specs is still
 * easier to reason about sequentially). Adjust if/when tests get isolated.
 */
export default defineConfig({
  testDir: "./specs",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:8080",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
