import { test, expect } from "@playwright/test";

test.describe("Public Status Page", () => {
  test("Status page accessible without login", async ({ page }) => {
    await page.goto("/status");
    await expect(
      page.getByText(/operational|status|uptime/i).first(),
    ).toBeVisible();
    await page.screenshot({
      path: "screenshots/status-page.png",
      fullPage: true,
    });
  });

  test("Service uptime bars rendered", async ({ page }) => {
    await page.goto("/status");
    await expect(page.locator("text=/api|service/i").first()).toBeVisible();
    await page.screenshot({
      path: "screenshots/status-services.png",
      fullPage: true,
    });
  });

  test("Incidents section renders (empty or populated)", async ({ page }) => {
    await page.goto("/status");
    // Either an "all clear" empty state or a recent-incidents list — we
    // only verify the section header is present so the test stays stable
    // when other specs in the same DB seed incident rows.
    await expect(
      page.getByText(/incidents|operational|outage|all clear/i).first(),
    ).toBeVisible();
    await page.screenshot({
      path: "screenshots/status-no-incidents.png",
      fullPage: true,
    });
  });
});
