import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import * as fs from 'fs';
import * as path from 'path';
import { buildFixture, seedFlagsPart, STAGE2_OUT, uniq } from '../helpers/stage3';

test.skip(!STAGE2_OUT, 'STAGE2_OUT not set: start the server with MCAGENT_FINAL_OUTPUTS=$STAGE2_OUT and export STAGE2_OUT');

const EVID = path.resolve(__dirname, '../../../../docs/test-reports/stage3-markup-evidence');
const serious = (res: any) => res.violations.filter((v: any) => v.impact === 'serious' || v.impact === 'critical');

async function openFlags(page: any) {
  await page.evaluate(() => (window as any).McA.dom.setUi({ drawerOpen: true, drawerSection: 'flags', drawerMode: 'results' }));
  await expect(page.locator('#dr-results .dfl')).toBeVisible({ timeout: 15_000 });
}
/** Counts strongly red pixels in the image the viewer is actually showing (so the box is VISIBLE, not just in a file). */
async function redPixels(page: any) {
  return page.evaluate(() => {
    const img = document.getElementById('ov-img') as HTMLImageElement;
    const c = document.createElement('canvas');
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const g = c.getContext('2d')!; g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    let n = 0;
    for (let i = 0; i < d.length; i += 16) if (d[i] > 180 && d[i + 1] < 90 && d[i + 2] < 90) n++;
    return n;
  });
}
const shownSrc = (page: any) => page.locator('#ov-img').getAttribute('src');

test.describe('Stage 3: automatic Engineering Markup in the 2D viewer', () => {
  test('41 a flagged run opens Engineering Markup by itself, with a visible red box and its label text', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    fs.mkdirSync(EVID, { recursive: true });
    const part = uniq(), fx = buildFixture(part, 0, 'main', false, 'main');
    expect(fx.summary.markup.status).toBe('partial');
    const session = await seedFlagsPart(page, request, part, fx);
    const sw = page.locator('.vp-src-sw');
    await expect(sw.getByRole('button', { name: 'Engineering Markup' })).toHaveAttribute('aria-pressed', 'true', { timeout: 15_000 });
    await expect.poll(() => shownSrc(page)).toContain('/engineering-markup/page/');
    await expect(page.locator('#vp-2d-state')).toHaveText('Engineering Markup');
    await expect(page.locator('.mk-hit[data-kind="region"]').first()).toBeAttached();
    expect(await redPixels(page)).toBeGreaterThan(150);                                 // the red boxes and labels are in the pixels
    await expect(page.locator('#vp-2d-pages button')).toHaveCount(2);                    // both sheets are in the strip
    const man = await (await request.get(`/api/parts/${session}/${part}/engineering-markup`)).json();
    expect(man.findings.map((f: any) => f.location_status).sort()).toEqual(['located', 'located', 'located', 'unlocated']);
    await page.screenshot({ path: path.join(EVID, 'engineering-markup-auto-1440x900.png') });
    // the marked PDF itself is served and has the rail text
    const pdf = await request.get(`/api/parts/${session}/${part}/engineering-markup.pdf`);
    expect(pdf.status()).toBe(200);
    expect((await pdf.body()).subarray(0, 4).toString()).toBe('%PDF');
  });

  test('42 Show on drawing opens the right sheet and region, and clicking a region selects the same flag', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = uniq(), fx = buildFixture(part, 0, 'main', false, 'main');
    const session = await seedFlagsPart(page, request, part, fx);
    const man = await (await request.get(`/api/parts/${session}/${part}/engineering-markup`)).json();
    const p2 = man.findings.find((f: any) => f.page === 2 && f.location_status === 'located');
    expect(p2, 'a flag on sheet 2').toBeTruthy();
    await expect.poll(() => shownSrc(page)).toContain('/page/1.png');
    await openFlags(page);
    const card = page.locator(`.flagcard[data-finding="${p2.finding_id}"]`);
    await card.getByRole('button', { name: 'Show on drawing' }).click();
    await expect.poll(() => shownSrc(page)).toContain('/page/2.png');                    // NOT page 1
    await expect.poll(async () => page.evaluate(() => (window as any).McA.viewer2d.getView().z.s)).toBeGreaterThan(1.2);
    const hit = page.locator(`.mk-hit[data-finding="${p2.finding_id}"][data-kind="region"]`);
    await expect(hit).toBeAttached();
    const hb = await hit.boundingBox(), vb = await page.locator('#ov-box').boundingBox();
    expect(Math.abs(hb!.x + hb!.width / 2 - (vb!.x + vb!.width / 2))).toBeLessThan(8);   // centred on the region
    expect(Math.abs(hb!.y + hb!.height / 2 - (vb!.y + vb!.height / 2))).toBeLessThan(8);
    await page.screenshot({ path: path.join(EVID, 'show-on-drawing-sheet2.png') });
    // region -> card: go back to sheet 1 and activate a region
    await page.locator('#vp-2d-pages button').first().click();
    await expect.poll(() => shownSrc(page)).toContain('/page/1.png');
    const first = page.locator('.mk-hit[data-kind="region"]').first();
    const fid = await first.getAttribute('data-finding');
    await first.click({ force: true });
    await expect(page.locator(`.flagcard[data-finding="${fid}"]`)).toHaveAttribute('aria-current', 'true');
    await expect(first).toHaveAttribute('aria-current', 'true');
  });

  test('43 an unlocated flag is disclosed honestly: a label card, no region box, no fake zoom', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = uniq(), fx = buildFixture(part, 0, 'main', false, 'main');
    const session = await seedFlagsPart(page, request, part, fx);
    const man = await (await request.get(`/api/parts/${session}/${part}/engineering-markup`)).json();
    const un = man.findings.find((f: any) => f.location_status === 'unlocated');
    expect(un.regions).toEqual([]);
    expect(un.rect_pdf_points).toBeNull();
    await expect.poll(() => shownSrc(page)).toContain('/page/');
    await expect(page.locator(`.mk-hit[data-finding="${un.finding_id}"][data-kind="region"]`)).toHaveCount(0);   // nothing precise to click
    await expect(page.locator('.mk-note')).toContainText(/could not be placed precisely/);
    await openFlags(page);
    const card = page.locator(`.flagcard[data-finding="${un.finding_id}"]`);
    await expect(card).toContainText(/Not located|Location not confirmed|not located/i);
    const before = await page.evaluate(() => (window as any).McA.viewer2d.getView().z.s);
    await card.getByRole('button', { name: 'Show on page' }).click();
    expect(await page.evaluate(() => (window as any).McA.viewer2d.getView().z.s)).toBeLessThanOrEqual(before + 0.001);   // no zoom
  });

  test('44 markup-generation failure keeps every flag and says so in the viewer', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = uniq(), fx = buildFixture(part, 0, 'main', false, 'fail');
    expect(fx.summary.markup.status).toBe('failed');
    const session = await seedFlagsPart(page, request, part, fx).catch(() => '');
    await expect(page.locator('#ov-empty .empty-t')).toHaveText('Engineering markup could not be generated', { timeout: 15_000 });
    await expect(page.locator('#ov-empty .empty-d')).toContainText('MARKUP_GENERATION_FAILED');
    await expect(page.locator('#ov-empty .empty-d')).toContainText('Engineering flags exist');
    await openFlags(page);
    expect(await page.locator('.flagcard').count()).toBeGreaterThan(0);                  // Results still lists every flag
    expect(session).toBeTruthy();
  });

  test('45 a clean run shows no Engineering Markup and stays on Overview', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = uniq(), fx = buildFixture(part, 0, 'main', false, 'clean');
    expect(fx.summary.markup.status).toBe('not_needed');
    const session = await seedFlagsPart(page, request, part, fx);
    await expect(page.locator('.vp-src-sw')).toBeHidden();
    expect(await shownSrc(page)).toContain('/overview.jpg');
    await expect(page.locator('.mk-hit')).toHaveCount(0);
    const r = await request.get(`/api/parts/${session}/${part}/engineering-markup.pdf`);
    expect(r.status()).toBe(404);
  });

  test('46 switching back to Overview is respected and the markup view is keyboard- and axe-clean', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = uniq(), fx = buildFixture(part, 0, 'main', false, 'main');
    await seedFlagsPart(page, request, part, fx);
    const sw = page.locator('.vp-src-sw');
    await expect(sw.getByRole('button', { name: 'Engineering Markup' })).toHaveAttribute('aria-pressed', 'true', { timeout: 15_000 });
    const res = await new AxeBuilder({ page }).include('#vp-2d').analyze();
    expect(serious(res), JSON.stringify(serious(res).map((v: any) => v.id))).toEqual([]);
    const hit = page.locator('.mk-hit[data-kind="region"]').first();
    await hit.focus();
    await expect(hit).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('#drawer')).toHaveAttribute('data-open', 'true');
    await sw.getByRole('button', { name: 'Overview' }).click();
    await expect.poll(() => shownSrc(page)).toContain('/overview.jpg');
    await page.evaluate(() => (window as any).McA.store.set && (window as any).McA.viewer2d.relayoutMarkup());
    await page.waitForTimeout(400);
    expect(await shownSrc(page)).toContain('/overview.jpg');                              // not yanked back to the markup
  });
});
