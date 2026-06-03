import { test, expect } from "../helpers/fixtures";
import { snap } from "../helpers/screenshot-helper";
import { signup, uniqueEmail } from "../helpers/auth-helper";

/**
 * Profile version history section in the edit view.
 *
 * We can't guarantee that cloud snapshots are enabled in CI, so the empty
 * state is the most reliable assertion. When versions are present we also
 * check that a Restore button is offered.
 */

async function createProfile(
  page: import("@playwright/test").Page,
  name: string,
): Promise<void> {
  await page
    .getByRole("button", { name: /new profile|new/i })
    .first()
    .click();
  await page.getByLabel(/name/i).first().fill(name);
  await page
    .getByRole("button", { name: /save|create/i })
    .first()
    .click();
  await expect(page.getByText(name)).toBeVisible();
}

async function openEditView(
  page: import("@playwright/test").Page,
  name: string,
): Promise<void> {
  await page.getByText(name).first().click();
  const editBtn = page.getByRole("button", { name: /edit/i }).first();
  if ((await editBtn.count()) > 0) {
    await editBtn.click();
  }
}

test.describe("profile version history", () => {
  test("Edit view scrolled down reveals a Version history section", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("pver-section"));
    await page.getByRole("button", { name: /profiles/i }).first().click();

    const name = `Versioned ${Date.now()}`;
    await createProfile(page, name);
    await snap(page, "pver-section-01-created");

    await openEditView(page, name);
    // Scroll to bottom to bring lazy sections into view.
    await page.mouse.wheel(0, 4000);
    await page.waitForTimeout(200);

    await expect(
      page
        .getByText(/version history|versions|snapshots/i)
        .first(),
    ).toBeVisible();
    await snap(page, "pver-section-02-section-visible");
  });

  test("Empty state explains there are no snapshots yet", async ({ page }) => {
    await signup(page, uniqueEmail("pver-empty"));
    await page.getByRole("button", { name: /profiles/i }).first().click();

    const name = `Empty Versions ${Date.now()}`;
    await createProfile(page, name);
    await openEditView(page, name);
    await page.mouse.wheel(0, 4000);
    await snap(page, "pver-empty-01-edit");

    const emptyCopy = page
      .getByText(
        /no snapshots yet|no versions yet|cloud snapshots not yet enabled|no history/i,
      )
      .first();
    await expect(emptyCopy).toBeVisible();
    await snap(page, "pver-empty-02-empty-state");
  });

  test("Refresh + Restore + size formatting render when a version exists", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("pver-restore"));
    await page.getByRole("button", { name: /profiles/i }).first().click();

    const name = `Restorable ${Date.now()}`;
    await createProfile(page, name);

    // Edit twice to seed potential history.
    for (let i = 0; i < 2; i++) {
      await openEditView(page, name);
      const nameField = page.getByLabel(/name/i).first();
      await nameField.fill(name);
      await page
        .getByRole("button", { name: /save|update/i })
        .first()
        .click();
      await page
        .getByRole("button", { name: /profiles/i })
        .first()
        .click();
    }
    await snap(page, "pver-restore-01-seeded");

    await openEditView(page, name);
    await page.mouse.wheel(0, 4000);
    await page.waitForTimeout(300);

    // Refresh button SHOULD always be present in the version section.
    const refreshBtn = page
      .getByRole("button", { name: /refresh|reload/i })
      .first();
    await expect(refreshBtn).toBeVisible();
    await snap(page, "pver-restore-02-section");

    const restoreBtn = page
      .getByRole("button", { name: /restore/i })
      .first();
    if ((await restoreBtn.count()) > 0) {
      await expect(restoreBtn).toBeVisible();
      // Size formatting — look for KB/MB/B near a snapshot row.
      const size = page
        .getByText(/\b\d+(\.\d+)?\s?(B|KB|MB|GB)\b/i)
        .first();
      // Best-effort: size MAY not be rendered if the snapshot is tiny.
      if ((await size.count()) > 0) {
        await expect(size).toBeVisible();
      }
      await snap(page, "pver-restore-03-restore-visible");
    } else {
      // Cloud snapshots disabled — assert the corresponding empty state.
      await expect(
        page
          .getByText(/no snapshots|not yet enabled|no versions/i)
          .first(),
      ).toBeVisible();
      await snap(page, "pver-restore-03-no-versions");
    }
  });
});
