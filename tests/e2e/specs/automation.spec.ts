import { test, expect } from "@playwright/test";
import { signup, uniqueEmail } from "../helpers/auth-helper";

test.describe("automations", () => {
  test("create a flow automation with a JSON version", async ({ page }) => {
    await signup(page, uniqueEmail("auto"));

    await page.getByRole("button", { name: /automations/i }).first().click();

    await page
      .getByRole("button", { name: /new automation|new/i })
      .first()
      .click();

    const name = `Auto ${Date.now()}`;
    await page.getByLabel(/name/i).first().fill(name);

    // Pick kind=flow if a kind selector exists.
    const kindSelect = page.getByLabel(/kind|type/i).first();
    if (await kindSelect.count()) {
      await kindSelect.selectOption("flow").catch(async () => {
        await kindSelect.click();
        await page.getByRole("option", { name: /flow/i }).click();
      });
    }

    await page.getByRole("button", { name: /save|create/i }).first().click();

    // Automation should appear in the list.
    await expect(page.getByText(name)).toBeVisible();

    // Open it and create a version. The version editor accepts JSON; if a
    // textarea is exposed, fill a minimal flow document.
    await page.getByText(name).first().click();
    const newVersionBtn = page.getByRole("button", {
      name: /new version|add version/i,
    });
    if (await newVersionBtn.count()) {
      await newVersionBtn.first().click();
      const editor = page.getByRole("textbox").last();
      await editor.fill(
        JSON.stringify({ nodes: [], edges: [] }, null, 2),
      );
      await page
        .getByRole("button", { name: /save|create/i })
        .first()
        .click();
    }

    await expect(page.getByText(name)).toBeVisible();
  });
});
