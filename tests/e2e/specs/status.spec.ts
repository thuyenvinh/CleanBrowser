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

  test("Incidents section empty state", async ({ page }) => {
    await page.goto("/status");
    // No incidents — should show empty placeholder or "All clear"
    await expect(
      page.getByText(/no incidents|all clear|operational/i).first(),
    ).toBeVisible();
    await page.screenshot({
      path: "screenshots/status-no-incidents.png",
      fullPage: true,
    });
  });
});
