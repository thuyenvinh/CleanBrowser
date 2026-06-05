import type { Page } from "@playwright/test";
import * as path from "path";
import * as fs from "fs";

/**
 * Helper để chụp screenshot có timestamp + tên test, lưu vào thư mục tổ chức
 * theo spec. Tự tạo folder nếu chưa có.
 */
export async function snap(
  page: Page,
  name: string,
  options: { fullPage?: boolean } = { fullPage: true },
): Promise<string> {
  const dir = path.join("screenshots", new Date().toISOString().slice(0, 10));
  fs.mkdirSync(dir, { recursive: true });
  const timestamp = Date.now();
  const safeName = name.replace(/[^a-z0-9-_]/gi, "_");
  const filename = `${safeName}-${timestamp}.png`;
  const fullPath = path.join(dir, filename);
  await page.screenshot({ path: fullPath, fullPage: options.fullPage });
  return fullPath;
}

/**
 * Chụp một loạt screenshot tại các milestone của 1 flow.
 * Trả về list các path đã chụp để báo cáo.
 */
export async function snapFlow(
  page: Page,
  flowName: string,
  steps: { name: string; action: () => Promise<void> }[],
): Promise<string[]> {
  const paths: string[] = [];
  paths.push(await snap(page, `${flowName}-00-start`));
  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];
    await step.action();
    paths.push(
      await snap(
        page,
        `${flowName}-${String(i + 1).padStart(2, "0")}-${step.name}`,
      ),
    );
  }
  return paths;
}

/**
 * Log một annotation vào trace + console với metadata test info.
 * Hữu ích khi review trace HTML report.
 */
export async function annotate(
  page: Page,
  label: string,
  payload?: object,
): Promise<void> {
  await page.evaluate(
    ({ label, payload }) => {
      // eslint-disable-next-line no-console
      console.log(`[E2E_ANNOTATE] ${label}`, payload || "");
    },
    { label, payload },
  );
}
