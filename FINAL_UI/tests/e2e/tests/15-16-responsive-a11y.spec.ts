import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import * as fs from 'fs';
import * as path from 'path';
import { boot, createPart, startDemo, uniq, watchConsole } from '../helpers/app';

const OUT = path.resolve(__dirname, '../test-results/screens');
const VIEWPORTS = [
  { name: '1920x1080', w: 1920, h: 1080 },
  { name: '1440x900', w: 1440, h: 900 },
  { name: '1366x768', w: 1366, h: 768 },
  { name: '1024x768', w: 1024, h: 768 },
  { name: '390x844', w: 390, h: 844 },
];

test.describe('Responsive and accessibility', () => {
  test('15 Responsive: inspector placement, tabs under 1100, no horizontal overflow, screenshots', async ({ page }) => {
    const bad = watchConsole(page);
    fs.mkdirSync(OUT, { recursive: true });
    await createPart(page, uniq('e2e-resp-'));
    for (const v of VIEWPORTS) {
      await page.setViewportSize({ width: v.w, height: v.h });
      await page.evaluate(() => { location.hash = '#/workspace'; });
      await page.waitForTimeout(250);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `horizontal overflow at ${v.name}`).toBeLessThanOrEqual(0);
      if (v.w >= 1250) {  // calibration pass: inspector docks from 1250 px (EXACT_DESIGN responsive rules); it was 1440
        await expect(page.locator('#inspector')).toBeVisible();
        expect(await page.evaluate(() => document.getElementById('inspector')!.parentElement!.id)).toBe('ws-main');
      } else {
        // Below 1250 the inspector's DOM lives in the drawer Tools mode.
        expect(await page.evaluate(() => document.getElementById('inspector')!.parentElement!.id)).toBe('dr-tools');
        await expect(page.locator('#dr-mode-tools')).toBeVisible();
      }
      if (v.w < 1100) {
        await expect(page.locator('#canvas .canvas-tabs')).toBeVisible();
        await expect(page.locator('#splitter')).toBeHidden();
      } else {
        await expect(page.locator('#canvas .canvas-tabs')).toBeHidden();
        await expect(page.locator('#splitter')).toBeVisible();
      }
      await page.screenshot({ path: path.join(OUT, `workspace-${v.name}.png`) });
      await page.evaluate(() => { location.hash = '#/home'; });
      await page.waitForTimeout(150);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
      await page.screenshot({ path: path.join(OUT, `home-${v.name}.png`) });
    }
    expect(bad, bad.join('\n')).toEqual([]);
  });

  test('16 Accessibility: axe finds no serious or critical violations on Home, Workspace, Results, Projects, Recent, Settings, Help', async ({ page }) => {
    await createPart(page, uniq('e2e-axe-'));
    await page.evaluate(() => { location.hash = '#/home'; });
    await startDemo(page).catch(async () => {
      await page.click('#home-demo');
      await page.locator('#dialog-root button[data-action="run"]').click();
    });
    await expect(page.locator('#trk-pct')).toHaveAttribute('aria-valuenow', '100', { timeout: 20_000 });
    const report: Record<string, string[]> = {};
    for (const p of ['home', 'workspace', 'results', 'projects', 'recent', 'settings', 'help']) {
      await page.evaluate((h) => { location.hash = h; }, `#/${p}`);
      await expect(page.locator(`#page-${p}`)).toBeVisible();
      await page.waitForTimeout(400);
      const res = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
      report[p] = res.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
        .map((v) => `${v.id} (${v.impact}): ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`);
    }
    const all = Object.entries(report).filter(([, v]) => v.length);
    expect(all, JSON.stringify(report, null, 2)).toEqual([]);
  });
});
