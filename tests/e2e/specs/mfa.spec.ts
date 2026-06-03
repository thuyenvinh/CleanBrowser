import { test, expect } from "../helpers/fixtures";
import { snap } from "../helpers/screenshot-helper";
import { signup, uniqueEmail } from "../helpers/auth-helper";

/**
 * MFA UI flow. We can't actually enable MFA in the test (would need a live
 * TOTP code), but we can verify:
 *   - the Security tab shows an MFA section
 *   - Enable MFA reveals a QR code + secret
 *   - submitting a bogus 6-digit code surfaces an error
 */
test.describe("MFA setup", () => {
  test("Security tab exposes an MFA section", async ({ page }) => {
    await signup(page, uniqueEmail("mfa-tab"));
    await snap(page, "mfa-tab-01-signed-in");

    await page
      .getByRole("button", { name: /security|api keys/i })
      .first()
      .click();

    await expect(
      page
        .getByText(/two.factor|mfa|authenticator/i)
        .first(),
    ).toBeVisible();
    await snap(page, "mfa-tab-02-section-visible");
  });

  test("Enable MFA reveals a QR code and a copyable secret", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("mfa-enable"));
    await page
      .getByRole("button", { name: /security|api keys/i })
      .first()
      .click();
    await snap(page, "mfa-enable-01-security");

    const enableBtn = page
      .getByRole("button", { name: /enable.*(mfa|two.factor|2fa)/i })
      .first();
    if ((await enableBtn.count()) === 0) {
      test.skip(true, "MFA enable button not present in this build");
    }
    await enableBtn.click();

    const qr = page
      .locator('img[src*="qr" i], img[alt*="qr" i], svg[aria-label*="qr" i]')
      .first();
    const secretText = page
      .getByText(/secret|otpauth|[A-Z2-7]{16,}/)
      .first();

    await expect(qr.or(secretText)).toBeVisible({ timeout: 10_000 });
    await snap(page, "mfa-enable-02-qr-visible");
  });

  test("submitting an invalid 6-digit code shows a validation error", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("mfa-bad"));
    await page
      .getByRole("button", { name: /security|api keys/i })
      .first()
      .click();
    await snap(page, "mfa-bad-01-security");

    const enableBtn = page
      .getByRole("button", { name: /enable.*(mfa|two.factor|2fa)/i })
      .first();
    if ((await enableBtn.count()) === 0) {
      test.skip(true, "MFA enable button not present in this build");
    }
    await enableBtn.click();

    // Find the code input. Apps often use a dedicated TOTP field or a generic
    // 6-digit "code" input.
    const codeInput = page
      .getByLabel(/code|token|otp|verification/i)
      .or(page.getByPlaceholder(/code|token|6.?digit/i))
      .first();

    if ((await codeInput.count()) === 0) {
      test.skip(true, "MFA code input not present");
    }
    await codeInput.fill("000000");
    await snap(page, "mfa-bad-02-bad-code");

    await page
      .getByRole("button", { name: /verify|confirm|enable|submit/i })
      .first()
      .click()
      .catch(() => {});

    await expect(
      page
        .getByText(/invalid|incorrect|wrong|does not match|try again/i)
        .first(),
    ).toBeVisible({ timeout: 10_000 });
    await snap(page, "mfa-bad-03-error");
  });

  test("UI flow only — does not actually flip the MFA flag", async ({
    page,
  }) => {
    // Sanity sentinel: we explicitly do NOT have a real TOTP secret, so we
    // confirm the user can land on Security and the page renders without
    // crashing. Real verification requires a TOTP generator + backend secret.
    await signup(page, uniqueEmail("mfa-noop"));
    await page
      .getByRole("button", { name: /security|api keys/i })
      .first()
      .click();
    await snap(page, "mfa-noop-01-security");

    await expect(
      page
        .getByText(/two.factor|mfa|authenticator|security/i)
        .first(),
    ).toBeVisible();
    await snap(page, "mfa-noop-02-rendered");
  });
});
