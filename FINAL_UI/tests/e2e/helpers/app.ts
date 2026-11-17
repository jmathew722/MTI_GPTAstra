import { expect, Page } from '@playwright/test';
import { pngFile } from './fixtures';

export const uniq = (p: string) => `${p}${Date.now().toString(36)}${Math.floor(Math.random() * 1e3)}`;

/** Collects console errors/warnings and uncaught exceptions. Headless-WebGL driver noise is ignored. */
export function watchConsole(page: Page) {
  const bad: string[] = [];
  page.on('console', (m) => {
    if (m.type() !== 'error' && m.type() !== 'warning') return;
    const t = m.text();
    if (/GL Driver Message|ReadPixels|GPU stall|swiftshader|WebGL/i.test(t)) return;
    bad.push(`${m.type()}: ${t}`);
  });
  page.on('pageerror', (e) => bad.push('pageerror: ' + e.message));
  return bad;
}

export async function boot(page: Page, hash = '#/home') {
  await page.goto('/' + hash);
  await expect(page.locator('#sidebar')).toBeVisible();
  await page.waitForFunction(() => !!(window as any).McA && (window as any).McA.store.get().session.id);
}

export async function status(page: Page): Promise<{ live: boolean; samples: string[]; model?: string }> {
  return page.evaluate(() => fetch('/api/status').then((r) => r.json()));
}

/** Upload two generated PNGs from Home, open Workspace, assign Front and Top, name and save. */
export async function createPart(page: Page, name: string, views: Array<[string, string]> = [['front.png', 'front'], ['top.png', 'top']], shown: string | RegExp = name) {
  await boot(page, '#/home');
  await page.setInputFiles('#home-file', views.map(([n], i) => pngFile(n, i + 1)));
  await expect(page.locator('#home-create')).toHaveAttribute('aria-disabled', 'false');
  await page.click('#home-create');
  await expect(page).toHaveURL(/#\/workspace/);
  for (let i = 0; i < views.length; i++) {
    await page.locator('#orient-gallery select.oselect').nth(i).selectOption(views[i][1]);
  }
  await page.fill('#part-name', name);
  await expect(page.locator('#save-part-btn')).toBeEnabled();
  await page.click('#save-part-btn');
  // Optional confirm dialogs (duplicate / unassigned / replace) are not expected with this fixture.
  await expect(page.locator('#ws-part')).toHaveText(shown);
}

export async function startDemo(page: Page, sample?: string) {
  await page.click('#home-demo');
  const dlg = page.locator('#dialog-root .dlg');
  await expect(dlg).toBeVisible();
  if (sample) await dlg.locator('#demo-pick').selectOption(sample);
  await dlg.locator('button[data-action="run"]').click();
  await expect(page).toHaveURL(/#\/workspace/);
}
