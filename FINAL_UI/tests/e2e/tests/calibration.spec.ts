import { test, expect } from '@playwright/test';
import * as path from 'path';
import { boot, startDemo, uniq } from '../helpers/app';

// Opt-in: CAL=1 npx playwright test calibration  (writes docs/screenshots/calibrated-*.png)
test.skip(!process.env.CAL, 'calibration capture is opt-in (CAL=1)');
const OUT = process.env.CAL_OUT || path.resolve(__dirname, '../../../docs/screenshots');
const ALL = [[1672, 941], [1920, 1080], [1440, 900], [1280, 800], [1024, 768], [768, 1024], [390, 844]] as const;
const ONLY = (process.env.CAL_ONLY || '').split(',').filter(Boolean);
const VPS = ALL.filter(([w]) => !ONLY.length || ONLY.includes(String(w)));

/** Draws a synthetic engineering-looking drawing (outline, dimensions, title block) on a canvas and returns PNG bytes. */
async function drawing(page: any): Promise<Buffer> {
  const b64: string = await page.evaluate(() => {
    const c = document.createElement('canvas'); c.width = 1200; c.height = 900;
    const g = c.getContext('2d')!; g.fillStyle = '#fff'; g.fillRect(0, 0, 1200, 900);
    g.strokeStyle = '#111'; g.fillStyle = '#111'; g.lineWidth = 2; g.font = '20px sans-serif';
    g.strokeRect(20, 20, 1160, 860);
    g.strokeRect(860, 40, 300, 120); g.font = '18px sans-serif';
    ['PART: SYNTH BRACKET', 'DWG NO: SB-001', 'REV: A', 'UNIT: mm'].forEach((t, i) => g.fillText(t, 872, 68 + i * 28));
    const dim = (x1: number, y1: number, x2: number, y2: number, t: string) => {
      g.lineWidth = 1.2; g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke();
      g.font = '18px sans-serif'; g.fillText(t, (x1 + x2) / 2 - 24, (y1 + y2) / 2 - 6);
    };
    g.lineWidth = 3; g.beginPath(); g.roundRect(240, 300, 560, 180, 70); g.stroke();
    g.beginPath(); g.arc(520, 390, 70, 0, 7); g.stroke();
    g.beginPath(); g.arc(300, 390, 22, 0, 7); g.stroke(); g.beginPath(); g.arc(740, 390, 22, 0, 7); g.stroke();
    dim(240, 250, 800, 250, '120.00'); dim(200, 300, 200, 480, '50.00');
    g.lineWidth = 3; g.strokeRect(240, 620, 560, 60); g.strokeRect(440, 540, 160, 80);
    dim(240, 740, 800, 740, '120.00'); dim(850, 540, 850, 680, '40.00');
    return c.toDataURL('image/png').split(',')[1];
  });
  return Buffer.from(b64, 'base64');
}

test('calibration shots', async ({ page }) => {
  test.setTimeout(Number(process.env.CAL_TIMEOUT || 240_000));
  await page.setViewportSize({ width: 1672, height: 941 });
  const name = uniq('Pump-Bracket-');
  await boot(page, '#/home');
  const png = await drawing(page);
  // idle (no part)
  await page.evaluate(() => { location.hash = '#/workspace'; });
  await page.waitForTimeout(800);
  for (const [w, h] of VPS) { await page.setViewportSize({ width: w, height: h }); await page.waitForTimeout(500); await page.screenshot({ path: path.join(OUT, `calibrated-idle-${w}x${h}.png`) }); }
  // saved part
  await page.setViewportSize({ width: 1672, height: 941 });
  await boot(page, '#/home');
  await page.evaluate(() => { location.hash = '#/home'; });
  await page.setInputFiles('#home-file', [{ name: 'Drawing_PumpBracket.png', mimeType: 'image/png', buffer: png }, { name: 'Drawing_PumpBracket_top.png', mimeType: 'image/png', buffer: png }]);
  await expect(page.locator('#home-create')).toHaveAttribute('aria-disabled', 'false');
  await page.click('#home-create');
  await expect(page).toHaveURL(/#\/workspace/);
  await page.locator('#orient-gallery select.oselect').nth(0).selectOption('front');
  await page.locator('#orient-gallery select.oselect').nth(1).selectOption('top');
  await page.fill('#part-name', name);
  await expect(page.locator('#save-part-btn')).toBeEnabled();
  await page.click('#save-part-btn');
  await expect(page.locator('#ws-part')).toHaveText(name);
  await page.locator('.toast-x').evaluateAll((els: any[]) => els.forEach((e) => e.click()));
  await page.waitForTimeout(1500);
  for (const [w, h] of VPS) { await page.setViewportSize({ width: w, height: h }); await page.waitForTimeout(600); await page.screenshot({ path: path.join(OUT, `calibrated-part-${w}x${h}.png`) }); }
  // demo
  await page.setViewportSize({ width: 1672, height: 941 });
  await page.evaluate(() => { location.hash = '#/home'; });
  await startDemo(page);
  await page.waitForTimeout(2500);
  await page.locator('.toast-x').evaluateAll((els: any[]) => els.forEach((e) => e.click()));
  await page.waitForTimeout(1000);
  for (const [w, h] of VPS) { await page.setViewportSize({ width: w, height: h }); await page.waitForTimeout(600); await page.screenshot({ path: path.join(OUT, `calibrated-demo-${w}x${h}.png`) }); }
});
