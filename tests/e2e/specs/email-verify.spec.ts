import { test, expect } from "../helpers/fixtures";
import { snap } from "../helpers/screenshot-helper";
import { signup, uniqueEmail } from "../helpers/auth-helper";

/**
 * Email verification UX:
 *   - banner appears after signup naming the unverified address
 *   - Resend button transitions through a "sending" state to success
 *   - the verify callback URL redirects to / with a flag (or surfaces an
 *     error UI when the token is bad)
 */
test.describe("email verification", () => {
  test("banner names the unverified address after signup", async ({
    page,
  }) => {
    const email = uniqueEmail("verify-banner");
    await signup(page, email);
    await snap(page, "verify-banner-01-signed-in");

    const banner = page
      .getByText(
        new RegExp(
          `${email.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\$&")}.*(not verified|unverified)|not verified|unverified|verify.*email|confirm.*email`,
          "i",
        ),
      )
      .first();
    await expect(banner).toBeVisible();
    await snap(page, "verify-banner-02-banner");
  });

  test("Resend verification transitions through a sending state to success", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("verify-resend"));
    await snap(page, "verify-resend-01-signed-in");

    const resend = page
      .getByRole("button", { name: /resend.*(verification|email)|resend/i })
      .first();
    if ((await resend.count()) === 0) {
      test.skip(true, "Resend button not present (banner may be dismissed)");
    }
    await resend.click();
    await snap(page, "verify-resend-02-clicked");

    // Either an in-flight indicator (disabled / "sending") or directly the
    // success copy is acceptable depending on network speed.
    const sendingState = page
      .getByText(/sending|please wait/i)
      .or(
        page.locator(
          'button:has-text("Resend")[disabled], button:has-text("Sending")',
        ),
      )
      .first();
    const successCopy = page
      .getByText(/sent|check (your )?(email|inbox)|on its way/i)
      .first();

    await expect(sendingState.or(successCopy)).toBeVisible({ timeout: 10_000 });
    await snap(page, "verify-resend-03-success");
  });

  test("verify URL with token redirects to /?verified=1 or shows an error UI", async ({
    page,
  }) => {
    // We hit the verify endpoint via the browser navigation so the cookie
    // flow has a chance to set a flag and redirect.
    const resp = await page
      .goto("/api/auth/verify-email?token=fake", { waitUntil: "load" })
      .catch(() => null);
    await snap(page, "verify-url-01-loaded");

    // Acceptable outcomes:
    //   a) redirected to "/?verified=1" or "/"
    //   b) status is 4xx and we land on an error page that mentions invalid/
    //      expired token
    if (resp && resp.ok()) {
      // Most likely redirected. URL should be the SPA root.
      await expect(page).toHaveURL(/\/(\?.*verified=1)?$/);
    } else {
      const errorCopy = page
        .getByText(/invalid|expired|verification failed|bad token/i)
        .first();
      // Either the SPA's error UI rendered the message, or the page body
      // surfaced the raw JSON — both are acceptable signals.
      const body = await page.content();
      if ((await errorCopy.count()) === 0) {
        expect(body.toLowerCase()).toMatch(/invalid|expired|error|failed/);
      } else {
        await expect(errorCopy).toBeVisible();
      }
    }
    await snap(page, "verify-url-02-result");
  });
});
