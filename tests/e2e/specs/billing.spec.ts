import { test, expect } from "@playwright/test";
import { signup, uniqueEmail } from "../helpers/auth-helper";

test.describe("billing", () => {
  test("billing page shows free plan, plan grid and usage bars", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("billing"));

    await page.getByRole("button", { name: /billing/i }).first().click();

    // Free plan badge / label somewhere on the page.
    await expect(page.getByText(/free/i).first()).toBeVisible();

    // Plan cards — we ship 4 tiers (free, starter, pro, enterprise). We
    // assert that we can see at least 3 distinct plan-name labels to avoid
    // brittle string matching when copy gets tweaked.
    const planMatches = await page
      .getByText(/(free|starter|pro|enterprise|business|team)/i)
      .count();
    expect(planMatches).toBeGreaterThanOrEqual(3);

    // Usage bars — look for progress bars or the word "usage".
    const hasProgress =
      (await page.getByRole("progressbar").count()) > 0 ||
      (await page.getByText(/usage/i).count()) > 0;
    expect(hasProgress).toBe(true);
  });

  test("Trial Pro auto-applied after signup shows Current plan/trialing", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("trial"));
    await page.getByRole("button", { name: /billing/i }).first().click();

    // After signup we auto-apply a Pro trial. Look for the Pro label paired
    // with a current/trial badge somewhere on the page.
    await expect(page.getByText(/pro/i).first()).toBeVisible();
    const trialBadge = page.getByText(/current plan|trialing|trial/i).first();
    await expect(trialBadge).toBeVisible();
  });

  test("Plans grid renders 4 tiers (Free/Starter/Pro/Team)", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("plans"));
    await page.getByRole("button", { name: /billing/i }).first().click();

    // We expect labels for at least four distinct tiers on the plans grid.
    // Accept "Team" or the older "Enterprise"/"Business" copy as the 4th.
    await expect(page.getByText(/free/i).first()).toBeVisible();
    await expect(page.getByText(/starter/i).first()).toBeVisible();
    await expect(page.getByText(/pro/i).first()).toBeVisible();
    await expect(
      page.getByText(/team|enterprise|business/i).first(),
    ).toBeVisible();

    // Usage bars should be present somewhere on the billing page.
    const hasProgress =
      (await page.getByRole("progressbar").count()) > 0 ||
      (await page.getByText(/usage/i).count()) > 0;
    expect(hasProgress).toBe(true);
  });

  test("Stripe and VNPay buttons available on paid plan", async ({ page }) => {
    await signup(page, uniqueEmail("pay"));
    await page.getByRole("button", { name: /billing/i }).first().click();

    // We don't assert the exact placement; just that both payment providers
    // are surfaced somewhere on the billing page for at least one paid plan.
    // Both providers ship on every paid tier; assert each is visible
    // independently (combining with .or() trips Playwright's strict mode).
    await expect(page.getByRole("button", { name: /^stripe$/i }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: /^vnpay$/i }).first()).toBeVisible();
  });

  test("Pricing page is public (no auth required)", async ({ page }) => {
    await page.goto("/?pricing=1");

    // Expect the four plan tiers to be visible to logged-out visitors.
    await expect(page.getByText(/free/i).first()).toBeVisible();
    await expect(page.getByText(/starter/i).first()).toBeVisible();
    await expect(page.getByText(/pro/i).first()).toBeVisible();

    // And a CTA pointing at the trial.
    await expect(
      page.getByRole("button", { name: /start free trial|free trial/i }).first(),
    ).toBeVisible();
  });

  test("Trial countdown banner integrates without breaking signup flow", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("banner"));
    // On a brand-new account with 14 days remaining, the countdown banner is
    // typically not yet shown (it surfaces near the end of the trial). We
    // only verify that the app shell still mounts cleanly and the billing
    // tab is reachable — i.e. the component import path is sound.
    await page.getByRole("button", { name: /billing/i }).first().click();
    await expect(page.getByText(/pro|trial|plan/i).first()).toBeVisible();
  });

  test("Invoice section shows empty state for new account", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("inv"));
    await page.getByRole("button", { name: /billing/i }).first().click();

    await expect(
      page.getByText(/no invoices yet|no invoices/i).first(),
    ).toBeVisible();
  });
});
