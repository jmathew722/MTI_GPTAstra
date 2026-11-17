import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { boot, createPart, status, uniq, watchConsole } from '../helpers/app';
import { drawingPng } from '../helpers/fixtures';

test.describe('Batch, XSS, clear all', () => {
  test('12 Batch upload: folder with two part subfolders is listed; Run All Parts is gated or opens a confirm dialog', async ({ page }) => {
    const bad = watchConsole(page);
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mca-batch-'));
    const a = uniq('batcha'), b = uniq('batchb');
    try {
      for (const [part, views] of [[a, ['front', 'top']], [b, ['front', 'right']]] as const) {
        fs.mkdirSync(path.join(root, part));
        views.forEach((v, i) => fs.writeFileSync(path.join(root, part, `${v}.png`), drawingPng(320, 240, i + 1)));
      }
      await boot(page, '#/projects');
      await page.setInputFiles('#proj-folder', root);
      await expect(page.locator('#proj-body .pcard-n', { hasText: a })).toBeVisible({ timeout: 15_000 });
      await expect(page.locator('#proj-body .pcard-n', { hasText: b })).toBeVisible();
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
    const st = await status(page);
    const runAll = page.locator('#proj-runall');
    if (!st.live) {
      // Without an API key the paid batch is gated, with the reason shown. Nothing can be confirmed.
      await expect(runAll).toHaveAttribute('aria-disabled', 'true');
      await expect(page.locator('#proj-runall-why')).toContainText(/API[_ ]?KEY|API key/i);
    } else {
      await expect(runAll).toHaveAttribute('aria-disabled', 'false');
      await runAll.click();
      const dlg = page.locator('#dialog-root .dlg');
      await expect(dlg).toBeVisible();
      await dlg.locator('button[data-action="cancel"]').click();   // never confirm: it would spend API budget
      await expect(dlg).toHaveCount(0);
    }
    expect(bad, bad.join('\n')).toEqual([]);
  });

  test('13 XSS: part notes, a region value and a hostile part name render as text, no script runs', async ({ page }) => {
    const bad = watchConsole(page);
    const dialogs: string[] = [];
    page.on('dialog', async (d) => { dialogs.push(d.message()); await d.dismiss(); });
    const payload = '<img src=x onerror="window.__xss=1;alert(1)">';
    const name = uniq('e2e-xss-');
    await createPart(page, name);

    // Notes (Views and must-meet specs is a disclosure that is closed for a saved part; calibration pass)
    await page.locator('#setup-more > summary').click();
    await page.fill('#part-notes', payload);
    await page.click('#save-notes-btn');
    await expect(page.locator('#toast-root')).toContainText(/Specs for/);
    // Region value
    await page.locator('#vp-2d [data-act="mark"]').click();
    const img = page.locator('#mk-img');
    await expect(img).toBeVisible({ timeout: 10_000 });
    const box = (await img.boundingBox())!;
    await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.4, box.y + box.height * 0.4, { steps: 5 });
    await page.mouse.up();
    const val = page.locator('.rg-val').first();
    await expect(val).toBeVisible();
    await val.fill(payload);
    await val.blur();
    await expect(page.locator('#mark-save-state')).toContainText(/saved/i);
    await page.click('#focus-close');

    // Hostile part name: save a second part under a markup name.
    await createPart(page, '<img src=x onerror=window.__xss=2>', [['front.png', 'front'], ['top.png', 'top']], /^img_src_x_onerror/);

    // Surfaces that echo user text.
    for (const hash of ['#/workspace', '#/projects', '#/recent', '#/results', '#/home']) {
      await page.evaluate((h) => { location.hash = h; }, hash);
      await page.waitForTimeout(200);
    }
    await page.evaluate(() => { location.hash = '#/workspace'; });
    expect(await page.evaluate(() => (window as any).__xss)).toBeUndefined();
    expect(await page.locator('img[src="x"]').count()).toBe(0);
    expect(dialogs).toEqual([]);
    // The note is shown literally in its textarea after a reload.
    await page.reload();
    await page.waitForFunction(() => (window as any).McA.store.get().parts.selected);
    await expect(page.locator('#part-notes')).toHaveValue(/<img src=x/);
    expect(await page.evaluate(() => (window as any).__xss)).toBeUndefined();
    expect(bad, bad.join('\n')).toEqual([]);
  });

  test('14 Clear all models: dialog shows the count; cancel leaves history intact', async ({ page }) => {
    await boot(page, '#/projects');
    await page.waitForFunction(() => (window as any).McA.store.get().history.loaded !== false);
    const before = await page.evaluate(() => fetch('/api/run-history').then((r) => r.json()).then((j) => j.runs.length));
    await page.click('#proj-more');
    await page.click('#proj-clear');
    const dlg = page.locator('#dialog-root .dlg');
    await expect(dlg).toBeVisible();
    await expect(dlg).toContainText(new RegExp(`${before} run`));
    await dlg.locator('button[data-action="cancel"]').click();   // never confirm: it deletes real outputs
    await expect(dlg).toHaveCount(0);
    const after = await page.evaluate(() => fetch('/api/run-history').then((r) => r.json()).then((j) => j.runs.length));
    expect(after).toBe(before);
  });
});
