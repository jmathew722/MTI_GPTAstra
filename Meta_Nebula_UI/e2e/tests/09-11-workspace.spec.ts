import { test, expect } from '@playwright/test';
import { boot, createPart, uniq, watchConsole } from '../helpers/app';

test.describe('Splitter, drawer, focus overlay, markup', () => {
  test('9 Splitter and drawer: keyboard resize, persistence across reload, aria-expanded toggles', async ({ page }) => {
    await boot(page, '#/workspace');
    const sp = page.locator('#splitter');
    await sp.focus();
    const before = Number(await sp.getAttribute('aria-valuenow'));
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowRight');
    const after = Number(await sp.getAttribute('aria-valuenow'));
    expect(after).toBeGreaterThan(before);
    await page.keyboard.press('Home');
    expect(Number(await sp.getAttribute('aria-valuenow'))).toBe(20);
    await page.keyboard.press('Enter');
    expect(Number(await sp.getAttribute('aria-valuenow'))).toBe(50);
    await page.keyboard.press('Shift+ArrowLeft');
    const moved = Number(await sp.getAttribute('aria-valuenow'));
    expect(moved).toBe(40);

    const tog = page.locator('#dr-toggle');
    await expect(tog).toHaveAttribute('aria-expanded', 'false');
    await tog.click();
    await expect(tog).toHaveAttribute('aria-expanded', 'true');
    const rz = page.locator('#dr-resize');
    await rz.focus();
    const h0 = Number(await rz.getAttribute('aria-valuenow'));
    await page.keyboard.press('ArrowUp');
    const h1 = Number(await rz.getAttribute('aria-valuenow'));
    expect(h1).toBeGreaterThan(h0);

    await page.waitForTimeout(400);       // persistence is debounced 150 ms
    await page.reload();
    await page.evaluate(() => { location.hash = '#/workspace'; });
    await expect(page.locator('#splitter')).toHaveAttribute('aria-valuenow', String(moved));
    await expect(page.locator('#dr-toggle')).toHaveAttribute('aria-expanded', 'true');
    await expect(page.locator('#dr-resize')).toHaveAttribute('aria-valuenow', String(h1));
    await page.locator('#dr-toggle').click();
    await expect(page.locator('#dr-toggle')).toHaveAttribute('aria-expanded', 'false');
  });

  test('10 Focus overlay: opens from the 2D toolbar, iframe loaded, Done returns focus, same iframe node', async ({ page }) => {
    const bad = watchConsole(page);
    await createPart(page, uniq('e2e-focus-'));
    const crop = page.locator('#vp-2d [data-act="crop"]');
    await expect(crop).toBeEnabled();
    await crop.focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('#focus')).toBeVisible();
    const frame = page.frameLocator('#photoapp');
    await expect(frame.locator('#openBtn')).toBeVisible({ timeout: 15_000 });
    await page.evaluate(() => { (document.getElementById('photoapp') as any).__tag = 'same-node'; });
    await page.click('#focus-close');
    await expect(page.locator('#focus')).toBeHidden();
    await expect(crop).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('#focus')).toBeVisible();
    expect(await page.evaluate(() => (document.getElementById('photoapp') as any).__tag)).toBe('same-node');
    await expect(frame.locator('#openBtn')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('#focus')).toBeHidden();
    await expect(crop).toBeFocused();
    expect(bad, bad.join('\n')).toEqual([]);
  });

  test('11 Markup persistence: draw a region, POST regions saved:1, reload, region drawn again', async ({ page }) => {
    const name = uniq('e2e-mark-');
    await createPart(page, name);
    const mark = page.locator('#vp-2d [data-act="mark"]');
    await expect(mark).toBeEnabled();
    await mark.click();
    await expect(page.locator('#focus')).toBeVisible();
    const img = page.locator('#mk-img');
    await expect(img).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('#mark-toggle')).toHaveAttribute('aria-pressed', 'true');
    const box = (await img.boundingBox())!;
    const post = page.waitForResponse((r) => /\/regions$/.test(r.url()) && r.request().method() === 'POST', { timeout: 10_000 });
    await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.45, box.y + box.height * 0.4, { steps: 6 });
    await page.mouse.up();
    await expect(page.locator('#ov-mark-layer .mark-box')).toHaveCount(1);
    const res = await post;
    expect((await res.json()).saved).toBe(1);
    await expect(page.locator('#mark-save-state')).toContainText(/saved/i);

    await page.reload();
    await page.waitForFunction(() => (window as any).McA.store.get().parts.selected);
    await page.evaluate(() => { location.hash = '#/workspace'; });
    await expect(page.locator('#ws-part')).toHaveText(name);
    await page.locator('#vp-2d [data-act="mark"]').click();
    await expect(page.locator('#ov-mark-layer .mark-box')).toHaveCount(1, { timeout: 10_000 });
  });
});
