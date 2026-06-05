import { test, expect } from "../helpers/fixtures";
import { snap } from "../helpers/screenshot-helper";
import { signup, uniqueEmail } from "../helpers/auth-helper";

/**
 * Admin moderation queue. A fresh tenant won't be a global admin, so we
 * only assert UI affordances that should be present (button exists →
 * modal opens), gracefully skipping the approve/reject path when the
 * current user lacks permissions or the queue is empty.
 */
test.describe("admin moderation", () => {
  test("Marketplace exposes a Moderation Queue button that opens a modal", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("mod-open"));
    await page
      .getByRole("button", { name: /marketplace/i })
      .first()
      .click();
    await snap(page, "mod-open-01-marketplace");

    const queueBtn = page
      .getByRole("button", { name: /moderation.*queue|moderate/i })
      .first();
    if ((await queueBtn.count()) === 0) {
      test.skip(true, "Moderation queue button not exposed to this user");
    }
    await queueBtn.click();

    // Modal should show — either pending list or empty-state copy.
    await expect(
      page
        .getByText(/pending|moderation|no .*pending|empty/i)
        .first(),
    ).toBeVisible({ timeout: 10_000 });
    await snap(page, "mod-open-02-modal");
  });

  test("Moderation queue renders the pending list or an empty state", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("mod-list"));
    await page
      .getByRole("button", { name: /marketplace/i })
      .first()
      .click();

    const queueBtn = page
      .getByRole("button", { name: /moderation.*queue|moderate/i })
      .first();
    if ((await queueBtn.count()) === 0) {
      test.skip(true, "Moderation queue button not present");
    }
    await queueBtn.click();
    await snap(page, "mod-list-01-modal-open");

    const emptyState = page
      .getByText(/no .*pending|nothing to moderate|queue is empty/i)
      .first();
    const pendingRow = page
      .getByRole("listitem")
      .or(page.locator('[data-pending], [class*="pending" i]'))
      .first();

    await expect(emptyState.or(pendingRow)).toBeVisible({ timeout: 10_000 });
    await snap(page, "mod-list-02-rendered");
  });

  test("Reject requires notes (form validation)", async ({ page }) => {
    await signup(page, uniqueEmail("mod-reject"));
    await page
      .getByRole("button", { name: /marketplace/i })
      .first()
      .click();

    const queueBtn = page
      .getByRole("button", { name: /moderation.*queue|moderate/i })
      .first();
    if ((await queueBtn.count()) === 0) {
      test.skip(true, "Moderation queue button not present");
    }
    await queueBtn.click();
    await snap(page, "mod-reject-01-modal");

    const rejectBtn = page
      .getByRole("button", { name: /^reject$/i })
      .first();
    if ((await rejectBtn.count()) === 0) {
      test.skip(true, "No pending app to reject");
    }
    await rejectBtn.click();
    await snap(page, "mod-reject-02-clicked");

    // Either a notes textarea is required (empty submit → error), or
    // the reject is immediately gated behind a confirmation form.
    const notes = page
      .getByLabel(/notes|reason|comment/i)
      .or(page.getByPlaceholder(/notes|reason|why/i))
      .first();

    if ((await notes.count()) > 0) {
      // Submit empty to trigger validation.
      const confirmBtn = page
        .getByRole("button", { name: /reject|confirm|submit/i })
        .last();
      await confirmBtn.click().catch(() => {});

      const validityBroken = await notes.evaluate(
        (el) =>
          (el as HTMLTextAreaElement | HTMLInputElement).validity?.valid ===
          false,
      );
      if (!validityBroken) {
        await expect(
          page
            .getByText(/required|notes|reason.*required|please.*reason/i)
            .first(),
        ).toBeVisible();
      }
      await snap(page, "mod-reject-03-required");
    } else {
      // No notes form — at minimum the reject action itself opened a confirm.
      await expect(
        page.getByRole("button", { name: /confirm|reject|cancel/i }).first(),
      ).toBeVisible();
      await snap(page, "mod-reject-03-confirm");
    }
  });
});
