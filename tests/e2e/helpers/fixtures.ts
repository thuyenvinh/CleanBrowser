import { test as base, expect } from "@playwright/test";
import { snap } from "./screenshot-helper";

/**
 * Custom fixture: tự động chụp screenshot khi test fail,
 * lưu trace luôn, và clean up cookies giữa các test.
 */
export const test = base.extend({
  // Override page để tự annotation
  page: async ({ page }, use, testInfo) => {
    // Inject E2E marker
    await page.addInitScript(() => {
      (window as unknown as { __E2E__: boolean }).__E2E__ = true;
    });

    await use(page);

    // After test: nếu fail, chụp final state
    if (testInfo.status !== "passed") {
      try {
        await snap(page, `FAILED-${testInfo.title}`);
      } catch {
        // page đã đóng — bỏ qua
      }
    }
  },
});

export { expect };
