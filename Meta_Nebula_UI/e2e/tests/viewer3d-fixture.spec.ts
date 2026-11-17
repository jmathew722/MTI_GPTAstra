import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import { createPart, uniq } from '../helpers/app';
import { bracketStl } from '../helpers/fixtureStl';

// Opt-in: CAL=1. Puts a hand-made synthetic mesh (named prevalidation.stl so the app labels it Pre-validated, never Generated)
// into a throwaway part to exercise the 3D viewer toolbar, triad and metallic lighting. Global teardown deletes the session folder.
test.skip(!process.env.CAL, 'viewer fixture capture is opt-in (CAL=1)');
const OUT = process.env.CAL_OUT || path.resolve(__dirname, '../../docs/screenshots');
const PARTS = path.resolve(__dirname, '../../pipeline_app/webapp/parts');

test('3D viewer with a synthetic fixture mesh', async ({ page }) => {
  const name = uniq('Fixture-');
  await page.setViewportSize({ width: 1672, height: 941 });
  await createPart(page, name);
  const session: string = await page.evaluate(() => (window as any).McA.store.get().session.id);
  const dir = path.join(PARTS, session, name, 'output');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'prevalidation.stl'), bracketStl());
  await page.reload();
  await page.waitForFunction(() => !!(window as any).McA && (window as any).McA.store.get().session.id);
  await page.waitForTimeout(800);
  await page.evaluate(([s, n]) => { (window as any).McA.openPart(s, n); }, [session, name]);
  await expect(page.locator('#stl-bar [data-act="fit"]')).toBeEnabled({ timeout: 15000 });
  await page.locator('.toast-x').evaluateAll((els: any[]) => els.forEach((e) => e.click()));
  await page.waitForTimeout(1200);
  await page.screenshot({ path: path.join(OUT, 'calibrated-3d-fixture-1672x941.png') });
  // toolbar controls really act
  const tri = page.locator('#stl-triad');
  await expect(tri).toBeVisible();
  await page.locator('#stl-bar [data-act="pan"]').click();
  await expect(page.locator('#stl-bar [data-act="pan"]')).toHaveAttribute('aria-pressed', 'true');
  await page.locator('#stl-bar [data-act="wire"]').click();
  await expect(page.locator('#stl-bar [data-act="wire"]')).toHaveAttribute('aria-pressed', 'true');
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(OUT, 'calibrated-3d-fixture-wire-1672x941.png') });
  await page.locator('#stl-bar [data-act="zoom-in"]').click();
  await page.locator('#stl-bar [data-act="fit"]').click();
  await page.locator('#stl-bar [data-act="reset"]').click();
});
