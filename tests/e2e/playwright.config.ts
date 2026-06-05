import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for CleanBrowser E2E suite.
 *
 * Workers forced to 1 because the suite shares a single Postgres instance
 * (each spec signs up a fresh tenant, but ordering across specs is still
 * easier to reason about sequentially). Adjust if/when tests get isolated.
 *
 * Trace / screenshot / video are forced ON for every test so failures in
 * CI can be triaged without re-running locally.
 */
export default defineConfig({
  testDir: "./specs",
  timeout: 30_000,
  fullyParallel: false, // sequential — shared DB state
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
    ["junit", { outputFile: "playwright-junit.xml" }],
  ],
  outputDir: "test-results",
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:8080",
    trace: "on", // luôn record trace
    screenshot: "on", // luôn screenshot mỗi test step
    video: { mode: "on", size: { width: 1280, height: 720 } }, // luôn quay video
    viewport: { width: 1280, height: 720 },
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    contextOptions: { recordVideo: { dir: "./test-results/videos" } },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // Webserver block intentionally omitted — assume backend đã start ngoài.
});
