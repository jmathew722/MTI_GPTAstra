import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import * as fs from 'fs';
import * as path from 'path';
import { buildFixture, enclosing, geometry, seedFlagsPart, STAGE2_OUT, toScreen, uniq } from '../helpers/stage3';

test.skip(!STAGE2_OUT, 'STAGE2_OUT not set: start the server with MCAGENT_FINAL_OUTPUTS=$STAGE2_OUT and export STAGE2_OUT');

const EVID = path.resolve(__dirname, '../../../../docs/test-reports/stage3-evidence');
const serious = (res: any) => res.violations.filter((v: any) => v.impact === 'serious' || v.impact === 'critical');

async function openFlags(page: any) {
  await page.evaluate(() => (window as any).McA.dom.setUi({ drawerOpen: true, drawerSection: 'flags', drawerMode: 'results' }));
  await expect(page.locator('#dr-results .dfl')).toBeVisible({ timeout: 15_000 });
}

test.describe('Stage 3: automatic engineering flags over the drawing', () => {
  test('31 a modeled mismatch becomes a red box over its callout with no human positioning, and the panel explains it', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    fs.mkdirSync(EVID, { recursive: true });
    const part = uniq(), fx = buildFixture(part, 0, 'main');
    // the artifacts came from the pipeline stage alone: every overlay is automatic and no hand-authored positions exist
    const art = JSON.parse(fs.readFileSync(path.join(fx.run_dir, 'engineering_flag_overlays.json'), 'utf-8'));
    expect(art.source_pdf_sha256).toBe(fx.sha256);
    expect(art.overlays.map((o: any) => o.provenance)).toEqual(['automatic', 'automatic']);
    expect(fs.readdirSync(fx.run_dir).filter((f) => /^markup_positions/.test(f))).toEqual([]);
    const session = await seedFlagsPart(page, request, part, fx);
    await expect(page.locator('.flag-box')).toHaveCount(2, { timeout: 15_000 });
    const g = await geometry(page);
    for (const key of ['tap', 'edge'] as const) {
      const hits = enclosing(g, toScreen(g, fx.expected_px[key]));
      expect(hits.length, `a red box must enclose the ${key} callout`).toBe(1);
      expect(hits[0].sev).toBe('error');
    }
    await expect(page.locator('.flag-box').first().locator('.flag-badge')).toContainText(/\d ERR/);     // severity is text, not just colour
    await page.screenshot({ path: path.join(EVID, 'viewer-flags-1440x900.png') });
    // the panel shows expected / actual / consequence / manual repair for the selected flag, and the link is both ways
    const first = page.locator('.flag-box').first();
    const fid = await first.getAttribute('data-finding');
    await first.click();
    await expect(page.locator('#drawer')).toHaveAttribute('data-open', 'true');
    const card = page.locator(`.flagcard[data-finding="${fid}"]`);
    await expect(card).toHaveAttribute('aria-current', 'true');
    await expect(first).toHaveAttribute('aria-current', 'true');
    for (const label of ['Expected', 'Actual', 'Consequence', 'Recommended manual repair']) await expect(card.locator('dt', { hasText: label })).toBeVisible();
    await expect(card.locator('.flag-loc')).toContainText(/Page 1 · exact match · 97% confidence/);
    await page.screenshot({ path: path.join(EVID, 'viewer-flag-selected-with-panel.png') });
    // card -> drawing: "Show on drawing" zooms to the flag and centres it
    const before = await page.evaluate(() => (window as any).McA.viewer2d.getView().z.s);
    await card.getByRole('button', { name: 'Show on drawing' }).click();
    await expect.poll(async () => page.evaluate(() => (window as any).McA.viewer2d.getView().z.s)).toBeGreaterThan(before * 1.2);
    const g2 = await geometry(page);
    const b2 = g2.boxes.find((b) => b.id === fid)!;
    const vb = await page.locator('#ov-box').boundingBox();
    expect(Math.abs((b2.left + b2.right) / 2 - (vb!.x + vb!.width / 2))).toBeLessThan(6);
    expect(Math.abs((b2.top + b2.bottom) / 2 - (vb!.y + vb!.height / 2))).toBeLessThan(6);
    // the exported PDF comes from the same artifact
    const pdfRes = await request.get(`/api/parts/${session}/${part}/file/engineering_flags_annotated.pdf`);
    expect(pdfRes.status()).toBe(200);
    expect((await pdfRes.body()).subarray(0, 4).toString()).toBe('%PDF');
  });

  for (const rot of [90, 180, 270]) {
    test(`32 the box stays on its callout when the sheet is rotated ${rot} degrees`, async ({ page, request }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      const part = uniq(), fx = buildFixture(part, rot, 'main');
      await seedFlagsPart(page, request, part, fx);
      await expect(page.locator('.flag-box')).toHaveCount(2, { timeout: 15_000 });
      const g = await geometry(page);
      for (const key of ['tap', 'edge'] as const) expect(enclosing(g, toScreen(g, fx.expected_px[key])).length, `${key} @${rot}`).toBe(1);
      fs.mkdirSync(EVID, { recursive: true });
      await page.screenshot({ path: path.join(EVID, `viewer-flags-rot${rot}.png`) });
    });
  }

  test('33 an ambiguous or unfindable callout is never boxed: it is listed as not located, with the reason', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const dialogs: string[] = [];
    page.on('dialog', async (d) => { dialogs.push(d.message()); await d.dismiss(); });
    const part = uniq(), fx = buildFixture(part, 0, 'ambiguous');
    await seedFlagsPart(page, request, part, fx);
    await expect(page.locator('.flag-box')).toHaveCount(2, { timeout: 15_000 });      // only the two unambiguous callouts
    const g = await geometry(page);
    // the duplicated callout's two blue blocks have no box on them
    const covered = (b: number[]) => { const e = toScreen(g, b); return g.boxes.some((x) => x.left <= e.right && x.right >= e.left && x.top <= e.bottom && x.bottom >= e.top); };
    expect(fx.blue_blocks.filter(covered).length).toBe(2);
    await openFlags(page);
    const un = page.locator('#dr-results .flagcards[aria-label="Flags not located on the drawing"]');
    await expect(un.locator('.flagcard')).toHaveCount(2);
    await expect(un).toContainText('2 equally good matches, so none was guessed');
    await expect(un).toContainText('the callout text was not found on the drawing');
    // hostile text from a callout renders as inert text
    await expect(un).toContainText('<img src=x onerror=alert(1)>');
    expect(await page.locator('#dr-results .dfl img').count()).toBe(0);
    expect(dialogs).toEqual([]);
    await page.screenshot({ path: path.join(EVID, 'panel-unlocated.png') });
  });

  test('34 boxes stay aligned through zoom, pan and a resized window', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = uniq(), fx = buildFixture(part, 0, 'main');
    await seedFlagsPart(page, request, part, fx);
    await expect(page.locator('.flag-box')).toHaveCount(2, { timeout: 15_000 });
    const check = async (label: string) => {
      const g = await geometry(page);
      for (const key of ['tap', 'edge'] as const) expect(enclosing(g, toScreen(g, fx.expected_px[key]), 6).length, `${label}: ${key}`).toBe(1);
    };
    await check('fit');
    const bx = (await page.locator('#ov-box').boundingBox())!;
    await page.mouse.move(bx.x + bx.width / 2, bx.y + bx.height / 2);
    await page.mouse.wheel(0, -300);
    await page.waitForTimeout(150);
    await check('zoomed');
    await page.mouse.move(bx.x + 200, bx.y + 200); await page.mouse.down(); await page.mouse.move(bx.x + 260, bx.y + 230); await page.mouse.up();
    await page.waitForTimeout(100);
    await check('panned');
    await page.keyboard.press('Escape');
    await page.evaluate(() => (window as any).McA.viewer2d.fit());
    await page.setViewportSize({ width: 1180, height: 760 });
    await page.waitForTimeout(250);
    await check('resized');
  });

  test('35 keyboard: Tab to a box, arrows move between flags, Enter selects, Escape clears; focus is visible', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = uniq(), fx = buildFixture(part, 0, 'main');
    await seedFlagsPart(page, request, part, fx);
    await expect(page.locator('.flag-box')).toHaveCount(2, { timeout: 15_000 });
    const boxes = page.locator('.flag-box');
    await boxes.first().focus();
    await expect(boxes.first()).toBeFocused();
    const outline = await boxes.first().evaluate((e) => getComputedStyle(e).outlineStyle);
    expect(outline).not.toBe('none');
    const firstId = await boxes.first().getAttribute('data-finding');
    await page.keyboard.press('ArrowRight');
    const focusedId = await page.evaluate(() => document.activeElement?.getAttribute('data-finding'));
    expect(focusedId).not.toBe(firstId);
    await page.keyboard.press('Enter');
    await expect(page.locator(`.flagcard[data-finding="${focusedId}"]`)).toHaveAttribute('aria-current', 'true');
    await page.keyboard.press('Escape');
    await expect(page.locator('.flagcard[aria-current="true"]')).toHaveCount(0);
    // the list is keyboard-navigable too
    await openFlags(page);
    const cards = page.locator('#dr-results .flagcard');
    await cards.first().focus();
    const id0 = await cards.first().getAttribute('data-finding');
    await page.keyboard.press('ArrowDown');
    await expect.poll(async () => page.evaluate(() => document.activeElement?.getAttribute('data-finding'))).not.toBe(id0);
  });

  test('36 filters, review states and a dismissal that needs a reason; the pipeline finding is never edited', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = uniq(), fx = buildFixture(part, 0, 'ambiguous');
    await seedFlagsPart(page, request, part, fx);
    await expect(page.locator('.flag-box')).toHaveCount(2, { timeout: 15_000 });
    await openFlags(page);
    const all = await page.locator('#dr-results .flagcard').count();
    expect(all).toBe(4);
    // severity: the open question is a warning, the unbuilt features are errors
    await page.locator('#dr-results .dfl-filter button', { hasText: /^Warning/ }).click();
    await expect(page.locator('#dr-results .flagcard')).toHaveCount(1);
    await expect(page.locator('.flag-box')).toHaveCount(0);                          // filters hide boxes on the drawing too
    await page.locator('#dr-results .dfl-filter button', { hasText: /^Warning/ }).click();
    await page.locator('#dr-results select[aria-label="Filter by location"]').selectOption('located');
    await expect(page.locator('#dr-results .flagcard')).toHaveCount(2);
    await page.locator('#dr-results select[aria-label="Filter by location"]').selectOption('unlocated');
    await expect(page.locator('#dr-results .flagcard')).toHaveCount(2);
    await page.locator('#dr-results select[aria-label="Filter by location"]').selectOption('all');
    // review: a dismissal needs a reason; nothing is sent without it
    const findingsFile = path.join(fx.run_dir, 'engineering_findings.json');
    const before = fs.readFileSync(findingsFile);
    const card = page.locator('#dr-results .flagcard').first();
    await card.locator('select[aria-label^="Review state"]').selectOption('dismissed_with_reason');
    await card.getByRole('button', { name: 'Save review' }).click();
    await expect(card).toContainText('A dismissal needs a reason.');
    await card.locator('input[aria-label^="Reason for dismissing"]').fill('Handled at the machine');
    await card.getByRole('button', { name: 'Save review' }).click();
    await expect(page.locator('#dr-results .flagcard[data-state="dismissed_with_reason"]')).toHaveCount(1, { timeout: 10_000 });
    const second = page.locator('#dr-results .flagcard[data-state="open"]').first();
    await second.locator('select[aria-label^="Review state"]').selectOption('corrected_pending_rerun');
    await second.getByRole('button', { name: 'Save review' }).click();
    await expect(page.locator('#dr-results .flagcard[data-state="corrected_pending_rerun"]')).toHaveCount(1, { timeout: 10_000 });
    expect(fs.readFileSync(findingsFile).equals(before)).toBe(true);              // immutable pipeline evidence
  });

  test('37 a different revision of the drawing withholds the overlays and says so', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = uniq(), fx = buildFixture(part, 0, 'main', true);
    const session = await seedFlagsPart(page, request, part, fx);
    await expect(page.locator('.flag-box')).toHaveCount(2, { timeout: 15_000 });
    const up = await request.post('/api/parts', { multipart: { session, part,
      original: { name: 'rev_b.pdf', mimeType: 'application/pdf', buffer: fs.readFileSync(fx.alt_pdf!) } } });
    expect(up.ok()).toBeTruthy();
    await page.reload();
    await expect(page.locator('#ws-part')).toHaveText(part, { timeout: 15_000 });
    await page.waitForFunction(() => { const s = (window as any).McA.store.get(); const f = s.outputs.payload && s.outputs.payload.categories.flags; return f && f.present; });
    await expect(page.locator('.flag-box')).toHaveCount(0);
    await openFlags(page);
    await expect(page.locator('#dr-results .dfl .banner')).toContainText(/different revision/i);
    expect(await page.locator('#dr-results .flagcard').count()).toBeGreaterThan(0);          // the findings are still listed
  });

  test('38 high contrast, reduced motion, narrow viewport and axe', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = uniq(), fx = buildFixture(part, 0, 'main');
    await seedFlagsPart(page, request, part, fx);
    await expect(page.locator('.flag-box')).toHaveCount(2, { timeout: 15_000 });
    await openFlags(page);
    const res = await new AxeBuilder({ page }).include('#ov-flag-layer').include('#dr-results .dfl').withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
    fs.mkdirSync(EVID, { recursive: true });
    fs.writeFileSync(path.join(EVID, 'axe-stage3.json'), JSON.stringify({ checked: ['#ov-flag-layer', '#dr-results .dfl'],
      serious_or_critical: serious(res).map((v: any) => ({ id: v.id, nodes: v.nodes.length })), all: res.violations.map((v: any) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })) }, null, 2));
    expect(serious(res), JSON.stringify(serious(res).map((v: any) => v.id))).toEqual([]);
    // forced colors: the box must still have a visible border and text
    await page.emulateMedia({ forcedColors: 'active', reducedMotion: 'reduce' });
    const bw = await page.locator('.flag-box').first().evaluate((e) => parseFloat(getComputedStyle(e).borderTopWidth));
    expect(bw).toBeGreaterThan(0);
    expect(await page.locator('.flag-box').first().evaluate((e) => parseFloat(getComputedStyle(e).transitionDuration))).toBeLessThanOrEqual(0.001);
    await page.emulateMedia({ forcedColors: 'none' });
    // narrow
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(250);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    await expect(page.locator('#dr-results .flagcard').first()).toBeVisible();
    await page.screenshot({ path: path.join(EVID, 'panel-390x844.png') });
  });
});

test.describe('Stage 3 on a 2x device pixel ratio', () => {
  test.use({ deviceScaleFactor: 2 });
  test('39 alignment does not depend on the device pixel ratio', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = uniq(), fx = buildFixture(part, 90, 'main');
    await seedFlagsPart(page, request, part, fx);
    await expect(page.locator('.flag-box')).toHaveCount(2, { timeout: 15_000 });
    expect(await page.evaluate(() => window.devicePixelRatio)).toBe(2);
    const g = await geometry(page);
    for (const key of ['tap', 'edge'] as const) expect(enclosing(g, toScreen(g, fx.expected_px[key])).length).toBe(1);
  });
});
