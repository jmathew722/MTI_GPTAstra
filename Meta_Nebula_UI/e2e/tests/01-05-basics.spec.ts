import { test, expect } from '@playwright/test';
import { boot, createPart, status, uniq, watchConsole } from '../helpers/app';

test.describe('Boot, routing, status, upload, run gating', () => {
  test('1 Boot: no console errors, sidebar items, Home heading, one gold button', async ({ page }) => {
    const bad = watchConsole(page);
    await boot(page);
    await expect(page.locator('#page-home h1')).toHaveText(/What would you like to create/);
    for (const p of ['home', 'workspace', 'projects', 'results', 'recent', 'help', 'settings']) {
      await expect(page.locator(`#sidebar .sb-item[data-page="${p}"]`)).toHaveCount(1);
    }
    await expect(page.locator('#sb-new')).toBeVisible();
    // Exactly one .btn.gold in the whole document (the Run Pipeline button), visible or not.
    expect(await page.locator('.btn.gold').count()).toBe(1);
    await expect(page.locator('#run-btn')).toHaveClass(/gold/);
    expect(bad, bad.join('\n')).toEqual([]);
  });

  test('2 Routing: each hash shows its page with aria-current, unknown hash goes Home', async ({ page }) => {
    const bad = watchConsole(page);
    await boot(page);
    for (const p of ['workspace', 'projects', 'results', 'recent', 'help', 'settings', 'home']) {
      await page.evaluate((h) => { location.hash = h; }, `#/${p}`);
      await expect(page.locator(`#page-${p}`)).toBeVisible();
      await expect(page.locator(`#sidebar .sb-item[data-page="${p}"]`)).toHaveAttribute('aria-current', 'page');
      await expect(page.locator('.page:not([hidden])')).toHaveCount(1);
      await expect(page.locator('main h1:visible')).toHaveCount(1);
    }
    await page.evaluate(() => { location.hash = '#/definitely-not-a-page'; });
    await expect(page.locator('#page-home')).toBeVisible();
    await expect(page).toHaveURL(/#\/home/);
    expect(bad, bad.join('\n')).toEqual([]);
  });

  test('3 Status honesty: API chip matches /api/status; never "Connected"; engine not hard-coded', async ({ page }) => {
    await boot(page, '#/workspace');
    const st = await status(page);
    const api = page.locator('#hdr-api');
    await expect(api).toContainText(st.live ? /API key set/i : /No API key/i);
    const body = await page.locator('body').innerText();
    expect(body).not.toMatch(/connected/i);
    for (const p of ['settings', 'help', 'projects', 'results', 'recent']) {
      await page.evaluate((h) => { location.hash = h; }, `#/${p}`);
      expect(await page.locator('main').innerText()).not.toMatch(/\bconnected\b/i);
    }
    await page.evaluate(() => { location.hash = '#/workspace'; });
    const engine = (await page.locator('#hdr-engine .chip-v').innerText()).trim();
    if (!(st as any).model) expect(engine).toMatch(/not reported|unknown|—|n\/a/i);
    else expect(engine).toContain((st as any).model);
    // No model or vendor name is baked into the markup or scripts.
    const srcs = await page.evaluate(async () => {
      const urls = Array.from(document.scripts).map((s) => s.src).filter(Boolean);
      return Promise.all(urls.filter((u) => u.includes('/static/')).map((u) => fetch(u).then((r) => r.text())));
    });
    for (const src of srcs) expect(src).not.toMatch(/opus|sonnet|haiku|claude-|gpt-/i);
  });

  test('4 Upload and save a part; it persists across refresh (session reuse)', async ({ page }) => {
    const bad = watchConsole(page);
    const name = uniq('e2e-part-');
    await createPart(page, name);
    await page.click('#part-switch');
    await expect(page.locator('#part-list')).toContainText(name);
    await page.keyboard.press('Escape');
    await page.evaluate(() => { location.hash = '#/projects'; });
    await expect(page.locator('#proj-body .pcard-n', { hasText: name })).toBeVisible();
    await page.reload();
    await page.waitForFunction(() => (window as any).McA.store.get().parts.list.length > 0);
    await page.evaluate(() => { location.hash = '#/projects'; });
    await expect(page.locator('#proj-body .pcard-n', { hasText: name })).toBeVisible();
    expect(bad, bad.join('\n')).toEqual([]);
  });

  test('5 Run button gating: reason with no part, API-key reason when live is false', async ({ page }) => {
    await boot(page, '#/workspace');
    const btn = page.locator('#run-btn');
    await expect(btn).toHaveAttribute('aria-disabled', 'true');
    await expect(page.locator('#run-reason')).toBeVisible();
    await expect(page.locator('#run-reason')).not.toBeEmpty();
    expect(await btn.getAttribute('aria-describedby')).toBe('run-reason');
    const st = await status(page);
    const name = uniq('e2e-gate-');
    await createPart(page, name);
    if (!st.live) {
      await expect(btn).toHaveAttribute('aria-disabled', 'true');
      await expect(page.locator('#run-reason')).toContainText(/API[_ ]KEY/i);
    } else {
      test.info().annotations.push({ type: 'note', description: 'Server reports live:true; the API-key reason cannot be asserted and Run is never clicked.' });
      await expect(btn).toHaveAttribute('aria-disabled', 'false');
    }
  });
});
