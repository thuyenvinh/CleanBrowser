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
});
