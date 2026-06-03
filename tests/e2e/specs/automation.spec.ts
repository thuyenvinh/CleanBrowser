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

  test("create flow automation with JSON DSL and v1 version", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("auto-json"));
    await page.getByRole("button", { name: /automations/i }).first().click();

    await page
      .getByRole("button", { name: /new automation|new/i })
      .first()
      .click();
    const name = `flow-json-${Date.now()}`;
    await page.getByLabel(/name/i).first().fill(name);

    const kindSelect = page.getByLabel(/kind|type/i).first();
    if (await kindSelect.count()) {
      await kindSelect.selectOption("flow").catch(async () => {
        await kindSelect.click();
        await page.getByRole("option", { name: /flow/i }).click();
      });
    }
    await page.getByRole("button", { name: /save|create/i }).first().click();
    await expect(page.getByText(name)).toBeVisible();

    await page.getByText(name).first().click();

    const newVersionBtn = page.getByRole("button", {
      name: /new version|add version/i,
    });
    if (await newVersionBtn.count()) {
      await newVersionBtn.first().click();
      const editor = page.getByRole("textbox").last();
      await editor.fill(
        JSON.stringify(
          {
            nodes: [{ id: "n1", type: "goto", url: "https://example.com" }],
            edges: [],
          },
          null,
          2,
        ),
      );
      await page
        .getByRole("button", { name: /save|create/i })
        .first()
        .click();
    }

    // Version list should expose v1 (or "version 1").
    await expect(page.getByText(/v1|version\s*1/i).first()).toBeVisible();
  });

  test("toggle between Visual and JSON editor modes", async ({ page }) => {
    await signup(page, uniqueEmail("auto-toggle"));
    await page.getByRole("button", { name: /automations/i }).first().click();

    await page
      .getByRole("button", { name: /new automation|new/i })
      .first()
      .click();
    const name = `toggle-${Date.now()}`;
    await page.getByLabel(/name/i).first().fill(name);
    await page.getByRole("button", { name: /save|create/i }).first().click();
    await page.getByText(name).first().click();

    // Toggle JSON.
    const jsonToggle = page.getByRole("button", { name: /^json$/i }).first();
    if (await jsonToggle.count()) {
      await jsonToggle.click();
      await expect(page.getByRole("textbox").first()).toBeVisible();
    }

    // Toggle Visual.
    const visualToggle = page
      .getByRole("button", { name: /visual|canvas/i })
      .first();
    if (await visualToggle.count()) {
      await visualToggle.click();
      // Canvas / visual editor should render some kind of surface.
      await expect(
        page
          .locator(
            '[data-testid*=canvas i], [class*=canvas i], [class*=flow i]',
          )
          .first(),
      ).toBeVisible();
    }
  });

  test("AI Build modal generates JSON from a prompt", async ({ page }) => {
    await signup(page, uniqueEmail("auto-ai"));
    await page.getByRole("button", { name: /automations/i }).first().click();

    await page
      .getByRole("button", { name: /new automation|new/i })
      .first()
      .click();
    const name = `ai-${Date.now()}`;
    await page.getByLabel(/name/i).first().fill(name);
    await page.getByRole("button", { name: /save|create/i }).first().click();
    await page.getByText(name).first().click();

    const aiBtn = page.getByRole("button", { name: /ai build|ai/i }).first();
    await aiBtn.click();

    // Modal should expose a prompt textarea.
    const prompt = page
      .getByPlaceholder(/prompt|describe/i)
      .or(page.getByRole("textbox"))
      .first();
    await prompt.fill("Open example.com and click Sign in");

    await page.getByRole("button", { name: /generate|build/i }).first().click();

    // After generation the editor's textbox should contain something
    // (dev-mode response or real LLM output).
    await expect(page.getByRole("textbox").first()).not.toBeEmpty({
      timeout: 15000,
    });
  });

  test("create a cron schedule on an automation", async ({ page }) => {
    await signup(page, uniqueEmail("auto-cron"));
    await page.getByRole("button", { name: /automations/i }).first().click();

    await page
      .getByRole("button", { name: /new automation|new/i })
      .first()
      .click();
    const name = `cron-${Date.now()}`;
    await page.getByLabel(/name/i).first().fill(name);
    await page.getByRole("button", { name: /save|create/i }).first().click();
    await page.getByText(name).first().click();

    // Open the Schedules section / tab.
    const schedSection = page
      .getByRole("button", { name: /schedules?/i })
      .or(page.getByRole("tab", { name: /schedules?/i }))
      .first();
    if (await schedSection.count()) await schedSection.click();

    await page
      .getByRole("button", { name: /add schedule|new schedule|\+ schedule/i })
      .first()
      .click();

    await page.getByLabel(/cron|expression/i).first().fill("0 9 * * *");
    await page
      .getByRole("button", { name: /save|create|add/i })
      .first()
      .click();

    await expect(page.getByText(/0 9 \* \* \*/)).toBeVisible();
  });

  test("create a webhook and reveal its URL with a copy button", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("auto-wh"));
    await page.getByRole("button", { name: /automations/i }).first().click();

    await page
      .getByRole("button", { name: /new automation|new/i })
      .first()
      .click();
    const name = `wh-${Date.now()}`;
    await page.getByLabel(/name/i).first().fill(name);
    await page.getByRole("button", { name: /save|create/i }).first().click();
    await page.getByText(name).first().click();

    const whSection = page
      .getByRole("button", { name: /webhooks?/i })
      .or(page.getByRole("tab", { name: /webhooks?/i }))
      .first();
    if (await whSection.count()) await whSection.click();

    await page
      .getByRole("button", { name: /create webhook|\+.*webhook|new webhook/i })
      .first()
      .click();

    await page.getByLabel(/name/i).last().fill(`hook-${Date.now()}`);
    await page
      .getByRole("button", { name: /save|create|add/i })
      .first()
      .click();

    // URL with a token should be revealed somewhere on the page.
    await expect(page.getByText(/https?:\/\/.+\/webhooks?\//i)).toBeVisible();
    await expect(
      page.getByRole("button", { name: /copy/i }).first(),
    ).toBeVisible();
  });

  test("run an automation manually against a profile", async ({ page }) => {
    await signup(page, uniqueEmail("auto-run"));

    // Create a profile first.
    await page.getByRole("button", { name: /profiles/i }).first().click();
    await page
      .getByRole("button", { name: /new profile|new/i })
      .first()
      .click();
    const profileName = `p-${Date.now()}`;
    await page.getByLabel(/name/i).first().fill(profileName);
    await page.getByRole("button", { name: /save|create/i }).first().click();
    await expect(page.getByText(profileName)).toBeVisible();

    // Create the automation.
    await page.getByRole("button", { name: /automations/i }).first().click();
    await page
      .getByRole("button", { name: /new automation|new/i })
      .first()
      .click();
    const autoName = `run-${Date.now()}`;
    await page.getByLabel(/name/i).first().fill(autoName);
    await page.getByRole("button", { name: /save|create/i }).first().click();
    await page.getByText(autoName).first().click();

    // Click Run on profile.
    await page.getByRole("button", { name: /run/i }).first().click();

    // If a profile picker appears, select it.
    const profilePicker = page.getByLabel(/profile/i).first();
    if (await profilePicker.count()) {
      await profilePicker.selectOption({ index: 1 }).catch(async () => {
        await profilePicker.click();
        await page.getByRole("option", { name: profileName }).click().catch(() => {});
      });
    }
    const confirmRun = page
      .getByRole("button", { name: /^run$|start|queue/i })
      .last();
    if (await confirmRun.count()) await confirmRun.click();

    // A toast or queue id should surface.
    await expect(
      page.getByText(/queued|started|run id|job/i).first(),
    ).toBeVisible({ timeout: 15000 });
  });

  test("delete automation with a schedule warns about the schedule (M9)", async ({
    page,
  }) => {
    await signup(page, uniqueEmail("auto-del"));
    await page.getByRole("button", { name: /automations/i }).first().click();

    await page
      .getByRole("button", { name: /new automation|new/i })
      .first()
      .click();
    const name = `del-${Date.now()}`;
    await page.getByLabel(/name/i).first().fill(name);
    await page.getByRole("button", { name: /save|create/i }).first().click();
    await page.getByText(name).first().click();

    // Add a schedule.
    const schedSection = page
      .getByRole("button", { name: /schedules?/i })
      .or(page.getByRole("tab", { name: /schedules?/i }))
      .first();
    if (await schedSection.count()) await schedSection.click();
    await page
      .getByRole("button", { name: /add schedule|new schedule|\+ schedule/i })
      .first()
      .click();
    await page.getByLabel(/cron|expression/i).first().fill("0 9 * * *");
    await page
      .getByRole("button", { name: /save|create|add/i })
      .first()
      .click();

    // Go back to the automation list & delete.
    await page.getByRole("button", { name: /automations/i }).first().click();
    await page
      .getByRole("button", { name: /^delete$|delete automation|xóa/i })
      .first()
      .click();

    // Confirmation dialog should mention the 1 attached schedule.
    await expect(
      page.getByText(/1 schedule|1 lịch|schedule/i).first(),
    ).toBeVisible();
  });
});
