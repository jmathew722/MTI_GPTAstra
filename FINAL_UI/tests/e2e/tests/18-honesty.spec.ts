import { test, expect } from '@playwright/test';
import { boot, createPart, startDemo, uniq, watchConsole } from '../helpers/app';

test.describe('Honesty rules (ARCH 16)', () => {
  test('18 no "Connected", one gold button, no hard-coded engine, learning loop disabled with reason, demo isolated', async ({ page }) => {
    const bad = watchConsole(page);
    await createPart(page, uniq('e2e-honest-'));
    await page.evaluate(() => { location.hash = '#/home'; });
    await startDemo(page);
    await expect(page.locator('#trk-pct')).toHaveAttribute('aria-valuenow', '100', { timeout: 20_000 });

    // Gold is reserved: exactly one .btn.gold, and no element other than the button and the tracker's
    // current stage paints with the gold token.
    expect(await page.locator('.btn.gold').count()).toBe(1);
    const gold = await page.evaluate(() => {
      const probe = document.createElement('span');
      probe.style.color = getComputedStyle(document.documentElement).getPropertyValue('--gold').trim();
      document.body.append(probe);
      const rgb = getComputedStyle(probe).color; probe.remove();
      const hits: string[] = [];
      document.querySelectorAll('#page-workspace *').forEach((el) => {
        const cs = getComputedStyle(el);
        if (cs.backgroundColor === rgb || cs.borderTopColor === rgb) {
          const r = (el as HTMLElement).getBoundingClientRect();
          if (r.width && r.height) hits.push((el.id ? '#' + el.id : '') + '.' + String((el as HTMLElement).className).split(' ').join('.'));
        }
      });
      return hits;
    });
    for (const h of gold) expect(h, `unexpected gold use: ${h}`).toMatch(/run-btn|btn\.gold|trk-/);

    // Learning loop button is disabled and explains why.
    await page.evaluate(() => { location.hash = '#/results?sec=flags'; });
    const save = page.getByRole('button', { name: /Save all to Learning Loop/ });
    await expect(save).toBeVisible();
    await expect(save).toHaveAttribute('aria-disabled', 'true');
    await expect(page.locator('#flags-save-why')).toContainText(/Not available/);

    // The word "Connected" never appears on any page, and no model/vendor name is in the sources.
    for (const p of ['home', 'workspace', 'projects', 'results', 'recent', 'help', 'settings']) {
      await page.evaluate((h) => { location.hash = h; }, `#/${p}`);
      expect(await page.locator(`#page-${p}`).innerText()).not.toMatch(/\bconnected\b/i);
    }
    const html = await page.content();
    expect(html).not.toMatch(/opus|sonnet|haiku/i);

    // Demo data stays out of Projects and Recent.
    for (const p of ['projects', 'recent']) {
      await page.evaluate((h) => { location.hash = h; }, `#/${p}`);
      expect(await page.locator(`#page-${p}`).innerText()).not.toMatch(/\bdemo\b|115C|116C|117C/i);
    }
    expect(bad, bad.join('\n')).toEqual([]);
  });
});
