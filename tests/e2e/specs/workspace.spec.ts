import { test, expect } from '@playwright/test';
import { signup, uniqueEmail } from '../helpers/auth-helper';

test.describe('Workspace management', () => {
  test('Default workspace created on signup', async ({ page }) => {
    const email = uniqueEmail('ws-default');
    await signup(page, email);
    // The signup helper creates a workspace called "Default" (db_auth.signup).
    // WorkspaceSelector renders a button with title="Switch workspace" whose
    // accessible name is the workspace's display name, plus a gear button with
    // aria-label="Workspace settings" next to it.
    await expect(
      page.getByRole('button', { name: /workspace settings/i }),
    ).toBeVisible();
    await expect(page.locator('button[title*="Switch workspace" i]')).toBeVisible();
    // The switcher button text contains the workspace name.
    await expect(
      page.locator('button[title*="Switch workspace" i]'),
    ).toContainText('Default');
    await page.screenshot({
      path: 'screenshots/workspace-default.png',
      fullPage: true,
    });
  });

  test('Open workspace settings dialog', async ({ page }) => {
    await signup(page, uniqueEmail('ws-settings'));
    await page.getByRole('button', { name: /workspace settings/i }).click();
    await expect(
      page.getByRole('button', { name: /^general$/i }),
    ).toBeVisible();
    await page.screenshot({
      path: 'screenshots/workspace-settings-open.png',
      fullPage: true,
    });
  });

  test('Rename workspace in General tab', async ({ page }) => {
    await signup(page, uniqueEmail('ws-rename'));
    await page.getByRole('button', { name: /workspace settings/i }).click();
    await page.getByRole('button', { name: /^general$/i }).click();
    // The General form's name input is pre-filled with the current workspace
    // name ("Default"). Locate by current value to avoid colliding with the
    // sidebar's "Search profiles..." input.
    const nameInput = page.locator('form input[type="text"]').first();
    await nameInput.fill('My Team');
    await page.getByRole('button', { name: /save changes/i }).click();
    // Rename triggers a full page reload (see WorkspaceSettingsPage.onChanged),
    // after which the switcher button shows the new name.
    await expect(
      page.locator('button[title*="Switch workspace" i]'),
    ).toContainText('My Team', { timeout: 15_000 });
    await page.screenshot({
      path: 'screenshots/workspace-renamed.png',
      fullPage: true,
    });
  });

  test('Members tab shows current owner', async ({ page }) => {
    const email = uniqueEmail('ws-members');
    await signup(page, email);
    await page.getByRole('button', { name: /workspace settings/i }).click();
    await page.getByRole('button', { name: /^members$/i }).click();
    // Role is rendered as a <select> whose value is "owner". The visible
    // "owner" text inside the table is the selected option of that select.
    await expect(page.getByText(email).first()).toBeVisible();
    const roleSelect = page.locator('table select').first();
    await expect(roleSelect).toBeVisible();
    await expect(roleSelect).toHaveValue('owner');
    await page.screenshot({
      path: 'screenshots/workspace-members-table.png',
      fullPage: true,
    });
  });

  test('Invite member form visible (verified email gate)', async ({ page }) => {
    await signup(page, uniqueEmail('ws-invite'));
    await page.getByRole('button', { name: /workspace settings/i }).click();
    await page.getByRole('button', { name: /^members$/i }).click();
    // The invite form input uses placeholder="user@example.com".
    await expect(
      page.getByPlaceholder(/user@example|email/i).first(),
    ).toBeVisible();
    await expect(page.locator('select').first()).toBeVisible();
    await page.screenshot({
      path: 'screenshots/workspace-invite-form.png',
      fullPage: true,
    });
  });

  test('Danger zone delete confirmation required', async ({ page }) => {
    await signup(page, uniqueEmail('ws-delete'));
    await page.getByRole('button', { name: /workspace settings/i }).click();
    await page.getByRole('button', { name: /danger/i }).click();
    // The warning block contains both "Delete this workspace" and
    // "Permanently delete <name>" — use .first() to avoid strict-mode collision.
    await expect(
      page.getByText(/cannot.*undone|permanently|delete this workspace/i).first(),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: /delete.*workspace/i }).first(),
    ).toBeVisible();
    await page.screenshot({
      path: 'screenshots/workspace-danger-zone.png',
      fullPage: true,
    });
  });
});
