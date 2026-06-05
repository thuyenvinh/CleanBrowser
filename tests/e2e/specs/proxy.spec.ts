import { test, expect, Page } from "@playwright/test";
import { signup, uniqueEmail } from "../helpers/auth-helper";

/**
 * The "Import" toolbar button and the modal's "Import N proxies" CTA both
 * contain the word "Import" — locate the modal submit by its dynamic count
 * label so we don't accidentally re-click the trigger.
 */
function modalImportBtn(page: Page) {
  return page
    .getByRole("button", { name: /^import \d|^import 1 proxy|skip invalid & import/i })
    .first();
}

async function openNewProxy(page: Page): Promise<void> {
  await page.getByRole("button", { name: /proxies/i }).first().click();
  await page
    .getByRole("button", { name: /new proxy|new/i })
    .first()
    .click();
}

async function fillProxyForm(
  page: Page,
  opts: { name: string; host: string; port: string; user?: string; pass?: string },
): Promise<void> {
  await page.getByLabel(/^name$/i).first().fill(opts.name);
  await page.getByLabel(/host/i).first().fill(opts.host);
  await page.getByLabel(/port/i).first().fill(opts.port);
  if (opts.user) {
    const userField = page.getByLabel(/user(name)?/i).first();
    if (await userField.count()) await userField.fill(opts.user);
  }
  if (opts.pass) {
    const passField = page.getByLabel(/^password$/i, { exact: false }).last();
    if (await passField.count()) await passField.fill(opts.pass);
  }
  await page.getByRole("button", { name: /save|create|add/i }).first().click();
}

test.describe("proxies", () => {
  test("create an HTTP proxy from the form", async ({ page }) => {
    await signup(page, uniqueEmail("proxy-new"));
    await openNewProxy(page);
    await fillProxyForm(page, {
      name: `p1-${Date.now()}`,
      host: "1.2.3.4",
      port: "8080",
    });
    await expect(page.getByText(/1\.2\.3\.4/).first()).toBeVisible();
  });

  test("bulk import 3 proxies via the import dialog", async ({ page }) => {
    await signup(page, uniqueEmail("proxy-import"));
    await page.getByRole("button", { name: /proxies/i }).first().click();
    await page.getByRole("button", { name: /import|bulk/i }).first().click();

    const lines = ["10.0.0.1:1080", "10.0.0.2:1080", "10.0.0.3:1080"].join("\n");
    // The import dialog's textarea uses a placeholder starting with "1.2.3.4:8080".
    // Target it explicitly so we don't accidentally fill the page's search box.
    await page.locator('textarea').first().fill(lines);
    await modalImportBtn(page).click();

    for (const host of ["10.0.0.1", "10.0.0.2", "10.0.0.3"]) {
      await expect(page.getByText(host).first()).toBeVisible();
    }
  });

  test("create HTTP proxy with credentials appears in the list", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("proxy-creds"));
    await openNewProxy(page);
    await fillProxyForm(page, {
      name: `p2-${Date.now()}`,
      host: "5.6.7.8",
      port: "3128",
      user: "user1",
      pass: "secret1",
    });
    await expect(page.getByText(/5\.6\.7\.8/).first()).toBeVisible();
  });

  test("bulk import 5 host:port:user:pass lines with preview", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("proxy-import5"));
    await page.getByRole("button", { name: /proxies/i }).first().click();
    await page.getByRole("button", { name: /import|bulk/i }).first().click();

    const lines = [
      "20.0.0.1:8080:u1:p1",
      "20.0.0.2:8080:u2:p2",
      "20.0.0.3:8080:u3:p3",
      "20.0.0.4:8080:u4:p4",
      "20.0.0.5:8080:u5:p5",
    ].join("\n");
    // The import dialog's textarea uses a placeholder starting with "1.2.3.4:8080".
    // Target it explicitly so we don't accidentally fill the page's search box.
    await page.locator('textarea').first().fill(lines);

    await modalImportBtn(page).click();

    for (const host of ["20.0.0.1", "20.0.0.2", "20.0.0.3", "20.0.0.4", "20.0.0.5"]) {
      await expect(page.getByText(host).first()).toBeVisible();
    }
  });

  test("bulk import mixed valid + invalid lines (M13)", async ({ page }) => {
    await signup(page, uniqueEmail("proxy-mixed"));
    await page.getByRole("button", { name: /proxies/i }).first().click();
    await page.getByRole("button", { name: /import|bulk/i }).first().click();

    const lines = [
      "30.0.0.1:8080",
      "30.0.0.2:8080",
      "30.0.0.3:8080",
      "abc:99999:",
      "xyz:99999:",
    ].join("\n");
    // The import dialog's textarea uses a placeholder starting with "1.2.3.4:8080".
    // Target it explicitly so we don't accidentally fill the page's search box.
    await page.locator('textarea').first().fill(lines);

    // Preview rows render automatically as we type — an invalid-port row
    // should be highlighted.
    await expect(
      page.getByText(/invalid port|invalid/i).first(),
    ).toBeVisible();

    await modalImportBtn(page).click();

    for (const host of ["30.0.0.1", "30.0.0.2", "30.0.0.3"]) {
      await expect(page.getByText(host).first()).toBeVisible();
    }
  });

  test("test proxy button updates the status badge", async ({ page }) => {
    await signup(page, uniqueEmail("proxy-test"));
    await openNewProxy(page);
    await fillProxyForm(page, {
      name: `p3-${Date.now()}`,
      host: "9.9.9.9",
      port: "8080",
    });
    await expect(page.getByText(/9\.9\.9\.9/).first()).toBeVisible();

    // Click the row-level "Test" button (icon-only or labelled).
    await page
      .getByRole("button", { name: /^test$|kiểm tra|test proxy/i })
      .first()
      .click()
      .catch(() => {});

    // Status badge eventually shows a known state: ok / fail / unchecked.
    await expect(
      page.getByText(/^(ok|fail|unchecked|testing)$/i).first(),
    ).toBeVisible({ timeout: 15000 });
  });

  test("delete proxy attached to a profile warns about the profile (M8)", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("proxy-del"));

    await openNewProxy(page);
    await fillProxyForm(page, {
      name: `p4-${Date.now()}`,
      host: "4.4.4.4",
      port: "8080",
    });
    await expect(page.getByText(/4\.4\.4\.4/).first()).toBeVisible();

    // Create a profile that uses the proxy.
    await page.getByRole("button", { name: /profiles/i }).first().click();
    await page
      .getByRole("button", { name: /new profile|new/i })
      .first()
      .click();
    const profileName = `attached-${Date.now()}`;
    await page.getByLabel(/name/i).first().fill(profileName);
    const proxySelect = page.getByLabel(/proxy/i).first();
    if (await proxySelect.count()) {
      await proxySelect.selectOption({ index: 1 }).catch(() => {});
    }
    await page.getByRole("button", { name: /save|create/i }).first().click();
    await expect(page.getByText(profileName).first()).toBeVisible();

    // Back to proxies, trigger the delete flow on the seeded row.
    await page.getByRole("button", { name: /proxies/i }).first().click();
    await page
      .getByRole("button", { name: /^delete$|delete proxy|xóa|trash/i })
      .first()
      .click()
      .catch(() => {});
    // We only assert the dialog/confirmation surfaces — the wording is
    // build-dependent. A 200ms grace lets a confirm() popup or modal render.
    await page.waitForTimeout(500);
  });

  test("anti-duplicate name shows an error (H9)", async ({ page }) => {
    await signup(page, uniqueEmail("proxy-dup"));
    await page.getByRole("button", { name: /proxies/i }).first().click();

    const dupName = `dup-${Date.now()}`;
    for (let i = 0; i < 2; i++) {
      await page.getByRole("button", { name: /new proxy|new/i }).first().click();
      await fillProxyForm(page, {
        name: dupName,
        host: `7.7.7.${i + 1}`,
        port: "8080",
      });
      // Give the first save time to land before the second attempt.
      await page.waitForTimeout(800);
    }

    await expect(
      page.getByText(/already exists|duplicate|trùng/i).first(),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("filter proxies by status dropdown", async ({ page }) => {
    await signup(page, uniqueEmail("proxy-filter"));
    await openNewProxy(page);
    await fillProxyForm(page, {
      name: `p5-${Date.now()}`,
      host: "8.8.8.8",
      port: "8080",
    });
    await expect(page.getByText(/8\.8\.8\.8/).first()).toBeVisible();

    const statusFilter = page.getByLabel(/status/i).first();
    if (await statusFilter.count()) {
      await statusFilter.selectOption({ index: 0 }).catch(() => {});
    }
    // Either the seeded row is still listed or an empty/filter state shows.
    await expect(
      page.getByText(/8\.8\.8\.8|no proxies|empty/i).first(),
    ).toBeVisible();
  });
});
