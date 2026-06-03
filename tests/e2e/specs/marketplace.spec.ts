import { test, expect, Page } from "@playwright/test";
import { signup, uniqueEmail } from "../helpers/auth-helper";

async function gotoMarketplace(page: Page): Promise<void> {
  await signup(page, uniqueEmail("mkt"));
  await page.getByRole("button", { name: /marketplace/i }).click();
}

test.describe("Marketplace", () => {
  test("List public apps (3 demo seeded)", async ({ page }) => {
    await gotoMarketplace(page);
    await expect(
      page
        .getByText(/Visit & Extract|Search & Click|Smooth Human Scroll/i)
        .first(),
    ).toBeVisible();
    await page.screenshot({
      path: "screenshots/marketplace-list.png",
      fullPage: true,
    });
  });

  test("Filter by category chips", async ({ page }) => {
    await gotoMarketplace(page);
    const dataChip = page.getByRole("button", { name: /data/i });
    if (await dataChip.isVisible()) await dataChip.click();
    await page.screenshot({
      path: "screenshots/marketplace-filter.png",
      fullPage: true,
    });
  });

  test("Install free app clones to workspace", async ({ page }) => {
    await gotoMarketplace(page);
    const installBtn = page
      .getByRole("button", { name: /install/i })
      .first();
    await installBtn.click();
    // Sau install, button đổi thành "Installed"
    await expect(page.getByText(/installed/i).first()).toBeVisible({
      timeout: 10_000,
    });
    await page.screenshot({
      path: "screenshots/marketplace-installed.png",
      fullPage: true,
    });
  });

  test("Open Creator Dashboard", async ({ page }) => {
    await gotoMarketplace(page);
    await page
      .getByRole("button", { name: /creator dashboard/i })
      .click();
    await expect(
      page.getByText(/total apps|earnings/i).first(),
    ).toBeVisible();
    await page.screenshot({
      path: "screenshots/marketplace-creator.png",
      fullPage: true,
    });
  });

  test("Open Submit App dialog", async ({ page }) => {
    await gotoMarketplace(page);
    await page.getByRole("button", { name: /submit/i }).click();
    await expect(page.getByLabel(/slug/i)).toBeVisible();
    await page.screenshot({
      path: "screenshots/marketplace-submit.png",
      fullPage: true,
    });
  });
});
