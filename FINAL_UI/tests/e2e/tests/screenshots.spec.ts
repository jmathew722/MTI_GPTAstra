import { test } from '@playwright/test';
import * as path from 'path';
import { boot, createPart, startDemo, uniq } from '../helpers/app';

// Opt-in: SHOTS=1 npx playwright test screenshots   (writes docs/screenshots/final-*.png)
test.skip(!process.env.SHOTS, 'screenshot capture is opt-in (SHOTS=1)');
const OUT = path.resolve(__dirname, '../../../docs/screenshots');
const VPS = [['1672x941', 1672, 941], ['1440x900', 1440, 900], ['1024x768', 1024, 768], ['390x844', 390, 844]] as const;

test('final screenshots', async ({ page }) => {
  await createPart(page, uniq('Pump-Bracket-'));
  for (const [n, w, h] of VPS) {
    await page.setViewportSize({ width: w, height: h });
    await page.evaluate(() => { location.hash = '#/home'; });
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(OUT, `final-home-${n}.png`) });
    await page.evaluate(() => { location.hash = '#/workspace'; });
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(OUT, `final-workspace-${n}.png`) });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.evaluate(() => { location.hash = '#/home'; });
  await startDemo(page);
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(OUT, 'final-workspace-demo-1440x900.png') });
});
