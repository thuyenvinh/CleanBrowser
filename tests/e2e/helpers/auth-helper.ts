import { Page, APIRequestContext } from "@playwright/test";

/**
 * Drive the signup form in the UI and wait for the app shell to mount.
 *
 * The auth pages use placeholder-only inputs (no <label> elements), so we
 * select by placeholder rather than label. The switcher from Login → Signup
 * is a small "Sign up" text button below the form; the submit button on
 * the SignupPage itself is also labelled "Sign up", so we disambiguate by
 * waiting for the Signup-only "Confirm password" placeholder before filling.
 */
export async function signup(
  page: Page,
  email: string,
  password = "password123",
): Promise<void> {
  // Use the JSON signup endpoint to create the account and capture the
  // session cookie from the response, then inject it into the browser
  // context so the subsequent navigation lands directly in the app shell.
  // UI-driven signup is exercised separately in auth.spec.ts via
  // `signupViaUI` — this fast path is for setup in other specs.
  const resp = await page.request.post("/api/auth/signup", {
    data: { email, password },
  });
  if (!resp.ok()) {
    throw new Error(`signup failed ${resp.status()}: ${await resp.text()}`);
  }

  // Copy cookies from the request context to the browser context.
  const cookies = await page.request.storageState();
  await page.context().addCookies(cookies.cookies);

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page
    .getByRole("button", { name: /profiles|proxies|automations/i })
    .first()
    .waitFor({ timeout: 15_000 });
}

/**
 * UI-driven signup — call this only from specs that explicitly test the
 * signup form (auth.spec.ts). All other specs should use `signup()` which
 * is the fast API-based variant.
 */
export async function signupViaUI(
  page: Page,
  email: string,
  password = "password123",
): Promise<void> {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  // Wait for the heading to confirm an auth page is rendered.
  await page
    .getByRole("heading", { name: /CloakBrowser Manager|CleanBrowser|Create your account|Welcome back/i })
    .first()
    .waitFor({ timeout: 10_000 });

  // If on LoginPage, click the inline "Sign up" link first.
  const confirmField = page.getByPlaceholder(/confirm/i);
  if (!(await confirmField.isVisible().catch(() => false))) {
    await page.getByRole("button", { name: /^sign up$/i }).click({ timeout: 5_000 }).catch(() => {});
    await confirmField.waitFor({ timeout: 10_000 });
  }

  await page.getByPlaceholder(/^email$/i).fill(email);
  await page.getByPlaceholder(/^password \(min/i).fill(password);
  await page.getByPlaceholder(/confirm/i).fill(password);

  await page.getByRole("button", { name: /^(sign up|create account)$/i }).click();
  await page
    .getByRole("button", { name: /profiles|proxies|automations/i })
    .first()
    .waitFor({ timeout: 15_000 });
}

/**
 * Log in via the UI form (placeholder-based inputs).
 */
export async function login(
  page: Page,
  email: string,
  password = "password123",
): Promise<void> {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByPlaceholder(/^email$/i).fill(email);
  await page.getByPlaceholder(/^password$/i).fill(password);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page
    .getByRole("button", { name: /profiles|proxies|automations/i })
    .first()
    .waitFor({ timeout: 15_000 });
}

/**
 * Click the logout control (lock icon in the top bar).
 */
export async function logout(page: Page): Promise<void> {
  // The logout control is a small button with title "Log out" rendering a
  // lock icon — getByTitle is more reliable than role-based regex.
  await page.getByTitle(/log out/i).click().catch(async () => {
    // Fallback: try role-based search
    await page
      .getByRole("button", { name: /log out|sign out|logout/i })
      .first()
      .click();
  });
}

export function uniqueEmail(prefix = "e2e"): string {
  return `${prefix}+${Date.now()}-${Math.random()
    .toString(36)
    .slice(2, 8)}@e2e.example.com`;
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

// Export thêm các helper UI level cho specs mới
export async function clickTab(
  page: Page,
  name:
    | "profiles"
    | "proxies"
    | "automations"
    | "marketplace"
    | "billing"
    | "security"
    | "apikeys",
): Promise<void> {
  await page
    .getByRole("button", { name: new RegExp(name, "i") })
    .first()
    .click();
}

export async function waitForAuthenticated(
  page: Page,
  timeoutMs = 10_000,
): Promise<void> {
  await page.waitForFunction(
    () =>
      !!document.querySelector("[data-testid=app-shell]") ||
      !!document.querySelector('button[title*="Hide sidebar" i]'),
    null,
    { timeout: timeoutMs },
  );
}
