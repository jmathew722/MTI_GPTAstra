import { test, expect } from '@playwright/test';
import { boot, startDemo, watchConsole } from '../helpers/app';

// Demo runs call POST /api/demo only; no model is invoked and no API key is needed.
test.describe('Demo runs', () => {
  test('6 Demo run: tracker reaches Build Plan, later stages skipped, 100 percent, results present, not in Recent', async ({ page }) => {
    const bad = watchConsole(page);
    await boot(page);
    await startDemo(page);
    await expect(page.locator('.trk-step[data-stage="build_plan"]')).toHaveAttribute('data-state', 'succeeded', { timeout: 20_000 });
    await expect(page.locator('.trk-step[data-stage="extraction"]')).toHaveAttribute('data-state', 'succeeded');
    await expect(page.locator('.trk-step[data-stage="resolution"]')).toHaveAttribute('data-state', 'succeeded');
    await expect(page.locator('.trk-step[data-stage="generation"]')).toHaveAttribute('data-state', 'skipped');
    await expect(page.locator('.trk-step[data-stage="verification"]')).toHaveAttribute('data-state', 'skipped');
    await expect(page.locator('#trk-pct')).toHaveAttribute('aria-valuetext', /100 percent/);
    await expect(page.locator('#trk-pct')).toHaveAttribute('aria-valuenow', '100');
    await expect(page.locator('#page-workspace .badge-c', { hasText: /^Demo$/ }).first()).toBeVisible();

    // Results sections are present for a demo run.
    await page.evaluate(() => { location.hash = '#/results'; });
    await expect(page.locator('#page-results')).toBeVisible();
    for (const label of ['Extraction', 'Build plan', 'Macros', 'Files']) {
      await expect(page.locator('#res-root').getByText(new RegExp(`^${label}`, 'i')).first()).toBeVisible();
    }
    await expect(page.locator('#page-results .badge-c', { hasText: /^Demo$/ }).first()).toBeVisible();

    // The demo never enters Recent or Projects.
    const hist = await page.evaluate(() => (window as any).McA.store.get().history.runs.map((r: any) => r.part));
    for (const where of ['recent', 'projects']) {
      await page.evaluate((h) => { location.hash = h; }, `#/${where}`);
      const txt = await page.locator(`#page-${where}`).innerText();
      expect(txt).not.toMatch(/\bdemo\b/i);
    }
    await page.evaluate(() => { location.hash = '#/home'; });
    await expect(page.locator('#home-recent-list')).not.toContainText(/demo|115C|116C|117C/i);
    expect(hist.join(',')).not.toMatch(/115C|116C|117C|demo/i);
    expect(bad, bad.join('\n')).toEqual([]);
  });

  test('7 Refresh during a demo run: tracker reattaches, POST /api/demo happens once', async ({ page }) => {
    await boot(page);
    let demoPosts = 0;
    page.on('request', (r) => { if (r.method() === 'POST' && /\/api\/demo$/.test(r.url())) demoPosts++; });
    await page.click('#home-demo');
    const posted = page.waitForResponse((r) => /\/api\/demo$/.test(r.url()) && r.request().method() === 'POST');
    await page.locator('#dialog-root button[data-action="run"]').click();
    await posted;
    await page.reload();
    await page.waitForFunction(() => !!(window as any).McA && (window as any).McA.store.get().session.id);
    await page.evaluate(() => { location.hash = '#/workspace'; });
    await expect(page.locator('.trk-step[data-stage="build_plan"]')).toHaveAttribute('data-state', 'succeeded', { timeout: 20_000 });
    await expect(page.locator('#trk-pct')).toHaveAttribute('aria-valuenow', '100');
    expect(demoPosts).toBe(1);
  });

  test('8 Cancel: state Cancelled, no percent, no success chip', async ({ page }) => {
    await boot(page);
    await startDemo(page);
    await page.locator('#cancel-btn').click({ timeout: 5_000 });
    await expect(page.locator('#dr-state')).toHaveText(/Cancelled/);
    await expect(page.locator('#trk-stage')).toHaveText(/Cancelled/);
    const pct = page.locator('#trk-pct');
    await expect(pct).toHaveAttribute('aria-valuetext', 'Cancelled');
    expect(await pct.getAttribute('aria-valuenow')).toBeNull();
    expect(await pct.innerText()).not.toMatch(/\d+\s*%/);
    await expect(page.locator('#dr-state')).not.toHaveText(/Completed|Succeeded/);
    await expect(page.locator('#dr-verdict')).not.toContainText(/Passed/);
  });
});
