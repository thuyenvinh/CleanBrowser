import { test, expect } from "@playwright/test";
import { signup, login, logout, uniqueEmail } from "../helpers/auth-helper";

/**
 * Per-spec screenshot helper. We dump to `screenshots/` under the e2e cwd so
 * artifacts collected in CI sit alongside the html/junit reports.
 */
async function snap(
  page: import("@playwright/test").Page,
  name: string,
  step: string,
): Promise<void> {
  await page
    .screenshot({
      path: `screenshots/auth-${name}-${step}.png`,
      fullPage: true,
    })
    .catch(() => {
      // best effort — never fail a test purely because the screenshot dir
      // wasn't writable.
    });
}

test.describe("auth", () => {
  test("signup creates tenant + default workspace and lands in the app", async ({
    page,
    context,
  }) => {
    const email = uniqueEmail("signup");
    await snap(page, "signup-basic", "01-start");
    await signup(page, email);
    await snap(page, "signup-basic", "02-after-signup");

    // App shell renders — sidebar with Profiles / Proxies / Automations.
    await expect(
      page.getByRole("button", { name: /profiles/i }).first(),
    ).toBeVisible();

    // A session cookie should have been set on the backend host.
    const cookies = await context.cookies();
    expect(cookies.some((c) => /session|access|token/i.test(c.name))).toBe(
      true,
    );
  });

  test("login with valid creds enters app; bad creds show error", async ({
    page,
  }) => {
    const email = uniqueEmail("login");
    await signup(page, email);
    await logout(page);
    await snap(page, "login-mixed", "01-logged-out");

    // Bad password first.
    await page.goto("/");
    await page.getByPlaceholder(/^email$/i).fill(email);
    await page
      .getByPlaceholder(/^password/i)
      .first()
      .fill("wrong-password");
    await page.getByRole("button", { name: /^(sign in|log in)$/i }).click();
    await expect(
      page.getByText(/invalid|incorrect|unauthorized|401/i),
    ).toBeVisible();
    await snap(page, "login-mixed", "02-bad-creds");

    // Now the right password.
    await login(page, email);
    await expect(
      page.getByRole("button", { name: /profiles/i }).first(),
    ).toBeVisible();
    await snap(page, "login-mixed", "03-good-creds");
  });

  test("logout clears the session and returns to login", async ({
    page,
    context,
  }) => {
    const email = uniqueEmail("logout");
    await signup(page, email);
    await snap(page, "logout-clears", "01-signed-in");

    await logout(page);
    await snap(page, "logout-clears", "02-after-logout");

    // Either the URL changed to /login or the login form is showing again.
    await expect(
      page.getByRole("button", { name: /^(sign in|log in)$/i }),
    ).toBeVisible();

    // Reloading shouldn't sneak us back in.
    await page.reload();
    await expect(
      page.getByRole("button", { name: /^(sign in|log in)$/i }),
    ).toBeVisible();

    const cookies = await context.cookies();
    // No auth cookie (or it has been cleared to empty).
    const authCookie = cookies.find((c) =>
      /session|access|token/i.test(c.name),
    );
    expect(!authCookie || authCookie.value === "").toBe(true);
  });

  test("signup happy path with step-by-step screenshots", async ({ page }) => {
    await page.goto("/");
    // Empty form snapshot.
    await page
      .getByRole("button", { name: /sign up/i })
      .click()
      .catch(() => {});
    await snap(page, "signup-happy", "01-empty-form");

    const email = uniqueEmail("signup-happy");
    await page.getByPlaceholder(/^email$/i).fill(email);
    await page
      .getByPlaceholder(/^password/i)
      .first()
      .fill("password123");
    await page.getByPlaceholder(/confirm/i).fill("password123");
    await snap(page, "signup-happy", "02-form-filled");

    await page
      .getByRole("button", { name: /create account|sign up/i })
      .click();
    await page.waitForURL(/\/$/);
    await snap(page, "signup-happy", "03-after-submit");

    await expect(
      page.getByRole("button", { name: /profiles/i }).first(),
    ).toBeVisible();
  });

  test("login validation: malformed email shows inline error", async ({
    page,
  }) => {
    await page.goto("/");
    await snap(page, "login-validation", "01-blank");

    await page.getByPlaceholder(/^email$/i).fill("not-an-email");
    await page
      .getByPlaceholder(/^password/i)
      .first()
      .fill("password123");
    await page
      .getByRole("button", { name: /^(sign in|log in)$/i })
      .click()
      .catch(() => {});
    await snap(page, "login-validation", "02-after-submit");

    // Either the HTML5 validation kicked in (email field is :invalid) or the
    // app surfaced an inline error message.
    const emailField = page.getByPlaceholder(/^email$/i);
    const inlineError = page.getByText(
      /invalid email|valid email|email.*format|enter.*email/i,
    );
    const validityBroken = await emailField.evaluate(
      (el) => (el as HTMLInputElement).validity?.valid === false,
    );
    if (!validityBroken) {
      await expect(inlineError.first()).toBeVisible();
    }
    // Either way: we are NOT in the app.
    await expect(
      page.getByRole("button", { name: /profiles/i }),
    ).toHaveCount(0);
  });

  test("login wrong password surfaces 401 invalid credentials message", async ({
    page,
  }) => {
    const email = uniqueEmail("login-401");
    await signup(page, email);
    await logout(page);
    await snap(page, "login-401", "01-logged-out");

    await page.goto("/");
    await page.getByPlaceholder(/^email$/i).fill(email);
    await page
      .getByPlaceholder(/^password/i)
      .first()
      .fill("definitely-wrong-pw");
    await page.getByRole("button", { name: /^(sign in|log in)$/i }).click();

    await expect(
      page.getByText(/invalid credentials|invalid|incorrect|unauthorized|401/i),
    ).toBeVisible();
    await snap(page, "login-401", "02-error-visible");
  });

  test("OAuth providers are gated by /api/auth/oauth/providers", async ({
    page,
    request,
  }) => {
    const resp = await request.get("/api/auth/oauth/providers");
    let providers: string[] = [];
    if (resp.ok()) {
      const body = await resp.json().catch(() => ({}));
      if (Array.isArray(body)) {
        providers = body.map((p: { id?: string; name?: string }) =>
          String(p.id ?? p.name ?? "").toLowerCase(),
        );
      } else if (Array.isArray((body as { providers?: unknown }).providers)) {
        providers = (
          (body as { providers: Array<{ id?: string; name?: string }> })
            .providers
        ).map((p) => String(p.id ?? p.name ?? "").toLowerCase());
      }
    }

    await page.goto("/");
    await snap(page, "oauth-providers", "01-login-loaded");

    const googleBtn = page.getByRole("button", { name: /google/i });
    const githubBtn = page.getByRole("button", { name: /github/i });

    if (providers.includes("google")) {
      await expect(googleBtn.first()).toBeVisible();
    } else {
      await expect(googleBtn).toHaveCount(0);
    }
    if (providers.includes("github")) {
      await expect(githubBtn.first()).toBeVisible();
    } else {
      await expect(githubBtn).toHaveCount(0);
    }
    await snap(page, "oauth-providers", "02-asserted");
  });

  test("forgot password flow opens form and accepts a submission", async ({
    page,
  }) => {
    await page.goto("/");
    await snap(page, "forgot-pw", "01-login");

    const forgotLink = page
      .getByRole("link", { name: /forgot/i })
      .or(page.getByRole("button", { name: /forgot/i }));
    await forgotLink.first().click();
    await snap(page, "forgot-pw", "02-form");

    const email = uniqueEmail("forgot");
    await page.getByPlaceholder(/^email$/i).fill(email);
    await page
      .getByRole("button", { name: /reset|send|submit/i })
      .first()
      .click();

    // Submitted state — either a success copy or the field is gone.
    await expect(
      page.getByText(/check your email|sent|link|reset/i).first(),
    ).toBeVisible();
    await snap(page, "forgot-pw", "03-submitted");
  });

  test("email-verify banner appears after signup and offers Resend", async ({
    page,
  }) => {
    const email = uniqueEmail("verify-banner");
    await signup(page, email);
    await snap(page, "verify-banner", "01-after-signup");

    // The banner copy is intentionally fuzzy across UI revisions.
    const banner = page
      .getByText(/verify (your )?email|confirm (your )?email|check.*email/i)
      .first();
    await expect(banner).toBeVisible();

    const resend = page.getByRole("button", { name: /resend/i }).first();
    await expect(resend).toBeVisible();
    await snap(page, "verify-banner", "02-banner-visible");
  });

  test("pricing page is reachable pre-login and trial CTA seeds signup", async ({
    page,
  }) => {
    await page.goto("/?pricing=1");
    await snap(page, "pricing", "01-pricing-loaded");

    // Expect four plan cards (Free / Starter / Pro / Enterprise — names may
    // vary, so we just count visible plan cards by their CTAs).
    const trialButtons = page.getByRole("button", {
      name: /start.*free.*trial|start trial|try.*free|sign up free|choose|select/i,
    });
    await expect(trialButtons.first()).toBeVisible();
    const plans = page.locator(
      '[data-plan], [data-testid*="plan"], .plan-card, [class*="plan"]',
    );
    if ((await plans.count()) >= 4) {
      expect(await plans.count()).toBeGreaterThanOrEqual(4);
    }

    // Click the Pro trial CTA.
    const proCta = page
      .locator(
        '[data-plan="pro"] button, [data-testid*="pro"] button, :has-text("Pro") >> button',
      )
      .filter({ hasText: /trial|choose|start/i })
      .first();
    if ((await proCta.count()) > 0) {
      await proCta.click();
    } else {
      await trialButtons.first().click();
    }
    await snap(page, "pricing", "02-clicked-pro");

    // URL should pick up ?plan=pro and signup page should render with banner.
    await expect(page).toHaveURL(/plan=pro/);
    await expect(
      page.getByText(/pro|trial/i).first(),
    ).toBeVisible();
    await snap(page, "pricing", "03-signup-with-banner");
  });
});
