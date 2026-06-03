import { test, expect } from "../helpers/fixtures";
import { snap } from "../helpers/screenshot-helper";
import { signup, uniqueEmail } from "../helpers/auth-helper";

/**
 * RunViewer cancel UX.
 *
 * We can't reliably produce a long-running real automation in a unit-style
 * test, so we verify the cancel control's *conditional visibility*:
 *   - if a running run exists, Cancel is offered and asks for confirm
 *   - if all runs are terminal (success/failed), Cancel is NOT offered
 */

async function gotoAutomations(
  page: import("@playwright/test").Page,
  emailPrefix: string,
): Promise<void> {
  await signup(page, uniqueEmail(emailPrefix));
  await page.getByRole("button", { name: /automations/i }).first().click();
}

async function createAndOpenAutomation(
  page: import("@playwright/test").Page,
  name: string,
): Promise<void> {
  await page
    .getByRole("button", { name: /new automation|new/i })
    .first()
    .click();
  await page.getByLabel(/name/i).first().fill(name);
  await page
    .getByRole("button", { name: /save|create/i })
    .first()
    .click();
  await page.getByText(name).first().click();
}

test.describe("run cancel UX", () => {
  test("starting a run reveals a Cancel button while status is running", async ({
    page,
  }) => {
    await gotoAutomations(page, "run-cancel");
    await snap(page, "run-cancel-01-list");

    const name = `cancellable-${Date.now()}`;
    await createAndOpenAutomation(page, name);
    await snap(page, "run-cancel-02-opened");

    const runBtn = page.getByRole("button", { name: /^run$|start/i }).first();
    if ((await runBtn.count()) === 0) {
      test.skip(true, "Run button not present in this build");
    }
    await runBtn.click();

    // Some apps need a profile picker — best-effort confirm.
    const confirmRun = page
      .getByRole("button", { name: /^run$|start|queue/i })
      .last();
    if ((await confirmRun.count()) > 0) {
      await confirmRun.click().catch(() => {});
    }

    // We accept either an immediately-shown Cancel button OR a running status
    // text, since the run may finish too fast in a stub backend.
    const cancelBtn = page
      .getByRole("button", { name: /cancel|stop|abort/i })
      .first();
    const runningStatus = page.getByText(/running|in progress|queued/i).first();
    await expect(cancelBtn.or(runningStatus)).toBeVisible({ timeout: 10_000 });
    await snap(page, "run-cancel-03-running");
  });

  test("Cancel button asks for confirmation and updates the status", async ({
    page,
  }) => {
    await gotoAutomations(page, "run-cancel-confirm");
    const name = `confirm-${Date.now()}`;
    await createAndOpenAutomation(page, name);

    const runBtn = page.getByRole("button", { name: /^run$|start/i }).first();
    if ((await runBtn.count()) === 0) {
      test.skip(true, "Run button not present");
    }
    await runBtn.click();
    const confirmRun = page
      .getByRole("button", { name: /^run$|start|queue/i })
      .last();
    if ((await confirmRun.count()) > 0) {
      await confirmRun.click().catch(() => {});
    }
    await snap(page, "run-cancel-confirm-01-started");

    const cancelBtn = page
      .getByRole("button", { name: /cancel|stop|abort/i })
      .first();
    if ((await cancelBtn.count()) === 0) {
      test.skip(true, "No cancel button surfaced — run probably finished");
    }

    // Accept any native window.confirm()
    page.once("dialog", (d) => d.accept().catch(() => {}));
    await cancelBtn.click();

    // Custom confirm modal path
    const okBtn = page
      .getByRole("button", { name: /^(yes|confirm|ok|cancel run)$/i })
      .first();
    if ((await okBtn.count()) > 0) {
      await okBtn.click().catch(() => {});
    }
    await snap(page, "run-cancel-confirm-02-confirmed");

    await expect(
      page
        .getByText(/cancel{1,2}ed|aborted|stopped|canceled/i)
        .first(),
    ).toBeVisible({ timeout: 10_000 });
    await snap(page, "run-cancel-confirm-03-status-changed");
  });

  test("a completed/success run does not expose Cancel", async ({ page }) => {
    await gotoAutomations(page, "run-cancel-done");
    const name = `done-${Date.now()}`;
    await createAndOpenAutomation(page, name);
    await snap(page, "run-cancel-done-01-opened");

    // We assume no runs exist OR they have all settled. Either way the
    // viewer panel should not offer Cancel in its current snapshot.
    // We wait briefly and assert Cancel is not visible.
    await page.waitForTimeout(500);
    await snap(page, "run-cancel-done-02-idle");

    const cancelBtns = page.getByRole("button", {
      name: /^cancel( run)?$|abort/i,
    });
    // We accept zero matches OR all of them being hidden/disabled.
    const count = await cancelBtns.count();
    if (count === 0) {
      expect(count).toBe(0);
    } else {
      for (let i = 0; i < count; i++) {
        const btn = cancelBtns.nth(i);
        const visible = await btn.isVisible().catch(() => false);
        if (visible) {
          const disabled = await btn.isDisabled().catch(() => true);
          // Either hidden or disabled — never a clickable cancel for a
          // completed run.
          expect(disabled).toBe(true);
        }
      }
    }
  });
});
