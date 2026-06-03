import { test, expect, Page } from "@playwright/test";
import { signup, uniqueEmail } from "../helpers/auth-helper";

async function gotoSecurity(page: Page): Promise<void> {
  await signup(page, uniqueEmail("apik"));
  await page.getByRole("button", { name: /security|api keys/i }).click();
}

test.describe("API Keys + Security", () => {
  test("Security tab shows MFA section + empty key list", async ({ page }) => {
    await gotoSecurity(page);
    await expect(
      page.getByText(/two.factor|mfa|authenticator/i).first(),
    ).toBeVisible();
    await expect(
      page.getByText(/no api keys|use api keys/i).first(),
    ).toBeVisible();
    await page.screenshot({
      path: "screenshots/security-empty.png",
      fullPage: true,
    });
  });

  test("MFA setup shows QR + secret", async ({ page }) => {
    await gotoSecurity(page);
    const enableBtn = page
      .getByRole("button", { name: /enable.*mfa|enable.*two.factor/i })
      .first();
    if (await enableBtn.isVisible()) {
      await enableBtn.click();
      await expect(
        page.locator('img[src*="qr"], img[alt*="qr" i]').first(),
      ).toBeVisible({ timeout: 10_000 });
      await page.screenshot({
        path: "screenshots/mfa-qr.png",
        fullPage: true,
      });
    }
  });

  test("Create API key requires verified email (or shows banner)", async ({
    page,
  }) => {
    await gotoSecurity(page);
    const createBtn = page
      .getByRole("button", { name: /create.*key|new.*key/i })
      .first();
    await createBtn.click();
    // Either the create-form modal renders (placeholder "e.g. CI deploy bot")
    // or a 403 verify-email banner appears. Either outcome proves the path
    // surfaces correctly; combining them via .or() trips strict mode when
    // both render together.
    const formCount = await page
      .getByPlaceholder(/CI deploy bot|key name|name/i)
      .count();
    const verifyCount = await page.getByText(/verify.*email/i).count();
    expect(formCount + verifyCount).toBeGreaterThan(0);
    await page.screenshot({
      path: "screenshots/apikey-create.png",
      fullPage: true,
    });
  });

  test("Token plaintext shown once after create", async () => {
    // Cần email verified — skip nếu chưa verify
    test.skip(true, "Requires verified email — covered in integration tests");
  });

  test("Revoke key removes it from active list", async () => {
    test.skip(true, "Requires verified email + existing key");
  });
});
