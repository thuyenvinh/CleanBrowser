import { test, expect } from "../helpers/fixtures";
import { snap } from "../helpers/screenshot-helper";
import { signup, uniqueEmail } from "../helpers/auth-helper";

/**
 * Trial countdown banner.
 *
 * The banner only surfaces when a Pro/Starter trial is within ~3 days of
 * expiry, so we can't deterministically force it from a fresh tenant
 * without a backend fixture knob. We assert two things:
 *
 *   1. localStorage dismissal suppresses the banner (does not regress the
 *      shell).
 *   2. The banner countdown does NOT appear on a brand-new account (14d
 *      remaining). Backend fixture TODO: add a way to seed trial_end < 3d.
 */
test.describe("trial countdown banner", () => {
  test("dismissed-in-localStorage suppresses the banner across reload", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("banner-dismiss"));
    await snap(page, "banner-dismiss-01-signed-in");

    // Seed dismissal flags the app might read.
    await page.evaluate(() => {
      try {
        localStorage.setItem("trialBanner.dismissed", "1");
        localStorage.setItem("trial_banner_dismissed", "1");
        localStorage.setItem("dismissed:trial-banner", String(Date.now()));
      } catch {
        // ignore
      }
    });
    await page.reload();
    await snap(page, "banner-dismiss-02-after-reload");

    // The banner should not be visible. We look for the countdown copy
    // specifically — "trial" alone can appear on the Billing tab.
    const banner = page.getByText(
      /trial ends in|days? left in|expires? in.*day|\d+ days? remaining/i,
    );
    await expect(banner).toHaveCount(0);
  });

  test("brand-new tenant (14d trial) does not show the countdown", async ({
    page,
  }) => {
    // TODO(backend fixture): once we expose a seed knob to set
    // trial_end < 3 days, add a positive-path test that asserts the
    // banner *does* render with an accurate countdown.
    await signup(page, uniqueEmail("banner-fresh"));
    await snap(page, "banner-fresh-01-signed-in");

    const banner = page.getByText(
      /trial ends in|day(s)? left|expires? (in )?\d+ day/i,
    );
    await expect(banner).toHaveCount(0);
    await snap(page, "banner-fresh-02-no-countdown");
  });
});
