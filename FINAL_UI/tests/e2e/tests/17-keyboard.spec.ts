import { test, expect } from '@playwright/test';
import { boot, createPart, uniq, watchConsole } from '../helpers/app';

// Keyboard-only walkthrough of the Workspace (CLAUDE.md section "Quality": keyboard + ARIA).
test.describe('Keyboard-only Workspace walkthrough', () => {
  test('17 sidebar toggle, run reason, splitter, drawer, inspector accordions, focus overlay, dialogs', async ({ page }) => {
    const bad = watchConsole(page);
    await createPart(page, uniq('e2e-kbd-'));

    // Skip link is the first tab stop and moves focus to main.
    await page.reload();
    await expect(page.locator('#ws-part')).toBeVisible();
    await page.keyboard.press('Tab');
    await expect(page.locator('.skip-link')).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('#main')).toBeFocused();

    // Sidebar toggle with Enter and Space; aria-expanded follows; focus stays on the toggle.
    const sb = page.locator('#sb-toggle');
    await sb.focus();
    const before = await sb.getAttribute('aria-expanded');
    await page.keyboard.press('Enter');
    await expect(sb).not.toHaveAttribute('aria-expanded', before!);
    await expect(sb).toBeFocused();
    await page.keyboard.press('Space');
    await expect(sb).toHaveAttribute('aria-expanded', before!);

    // Run button: focusable although unavailable, Enter does nothing, reason is exposed.
    const run = page.locator('#run-btn');
    await run.focus();
    await expect(run).toBeFocused();
    const reasonId = await run.getAttribute('aria-describedby');
    await expect(page.locator('#' + reasonId)).toBeVisible();
    await expect(page.locator('#' + reasonId)).not.toBeEmpty();
    const demoBefore = await page.evaluate(() => (window as any).McA.store.get().run.state);
    await page.keyboard.press('Enter');
    expect(await page.evaluate(() => (window as any).McA.store.get().run.state)).toBe(demoBefore);

    // Splitter keys.
    const sp = page.locator('#splitter');
    await sp.focus();
    await page.keyboard.press('End');
    await expect(sp).toHaveAttribute('aria-valuenow', '80');
    await page.keyboard.press('Enter');
    await expect(sp).toHaveAttribute('aria-valuenow', '50');

    // Drawer toggle and resizer.
    const dt = page.locator('#dr-toggle');
    await dt.focus();
    await page.keyboard.press('Enter');
    await expect(dt).toHaveAttribute('aria-expanded', 'true');
    const rz = page.locator('#dr-resize');
    await rz.focus();
    const h0 = Number(await rz.getAttribute('aria-valuenow'));
    await page.keyboard.press('Shift+ArrowUp');
    expect(Number(await rz.getAttribute('aria-valuenow'))).toBeGreaterThan(h0);
    await page.keyboard.press('Home');
    expect(Number(await rz.getAttribute('aria-valuenow'))).toBe(Number(await rz.getAttribute('aria-valuemin')));
    await dt.focus();
    await page.keyboard.press('Space');
    await expect(dt).toHaveAttribute('aria-expanded', 'false');

    // Inspector accordions toggle with Enter and Space and expose aria-expanded / aria-controls.
    for (const id of ['acc-btn-setup', 'acc-btn-actions', 'acc-btn-corrections', 'acc-btn-export']) {
      const b = page.locator('#' + id);
      await b.focus();
      const open = await b.getAttribute('aria-expanded');
      await page.keyboard.press('Enter');
      await expect(b).not.toHaveAttribute('aria-expanded', open!);
      await page.keyboard.press('Space');
      await expect(b).toHaveAttribute('aria-expanded', open!);
      await expect(page.locator('#' + (await b.getAttribute('aria-controls')))).toHaveCount(1);
    }

    // Focus overlay: open with Enter, focus moves inside, Escape closes and returns focus to the opener.
    const mark = page.locator('#vp-2d [data-act="mark"]');
    await mark.focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('#focus')).toBeVisible();
    expect(await page.evaluate(() => !!document.getElementById('focus')!.contains(document.activeElement))).toBe(true);
    await expect(page.locator('#main')).toHaveAttribute('inert', '');
    await page.keyboard.press('Escape');
    await expect(page.locator('#focus')).toBeHidden();
    await expect(mark).toBeFocused();

    // Dialog: opens from Home demo link, traps focus, Escape cancels and returns focus.
    await page.evaluate(() => { location.hash = '#/home'; });
    const link = page.locator('#home-demo');
    await link.focus();
    await page.keyboard.press('Enter');
    const dlg = page.locator('#dialog-root .dlg');
    await expect(dlg).toBeVisible();
    for (let i = 0; i < 6; i++) {
      await page.keyboard.press('Tab');
      expect(await page.evaluate(() => !!document.querySelector('#dialog-root .dlg')!.contains(document.activeElement))).toBe(true);
    }
    await page.keyboard.press('Escape');
    await expect(dlg).toHaveCount(0);
    await expect(link).toBeFocused();
    expect(bad, bad.join('\n')).toEqual([]);
  });
});
