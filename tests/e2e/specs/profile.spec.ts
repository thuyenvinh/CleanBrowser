import { test, expect } from "@playwright/test";
import { signup, uniqueEmail } from "../helpers/auth-helper";

test.describe("profiles", () => {
  test("create a profile from the empty state", async ({ page }) => {
    await signup(page, uniqueEmail("profile-create"));

    // Make sure we're on the Profiles tab.
    await page.getByRole("button", { name: /profiles/i }).first().click();

    // Empty state copy varies — accept either "no profiles" hint or just the
    // New button being present.
    const newBtn = page.getByRole("button", { name: /new profile|new/i }).first();
    await newBtn.click();

    const name = `My Profile ${Date.now()}`;
    await page.getByLabel(/name/i).first().fill(name);
    await page.getByRole("button", { name: /save|create/i }).first().click();

    await expect(page.getByText(name)).toBeVisible();
  });

  test("rename a profile and see the update reflected in the list", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("profile-edit"));
    await page.getByRole("button", { name: /profiles/i }).first().click();

    const original = `Original ${Date.now()}`;
    await page.getByRole("button", { name: /new profile|new/i }).first().click();
    await page.getByLabel(/name/i).first().fill(original);
    await page.getByRole("button", { name: /save|create/i }).first().click();
    await expect(page.getByText(original)).toBeVisible();

    // Open the profile and edit it.
    await page.getByText(original).first().click();
    await page.getByRole("button", { name: /edit/i }).first().click();
    const renamed = `${original} v2`;
    const nameField = page.getByLabel(/name/i).first();
    await nameField.fill(renamed);
    await page.getByRole("button", { name: /save|update/i }).first().click();

    await expect(page.getByText(renamed)).toBeVisible();
  });

  test("delete a profile removes it from the list", async ({ page }) => {
    await signup(page, uniqueEmail("profile-delete"));
    await page.getByRole("button", { name: /profiles/i }).first().click();

    const name = `Deletable ${Date.now()}`;
    await page.getByRole("button", { name: /new profile|new/i }).first().click();
    await page.getByLabel(/name/i).first().fill(name);
    await page.getByRole("button", { name: /save|create/i }).first().click();
    await expect(page.getByText(name)).toBeVisible();

    await page.getByText(name).first().click();
    // The confirm-and-delete varies; auto-accept any browser confirm.
    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: /delete|remove/i }).first().click();

    await expect(page.getByText(name)).toHaveCount(0);
  });
});
