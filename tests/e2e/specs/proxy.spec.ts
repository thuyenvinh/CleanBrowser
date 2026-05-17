import { test, expect } from "@playwright/test";
import { signup, uniqueEmail } from "../helpers/auth-helper";

test.describe("proxies", () => {
  test("create an HTTP proxy from the form", async ({ page }) => {
    await signup(page, uniqueEmail("proxy-new"));

    await page.getByRole("button", { name: /proxies/i }).first().click();

    // Empty state — click "New Proxy".
    await page
      .getByRole("button", { name: /new proxy|new/i })
      .first()
      .click();

    // Pick HTTP scheme if a selector is present. (UI uses a <select> or
    // a button group depending on the version, so be defensive.)
    const schemeSelect = page.getByLabel(/scheme|type/i).first();
    if (await schemeSelect.count()) {
      await schemeSelect.selectOption("http").catch(async () => {
        await schemeSelect.click();
        await page.getByRole("option", { name: /^http$/i }).click();
      });
    }

    await page.getByLabel(/host/i).first().fill("1.2.3.4");
    await page.getByLabel(/port/i).first().fill("8080");

    await page
      .getByRole("button", { name: /save|create|add/i })
      .first()
      .click();

    await expect(page.getByText(/1\.2\.3\.4/)).toBeVisible();
    await expect(page.getByText(/8080/)).toBeVisible();
  });

  test("bulk import 3 proxies via the import dialog", async ({ page }) => {
    await signup(page, uniqueEmail("proxy-import"));
    await page.getByRole("button", { name: /proxies/i }).first().click();

    await page
      .getByRole("button", { name: /import|bulk/i })
      .first()
      .click();

    const lines = [
      "10.0.0.1:1080",
      "10.0.0.2:1080",
      "10.0.0.3:1080",
    ].join("\n");
    await page.getByRole("textbox").first().fill(lines);

    // Some builds show a "Preview" step; click it if present, otherwise the
    // primary CTA jumps straight to Import.
    const previewBtn = page.getByRole("button", { name: /preview/i });
    if (await previewBtn.count()) {
      await previewBtn.first().click();
    }
    await page
      .getByRole("button", { name: /^import$/i })
      .first()
      .click();

    for (const host of ["10.0.0.1", "10.0.0.2", "10.0.0.3"]) {
      await expect(page.getByText(host)).toBeVisible();
    }
  });
});
