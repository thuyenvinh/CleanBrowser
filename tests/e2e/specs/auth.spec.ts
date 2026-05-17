import { test, expect } from "@playwright/test";
import { signup, login, logout, uniqueEmail } from "../helpers/auth-helper";

test.describe("auth", () => {
  test("signup creates tenant + default workspace and lands in the app", async ({
    page,
    context,
  }) => {
    const email = uniqueEmail("signup");
    await signup(page, email);

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

    // Bad password first.
    await page.goto("/");
    await page.getByLabel(/email/i).fill(email);
    await page
      .getByLabel(/password/i, { exact: true })
      .first()
      .fill("wrong-password");
    await page.getByRole("button", { name: /^(sign in|log in)$/i }).click();
    await expect(
      page.getByText(/invalid|incorrect|unauthorized|401/i),
    ).toBeVisible();

    // Now the right password.
    await login(page, email);
    await expect(
      page.getByRole("button", { name: /profiles/i }).first(),
    ).toBeVisible();
  });

  test("logout clears the session and returns to login", async ({
    page,
    context,
  }) => {
    const email = uniqueEmail("logout");
    await signup(page, email);

    await logout(page);

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
});
