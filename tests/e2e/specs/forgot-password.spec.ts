import { test, expect } from "../helpers/fixtures";
import { snap } from "../helpers/screenshot-helper";

/**
 * Forgot-password / reset-password UI flow.
 *
 * The backend may or may not have wired the actual email send — we only
 * verify the front-end form behavior (link discoverable, request submits,
 * reset URL renders a form, weak-password validation triggers).
 */
test.describe("forgot password", () => {
  test("login page exposes a 'Forgot password?' link", async ({ page }) => {
    await page.goto("/");
    await snap(page, "forgot-login-loaded");

    const link = page
      .getByRole("link", { name: /forgot.*password/i })
      .or(page.getByRole("button", { name: /forgot.*password/i }))
      .or(page.getByText(/forgot.*password/i));
    await expect(link.first()).toBeVisible();
    await snap(page, "forgot-link-visible");
  });

  test("clicking the link opens the ForgotPasswordPage form", async ({
    page,
  }) => {
    await page.goto("/");
    await snap(page, "forgot-open-01-start");

    const link = page
      .getByRole("link", { name: /forgot/i })
      .or(page.getByRole("button", { name: /forgot/i }));
    await link.first().click();

    // Either a dedicated email field, or a heading mentioning reset/forgot.
    const heading = page.getByRole("heading", {
      name: /forgot|reset.*password/i,
    });
    const emailField = page.getByPlaceholder(/^email$/i).first();
    await expect(heading.first().or(emailField)).toBeVisible();
    await snap(page, "forgot-open-02-form");
  });

  test("submitting an email shows the generic 'if that email exists' confirmation", async ({
    page,
  }) => {
    await page.goto("/");
    await snap(page, "forgot-submit-01-login");

    await page
      .getByRole("link", { name: /forgot/i })
      .or(page.getByRole("button", { name: /forgot/i }))
      .first()
      .click();

    await page.getByPlaceholder(/^email$/i).first().fill("nobody@e2e.example.com");
    await snap(page, "forgot-submit-02-filled");

    await page
      .getByRole("button", { name: /reset|send|submit/i })
      .first()
      .click();

    // Privacy-preserving copy — should NOT confirm existence of the address.
    await expect(
      page
        .getByText(
          /if that email exists|check your (email|inbox)|we (have )?sent|reset link/i,
        )
        .first(),
    ).toBeVisible();
    await snap(page, "forgot-submit-03-confirmed");
  });

  test("reset-password URL with a token renders the new-password form and rejects weak passwords", async ({
    page,
  }) => {
    await page.goto("/reset-password?token=fake");
    await snap(page, "reset-form-01-loaded");

    // Either we see a password field (form rendered) or an "invalid token"
    // error — both are valid UI states.
    const pwField = page.getByPlaceholder(/^password/i).first();
    const invalidMsg = page
      .getByText(/invalid|expired|not (a )?valid/i)
      .first();

    if ((await pwField.count()) > 0) {
      await pwField.fill("123");
      // Try to find a confirm field — fill same weak value.
      const confirm = page.getByPlaceholder(/confirm/i).first();
      if ((await confirm.count()) > 0) {
        await confirm.fill("123");
      }
      await snap(page, "reset-form-02-weak-filled");

      await page
        .getByRole("button", { name: /reset|save|submit|update/i })
        .first()
        .click()
        .catch(() => {});

      // Either inline HTML5 validity, or a "min 8 chars" error.
      const validityBroken = await pwField.evaluate(
        (el) => (el as HTMLInputElement).validity?.valid === false,
      );
      if (!validityBroken) {
        await expect(
          page
            .getByText(/at least 8|min(imum)?\s*8|too short|weak/i)
            .first(),
        ).toBeVisible();
      }
      await snap(page, "reset-form-03-weak-error");
    } else {
      await expect(invalidMsg).toBeVisible();
      await snap(page, "reset-form-02-invalid-token");
    }
  });
});
