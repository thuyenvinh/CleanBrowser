import { Page, APIRequestContext } from "@playwright/test";

/**
 * Drive the signup form in the UI and wait for the app shell to mount.
 *
 * The form is forgiving about which heading is currently rendered (the
 * landing page might already show "Sign up" or it might require clicking a
 * "Sign up" link first), so the initial click is best-effort.
 */
export async function signup(
  page: Page,
  email: string,
  password = "password123",
): Promise<void> {
  await page.goto("/");
  // If we landed on the login page, follow the "Sign up" link first.
  await page
    .getByRole("button", { name: /sign up/i })
    .click()
    .catch(() => {});
  await page.getByLabel(/email/i).fill(email);
  await page
    .getByLabel(/password/i, { exact: true })
    .first()
    .fill(password);
  await page.getByLabel(/confirm/i).fill(password);
  await page
    .getByRole("button", { name: /create account|sign up/i })
    .click();
  // After signup we expect to be at the app root with the shell mounted.
  await page.waitForURL(/\/$/);
}

/**
 * Log in via the UI form.
 */
export async function login(
  page: Page,
  email: string,
  password = "password123",
): Promise<void> {
  await page.goto("/");
  await page.getByLabel(/email/i).fill(email);
  await page
    .getByLabel(/password/i, { exact: true })
    .first()
    .fill(password);
  await page.getByRole("button", { name: /^(sign in|log in)$/i }).click();
  await page.waitForURL(/\/$/);
}

/**
 * Click the logout control in the workspace selector / user menu.
 */
export async function logout(page: Page): Promise<void> {
  await page
    .getByRole("button", { name: /log out|sign out|logout/i })
    .first()
    .click();
}

export function uniqueEmail(prefix = "e2e"): string {
  return `${prefix}+${Date.now()}-${Math.random()
    .toString(36)
    .slice(2, 8)}@example.test`;
}

/**
 * Hit the JSON signup endpoint directly. Useful when the test only needs an
 * authenticated session to set up state, not to exercise the form itself.
 *
 * Returns the parsed JSON body so callers can grab the access token /
 * tenant ID if they need it.
 */
export async function apiSignup(
  req: APIRequestContext,
  email: string,
  password = "password123",
): Promise<unknown> {
  const r = await req.post("/api/auth/signup", {
    data: { email, password },
  });
  if (!r.ok()) {
    throw new Error(`signup failed ${r.status()} ${await r.text()}`);
  }
  return r.json();
}

/**
 * Hit the JSON login endpoint directly. Same rationale as `apiSignup`.
 */
export async function apiLogin(
  req: APIRequestContext,
  email: string,
  password = "password123",
): Promise<unknown> {
  const r = await req.post("/api/auth/login", {
    data: { email, password },
  });
  if (!r.ok()) {
    throw new Error(`login failed ${r.status()} ${await r.text()}`);
  }
  return r.json();
}
