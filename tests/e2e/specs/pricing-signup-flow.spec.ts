import { test, expect } from "@playwright/test";
import { uniqueEmail } from "../helpers/auth-helper";

/**
 * Pricing → signup → billing happy path.
 *
 * Covers the public pricing landing (``/?pricing=1``), the ``?plan=`` hand-off
 * that the SignupPage reads to render the trial banner, and the post-signup
 * Billing tab that surfaces the auto-applied Pro trial. See ``PricingPage``,
 * ``SignupPage`` and ``BillingPage`` for the components under test.
 */
test.describe("pricing → signup flow", () => {
  test("public pricing page renders 4 plan cards", async ({ page }) => {
    await page.goto("/?pricing=1");

    // 4 tiers: Free / Starter / Pro / Team (or legacy Enterprise/Business
    // copy). At minimum we expect the three canonical labels plus one CTA.
    await expect(page.getByText(/free/i).first()).toBeVisible();
    await expect(page.getByText(/starter/i).first()).toBeVisible();
    await expect(page.getByText(/pro/i).first()).toBeVisible();
    await expect(
      page.getByText(/team|enterprise|business/i).first(),
    ).toBeVisible();
  });

  test("clicking Start free trial on Pro lands on the signup form with ?plan=pro", async ({
    page,
  }) => {
    await page.goto("/?pricing=1");

    // Wait for the pricing CTA — the Pro card uses the "Start 14-day free
    // trial" copy; older variants used "Start free trial".
    const trialCta = page
      .getByRole("button", { name: /start (14-day )?free trial/i })
      .first();
    await expect(trialCta).toBeVisible();
    await trialCta.click();

    // SignupPage drops ``?plan=`` into the URL so the trial banner can show
    // which plan the user is starting on. Accept any non-free plan id.
    await expect(page).toHaveURL(/[?&]plan=(pro|starter|team|business|enterprise)/);

    // And we should now be on the signup form (email + confirm password).
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expect(page.getByLabel(/confirm/i)).toBeVisible();
  });

  test("signing up from the Pro pricing CTA lands on Billing with a Pro trial", async ({
    page,
  }) => {
    await page.goto("/?pricing=1");

    const trialCta = page
      .getByRole("button", { name: /start (14-day )?free trial/i })
      .first();
    await expect(trialCta).toBeVisible();
    await trialCta.click();

    // Drive the signup form directly here so we exercise the full flow
    // (the standard ``signup`` helper goes via ``/`` instead of ``/?plan=``).
    const email = uniqueEmail("pricing-signup");
    await page.getByLabel(/email/i).fill(email);
    await page
      .getByLabel(/password/i, { exact: true })
      .first()
      .fill("password123");
    await page.getByLabel(/confirm/i).fill("password123");
    await page
      .getByRole("button", { name: /create account|sign up/i })
      .click();

    // Land on the app shell.
    await page.waitForURL(/\/$/);
    await page.getByRole("button", { name: /billing/i }).first().click();

    // Pro plan with a trial badge should be visible on the Billing tab.
    await expect(page.getByText(/pro/i).first()).toBeVisible();
    await expect(
      page.getByText(/trialing|trial|current plan/i).first(),
    ).toBeVisible();
  });
});
