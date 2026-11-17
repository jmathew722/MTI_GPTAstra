import { test, expect } from '@playwright/test';
import { boot, createPart, uniq } from '../helpers/app';

test('19 stale responses: a slow outputs reply for the previous part never overwrites the current selection', async ({ page }) => {
  const a = uniq('e2e-sa-'), b = uniq('e2e-sb-');
  await createPart(page, a);
  await createPart(page, b);
  await boot(page, '#/workspace');
  // Delay the outputs reply of part A by 1.5 s, then select B right away.
  await page.route(new RegExp(`/api/parts/[^/]+/${a}/outputs`), async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  const sess = await page.evaluate(() => (window as any).McA.store.get().session.id);
  await page.evaluate(([s, p]) => (window as any).McA.openPart(s, p), [sess, a]);
  await page.evaluate(([s, p]) => (window as any).McA.openPart(s, p), [sess, b]);
  await page.waitForTimeout(2200);
  const sel = await page.evaluate(() => (window as any).McA.store.get().parts.selected.part);
  const ctx = await page.evaluate(() => JSON.stringify((window as any).McA.store.get().outputs.ctx || {}));
  expect(sel).toBe(b);
  expect(ctx).not.toContain(a);
  await expect(page.locator('#ws-part')).toHaveText(b);
});
