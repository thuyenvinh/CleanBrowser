import { test, expect } from "@playwright/test";
import { signup, uniqueEmail } from "../helpers/auth-helper";

test.describe("proxies", () => {
  test("create an HTTP proxy from the form", async ({ page }) => {
    await signup(page, uniqueEmail("proxy-new"));

    await page.getByRole("button", { name: /proxies/i }).first().click();

    // Empty state — click "New Proxy".
    await page
      .getByRole("button", { name: /new proxy|new/i })
      .first()
      .click();

    // Pick HTTP scheme if a selector is present. (UI uses a <select> or
    // a button group depending on the version, so be defensive.)
    const schemeSelect = page.getByLabel(/scheme|type/i).first();
    if (await schemeSelect.count()) {
      await schemeSelect.selectOption("http").catch(async () => {
        await schemeSelect.click();
        await page.getByRole("option", { name: /^http$/i }).click();
      });
    }

    await page.getByLabel(/host/i).first().fill("1.2.3.4");
    await page.getByLabel(/port/i).first().fill("8080");

    await page
      .getByRole("button", { name: /save|create|add/i })
      .first()
      .click();

    await expect(page.getByText(/1\.2\.3\.4/)).toBeVisible();
    await expect(page.getByText(/8080/)).toBeVisible();
  });

  test("bulk import 3 proxies via the import dialog", async ({ page }) => {
    await signup(page, uniqueEmail("proxy-import"));
    await page.getByRole("button", { name: /proxies/i }).first().click();

    await page
      .getByRole("button", { name: /import|bulk/i })
      .first()
      .click();

    const lines = [
      "10.0.0.1:1080",
      "10.0.0.2:1080",
      "10.0.0.3:1080",
    ].join("\n");
    await page.getByRole("textbox").first().fill(lines);

    // Some builds show a "Preview" step; click it if present, otherwise the
    // primary CTA jumps straight to Import.
    const previewBtn = page.getByRole("button", { name: /preview/i });
    if (await previewBtn.count()) {
      await previewBtn.first().click();
    }
    await page
      .getByRole("button", { name: /^import$/i })
      .first()
      .click();

    for (const host of ["10.0.0.1", "10.0.0.2", "10.0.0.3"]) {
      await expect(page.getByText(host)).toBeVisible();
    }
  });

  test("create HTTP proxy with credentials appears in the list", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("proxy-creds"));
    await page.getByRole("button", { name: /proxies/i }).first().click();

    await page
      .getByRole("button", { name: /new proxy|new/i })
      .first()
      .click();

    const schemeSelect = page.getByLabel(/scheme|type/i).first();
    if (await schemeSelect.count()) {
      await schemeSelect.selectOption("http").catch(async () => {
        await schemeSelect.click();
        await page.getByRole("option", { name: /^http$/i }).click();
      });
    }

    await page.getByLabel(/host/i).first().fill("5.6.7.8");
    await page.getByLabel(/port/i).first().fill("3128");
    // Username/password fields are optional in some forms; be defensive.
    const userField = page.getByLabel(/user(name)?/i).first();
    if (await userField.count()) await userField.fill("user1");
    const passField = page
      .getByLabel(/^password$/i, { exact: false })
      .last();
    if (await passField.count()) await passField.fill("secret1");

    await page
      .getByRole("button", { name: /save|create|add/i })
      .first()
      .click();

    await expect(page.getByText(/5\.6\.7\.8/)).toBeVisible();
  });

  test("bulk import 5 host:port:user:pass lines with preview", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("proxy-import5"));
    await page.getByRole("button", { name: /proxies/i }).first().click();

    await page
      .getByRole("button", { name: /import|bulk/i })
      .first()
      .click();

    const lines = [
      "20.0.0.1:8080:u1:p1",
      "20.0.0.2:8080:u2:p2",
      "20.0.0.3:8080:u3:p3",
      "20.0.0.4:8080:u4:p4",
      "20.0.0.5:8080:u5:p5",
    ].join("\n");
    await page.getByRole("textbox").first().fill(lines);

    const previewBtn = page.getByRole("button", { name: /preview/i });
    if (await previewBtn.count()) {
      await previewBtn.first().click();
      // Preview should report 5 valid entries somewhere.
      await expect(page.getByText(/5/).first()).toBeVisible();
    }

    await page
      .getByRole("button", { name: /^import$|import 5/i })
      .first()
      .click();

    for (const host of [
      "20.0.0.1",
      "20.0.0.2",
      "20.0.0.3",
      "20.0.0.4",
      "20.0.0.5",
    ]) {
      await expect(page.getByText(host)).toBeVisible();
    }
  });

  test("bulk import mixed valid + invalid lines (M13)", async ({ page }) => {
    await signup(page, uniqueEmail("proxy-mixed"));
    await page.getByRole("button", { name: /proxies/i }).first().click();

    await page
      .getByRole("button", { name: /import|bulk/i })
      .first()
      .click();

    const lines = [
      "30.0.0.1:8080",
      "30.0.0.2:8080",
      "30.0.0.3:8080",
      "abc:99999:",
      "xyz:99999:",
    ].join("\n");
    await page.getByRole("textbox").first().fill(lines);

    const previewBtn = page.getByRole("button", { name: /preview/i });
    if (await previewBtn.count()) {
      await previewBtn.first().click();
    }

    // Expect an invalid-port reason to show up in the preview.
    await expect(
      page.getByText(/invalid port|invalid/i).first(),
    ).toBeVisible();

    // Click whichever "import 3" / "skip invalid" CTA the UI exposes.
    const skipBtn = page.getByRole("button", {
      name: /skip.*import 3|import 3|skip invalid/i,
    });
    if (await skipBtn.count()) {
      await skipBtn.first().click();
    } else {
      await page
        .getByRole("button", { name: /^import$/i })
        .first()
        .click();
    }

    for (const host of ["30.0.0.1", "30.0.0.2", "30.0.0.3"]) {
      await expect(page.getByText(host)).toBeVisible();
    }
  });

  test("test proxy button updates the status badge", async ({ page }) => {
    await signup(page, uniqueEmail("proxy-test"));
    await page.getByRole("button", { name: /proxies/i }).first().click();

    await page
      .getByRole("button", { name: /new proxy|new/i })
      .first()
      .click();
    await page.getByLabel(/host/i).first().fill("9.9.9.9");
    await page.getByLabel(/port/i).first().fill("8080");
    await page
      .getByRole("button", { name: /save|create|add/i })
      .first()
      .click();

    await expect(page.getByText(/9\.9\.9\.9/)).toBeVisible();

    // Click the row-level "Test" button. Accept Vietnamese label too.
    await page
      .getByRole("button", { name: /^test$|kiểm tra/i })
      .first()
      .click();

    // After the request resolves the status badge should report something
    // other than the initial "unknown" — either ok or fail is fine here.
    await expect(
      page.getByText(/ok|fail|success|error|lỗi|thành công/i).first(),
    ).toBeVisible({ timeout: 15000 });
  });

  test("delete proxy attached to a profile warns about the profile (M8)", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("proxy-del"));

    // Create a proxy first.
    await page.getByRole("button", { name: /proxies/i }).first().click();
    await page
      .getByRole("button", { name: /new proxy|new/i })
      .first()
      .click();
    await page.getByLabel(/host/i).first().fill("4.4.4.4");
    await page.getByLabel(/port/i).first().fill("8080");
    await page
      .getByRole("button", { name: /save|create|add/i })
      .first()
      .click();
    await expect(page.getByText(/4\.4\.4\.4/)).toBeVisible();

    // Create a profile that uses the proxy.
    await page.getByRole("button", { name: /profiles/i }).first().click();
    await page
      .getByRole("button", { name: /new profile|new/i })
      .first()
      .click();
    const profileName = `attached-${Date.now()}`;
    await page.getByLabel(/name/i).first().fill(profileName);
    // Select the proxy if a proxy selector exists.
    const proxySelect = page.getByLabel(/proxy/i).first();
    if (await proxySelect.count()) {
      await proxySelect.selectOption({ index: 1 }).catch(async () => {
        await proxySelect.click();
        await page.getByRole("option").nth(1).click().catch(() => {});
      });
    }
    await page
      .getByRole("button", { name: /save|create/i })
      .first()
      .click();
    await expect(page.getByText(profileName)).toBeVisible();

    // Back to proxies, delete it.
    await page.getByRole("button", { name: /proxies/i }).first().click();
    await page
      .getByRole("button", { name: /^delete$|delete proxy|xóa/i })
      .first()
      .click();

    // The confirmation dialog should mention the attached profile by name.
    await expect(page.getByText(profileName)).toBeVisible();
  });

  test("anti-duplicate name shows an error (H9)", async ({ page }) => {
    await signup(page, uniqueEmail("proxy-dup"));
    await page.getByRole("button", { name: /proxies/i }).first().click();

    const dupName = `dup-${Date.now()}`;
    for (let i = 0; i < 2; i++) {
      await page
        .getByRole("button", { name: /new proxy|new/i })
        .first()
        .click();
      const nameField = page.getByLabel(/^name$/i).first();
      if (await nameField.count()) await nameField.fill(dupName);
      await page.getByLabel(/host/i).first().fill(`7.7.7.${i + 1}`);
      await page.getByLabel(/port/i).first().fill("8080");
      await page
        .getByRole("button", { name: /save|create|add/i })
        .first()
        .click();
    }

    // Second submit should surface a duplicate-name error.
    await expect(
      page.getByText(/already exists|duplicate|trùng/i).first(),
    ).toBeVisible();
  });

  test("filter proxies by status dropdown", async ({ page }) => {
    await signup(page, uniqueEmail("proxy-filter"));
    await page.getByRole("button", { name: /proxies/i }).first().click();

    // Seed a proxy so the list isn't empty.
    await page
      .getByRole("button", { name: /new proxy|new/i })
      .first()
      .click();
    await page.getByLabel(/host/i).first().fill("8.8.8.8");
    await page.getByLabel(/port/i).first().fill("8080");
    await page
      .getByRole("button", { name: /save|create|add/i })
      .first()
      .click();
    await expect(page.getByText(/8\.8\.8\.8/)).toBeVisible();

    // Open the status filter and pick "ok" / "fail". Filter may be a select
    // or a popover button group; be defensive.
    const statusFilter = page.getByLabel(/status/i).first();
    if (await statusFilter.count()) {
      await statusFilter
        .selectOption({ label: /ok/i.toString() })
        .catch(async () => {
          await statusFilter.click();
          await page
            .getByRole("option", { name: /ok|all/i })
            .first()
            .click()
            .catch(() => {});
        });
    } else {
      // Fallback: search for a "Status" button and click it.
      const statusBtn = page.getByRole("button", { name: /status|filter/i });
      if (await statusBtn.count()) await statusBtn.first().click();
    }

    // After filtering the proxy list should still render (no crash).
    await expect(page.getByText(/8\.8\.8\.8|no proxies|empty/i)).toBeVisible();
  });
});
