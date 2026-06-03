import { test, expect } from '@playwright/test';
import { signup, uniqueEmail } from '../helpers/auth-helper';

test.describe('Workspace management', () => {
  test('Default workspace created on signup', async ({ page }) => {
    const email = uniqueEmail('ws-default');
    await signup(page, email);
    // WorkspaceSelector hiển thị default workspace
    await expect(
      page.locator(
        'button:has-text("Default Workspace"), [data-testid=workspace-selector]',
      ),
    ).toBeVisible();
    await page.screenshot({
      path: 'screenshots/workspace-default.png',
      fullPage: true,
    });
  });

  test('Open workspace settings dialog', async ({ page }) => {
    await signup(page, uniqueEmail('ws-settings'));
    // Click gear icon in WorkspaceSelector
    await page
      .locator('[aria-label*=settings i], button[title*=settings i]')
      .first()
      .click();
    await expect(
      page.getByText(/general|members|danger zone/i),
    ).toBeVisible();
    await page.screenshot({
      path: 'screenshots/workspace-settings-open.png',
      fullPage: true,
    });
  });

  test('Rename workspace in General tab', async ({ page }) => {
    await signup(page, uniqueEmail('ws-rename'));
    await page.locator('[aria-label*=settings i]').first().click();
    await page.getByRole('button', { name: /general/i }).click();
    await page.getByLabel(/name/i).fill('My Team');
    await page.getByRole('button', { name: /save/i }).click();
    await expect(page.getByText('My Team').first()).toBeVisible();
    await page.screenshot({
      path: 'screenshots/workspace-renamed.png',
      fullPage: true,
    });
  });

  test('Members tab shows current owner', async ({ page }) => {
    const email = uniqueEmail('ws-members');
    await signup(page, email);
    await page.locator('[aria-label*=settings i]').first().click();
    await page.getByRole('button', { name: /members/i }).click();
    await expect(page.getByText(email)).toBeVisible();
    await expect(page.getByText(/owner/i)).toBeVisible();
    await page.screenshot({
      path: 'screenshots/workspace-members-table.png',
      fullPage: true,
    });
  });

  test('Invite member form visible (verified email gate)', async ({ page }) => {
    await signup(page, uniqueEmail('ws-invite'));
    await page.locator('[aria-label*=settings i]').first().click();
    await page.getByRole('button', { name: /members/i }).click();
    // Form invite có email + role select + button
    await expect(page.getByPlaceholder(/email/i)).toBeVisible();
    await expect(page.locator('select')).toBeVisible();
    await page.screenshot({
      path: 'screenshots/workspace-invite-form.png',
      fullPage: true,
    });
  });

  test('Danger zone delete confirmation required', async ({ page }) => {
    await signup(page, uniqueEmail('ws-delete'));
    await page.locator('[aria-label*=settings i]').first().click();
    await page.getByRole('button', { name: /danger/i }).click();
    await expect(page.getByText(/cannot.*undone|permanently/i)).toBeVisible();
    await expect(
      page.getByRole('button', { name: /delete.*workspace/i }),
    ).toBeDisabled();
    await page.screenshot({
      path: 'screenshots/workspace-danger-zone.png',
      fullPage: true,
    });
  });
});
