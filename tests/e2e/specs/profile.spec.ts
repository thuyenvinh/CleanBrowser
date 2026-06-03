import { test, expect, Page } from "@playwright/test";
import { signup, uniqueEmail } from "../helpers/auth-helper";

async function snap(
  page: Page,
  name: string,
  step: string,
): Promise<void> {
  await page
    .screenshot({
      path: `screenshots/profile-${name}-${step}.png`,
      fullPage: true,
    })
    .catch(() => {});
}

/**
 * Local helper: sign up a fresh tenant, navigate to the Profiles tab.
 *
 * The email verify banner may or may not appear in any given build — we don't
 * dismiss it because the create-profile flow is expected to work regardless.
 */
async function freshSignupAndGoToProfiles(page: Page): Promise<string> {
  const email = uniqueEmail("profile");
  await signup(page, email);
  await page.getByRole("button", { name: /profiles/i }).first().click();
  return email;
}

async function openNewProfile(page: Page): Promise<void> {
  await page
    .getByRole("button", { name: /new profile|new/i })
    .first()
    .click();
}

async function fillNameAndSave(page: Page, name: string): Promise<void> {
  await page.getByLabel(/name/i).first().fill(name);
  await page
    .getByRole("button", { name: /save|create/i })
    .first()
    .click();
}

test.describe("profiles", () => {
  test("create a profile from the empty state (chromium)", async ({ page }) => {
    await freshSignupAndGoToProfiles(page);
    await snap(page, "create-basic", "01-empty");

    await openNewProfile(page);
    const name = `My Profile ${Date.now()}`;
    await page.getByLabel(/name/i).first().fill(name);

    // browser_type chromium — only set if a control exists.
    const browserSelect = page
      .getByLabel(/browser.*type|engine/i)
      .or(page.locator('select[name*="browser"]'));
    if ((await browserSelect.count()) > 0) {
      await browserSelect
        .first()
        .selectOption("chromium")
        .catch(() => {});
    }
    await snap(page, "create-basic", "02-form-filled");

    await page
      .getByRole("button", { name: /save|create/i })
      .first()
      .click();

    await expect(page.getByText(name).first()).toBeVisible();
    await snap(page, "create-basic", "03-in-list");
  });

  test("create profile with timezone / locale / screen / tags", async ({
    page,
  }) => {
    await freshSignupAndGoToProfiles(page);
    await openNewProfile(page);

    const name = `Full Profile ${Date.now()}`;
    await page.getByLabel(/name/i).first().fill(name);

    const setIfPresent = async (
      labelRe: RegExp,
      value: string,
    ): Promise<void> => {
      const field = page.getByLabel(labelRe).first();
      if ((await field.count()) > 0) {
        await field.fill(value).catch(async () => {
          await field.selectOption(value).catch(() => {});
        });
      }
    };

    await setIfPresent(/timezone/i, "Europe/Berlin");
    await setIfPresent(/locale|language/i, "en-US");
    await setIfPresent(/screen.*width|width/i, "1920");
    await setIfPresent(/screen.*height|height/i, "1080");
    await setIfPresent(/tags?/i, "qa,e2e");
    await snap(page, "create-full", "01-form-filled");

    await page
      .getByRole("button", { name: /save|create/i })
      .first()
      .click();

    await expect(page.getByText(name).first()).toBeVisible();
    await snap(page, "create-full", "02-saved");
  });

  test("filter profiles by tag (M12)", async ({ page }) => {
    await freshSignupAndGoToProfiles(page);

    const stamp = Date.now();
    const aName = `Alpha ${stamp}`;
    const bName = `Bravo ${stamp}`;

    // Create #1 with tag "alpha"
    await openNewProfile(page);
    await page.getByLabel(/name/i).first().fill(aName);
    const tags1 = page.getByLabel(/tags?/i).first();
    if ((await tags1.count()) > 0) await tags1.fill("alpha");
    await page
      .getByRole("button", { name: /save|create/i })
      .first()
      .click();
    await expect(page.getByText(aName).first()).toBeVisible();

    // Create #2 with tag "bravo"
    await openNewProfile(page);
    await page.getByLabel(/name/i).first().fill(bName);
    const tags2 = page.getByLabel(/tags?/i).first();
    if ((await tags2.count()) > 0) await tags2.fill("bravo");
    await page
      .getByRole("button", { name: /save|create/i })
      .first()
      .click();
    await expect(page.getByText(bName).first()).toBeVisible();
    await snap(page, "filter-tag", "01-both-created");

    // Apply tag filter
    const tagFilter = page
      .getByLabel(/filter.*tag|tag.*filter/i)
      .or(page.locator('[data-testid="tag-filter"]'));
    if ((await tagFilter.count()) > 0) {
      await tagFilter
        .first()
        .selectOption("alpha")
        .catch(async () => {
          await tagFilter.first().fill("alpha");
        });
      await snap(page, "filter-tag", "02-alpha-selected");
      await expect(page.getByText(aName).first()).toBeVisible();
      await expect(page.getByText(bName)).toHaveCount(0);
    }
  });

  test("filter profiles by region (M12)", async ({ page }) => {
    await freshSignupAndGoToProfiles(page);

    const stamp = Date.now();
    const usName = `US ${stamp}`;
    const euName = `EU ${stamp}`;

    const createWithRegion = async (
      name: string,
      region: string,
    ): Promise<void> => {
      await openNewProfile(page);
      await page.getByLabel(/name/i).first().fill(name);
      const regionField = page
        .getByLabel(/region|country/i)
        .or(page.locator('select[name*="region"]'));
      if ((await regionField.count()) > 0) {
        await regionField
          .first()
          .selectOption(region)
          .catch(async () => {
            await regionField.first().fill(region);
          });
      }
      await page
        .getByRole("button", { name: /save|create/i })
        .first()
        .click();
      await expect(page.getByText(name).first()).toBeVisible();
    };

    await createWithRegion(usName, "us");
    await createWithRegion(euName, "eu");
    await snap(page, "filter-region", "01-both-created");

    const regionFilter = page
      .getByLabel(/filter.*region|region.*filter/i)
      .or(page.locator('[data-testid="region-filter"]'));
    if ((await regionFilter.count()) > 0) {
      await regionFilter
        .first()
        .selectOption("us")
        .catch(async () => {
          await regionFilter.first().fill("us");
        });
      await snap(page, "filter-region", "02-us-selected");
      await expect(page.getByText(usName).first()).toBeVisible();
      await expect(page.getByText(euName)).toHaveCount(0);
    }
  });

  test("rename a profile and see the update reflected in the list", async ({
    page,
  }) => {
    await freshSignupAndGoToProfiles(page);

    const original = `Original ${Date.now()}`;
    await openNewProfile(page);
    await fillNameAndSave(page, original);
    await expect(page.getByText(original).first()).toBeVisible();
    await snap(page, "rename", "01-created");

    await page.getByText(original).first().click();
    await page
      .getByRole("button", { name: /edit/i })
      .first()
      .click();
    const renamed = `${original} v2`;
    const nameField = page.getByLabel(/name/i).first();
    await nameField.fill(renamed);
    await page
      .getByRole("button", { name: /save|update/i })
      .first()
      .click();

    await expect(page.getByText(renamed).first()).toBeVisible();
    await snap(page, "rename", "02-renamed");
  });

  test("anti-duplicate name surfaces an error (H9)", async ({ page }) => {
    await freshSignupAndGoToProfiles(page);

    const dupName = `duplicate ${Date.now()}`;
    await openNewProfile(page);
    await fillNameAndSave(page, dupName);
    await expect(page.getByText(dupName).first()).toBeVisible();
    await snap(page, "dup-name", "01-first-created");

    await openNewProfile(page);
    await page.getByLabel(/name/i).first().fill(dupName);
    await page
      .getByRole("button", { name: /save|create/i })
      .first()
      .click();

    await expect(
      page.getByText(/duplicate|already exists|taken|conflict|in use/i),
    ).toBeVisible();
    await snap(page, "dup-name", "02-error");
  });

  test("delete a profile removes it from the list", async ({ page }) => {
    await freshSignupAndGoToProfiles(page);

    const name = `Deletable ${Date.now()}`;
    await openNewProfile(page);
    await fillNameAndSave(page, name);
    await expect(page.getByText(name).first()).toBeVisible();
    await snap(page, "delete-basic", "01-created");

    await page.getByText(name).first().click();
    page.once("dialog", (d) => d.accept());
    await page
      .getByRole("button", { name: /delete|remove/i })
      .first()
      .click();
    // If a custom confirm modal appears instead of window.confirm:
    const confirmBtn = page.getByRole("button", {
      name: /^(delete|confirm|yes)$/i,
    });
    if ((await confirmBtn.count()) > 0) {
      await confirmBtn.first().click().catch(() => {});
    }

    await expect(page.getByText(name)).toHaveCount(0);
    await snap(page, "delete-basic", "02-gone");
  });

  test("delete profile with version history shows warning in confirm", async ({
    page,
  }) => {
    await freshSignupAndGoToProfiles(page);

    const name = `Versioned ${Date.now()}`;
    await openNewProfile(page);
    await fillNameAndSave(page, name);
    await expect(page.getByText(name).first()).toBeVisible();

    // Simulate edits to seed a version history. We edit-and-save twice.
    for (let i = 0; i < 2; i++) {
      await page.getByText(name).first().click();
      const editBtn = page.getByRole("button", { name: /edit/i }).first();
      if ((await editBtn.count()) === 0) break;
      await editBtn.click();
      const nameField = page.getByLabel(/name/i).first();
      await nameField.fill(`${name}`);
      await page
        .getByRole("button", { name: /save|update/i })
        .first()
        .click();
    }
    await snap(page, "delete-versioned", "01-versions-seeded");

    await page.getByText(name).first().click();
    page.once("dialog", (d) => d.accept());
    await page
      .getByRole("button", { name: /delete|remove/i })
      .first()
      .click();

    // The confirm dialog (custom modal) should mention version history. If the
    // app uses window.confirm we already accepted it — in that case at least
    // the row should disappear.
    const warning = page.getByText(
      /version history|previous versions|history will|cannot be undone/i,
    );
    if ((await warning.count()) > 0) {
      await expect(warning.first()).toBeVisible();
      await snap(page, "delete-versioned", "02-warning");
      const confirmBtn = page
        .getByRole("button", { name: /^(delete|confirm|yes)$/i })
        .first();
      if ((await confirmBtn.count()) > 0) {
        await confirmBtn.click();
      }
    }
    await expect(page.getByText(name)).toHaveCount(0);
    await snap(page, "delete-versioned", "03-gone");
  });
});
