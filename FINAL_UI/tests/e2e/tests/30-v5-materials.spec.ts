import { test, expect, Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { auditLayout, summarise, Finding } from '../helpers/layout-audit';
import { FINAL, replaceStl, seedMaterialPart, uniq, writeLibrary } from '../helpers/materials';

// Phase 1 material UI: the library control, the Material section, the viewer's appearance guard, Projects totals.
// Needs a server started with MCAGENT_FINAL_OUTPUTS (and MCAGENT_DATA) pointing at temp folders; the same value exported here.
test.skip(!FINAL, 'MCAGENT_FINAL_OUTPUTS not set: start the server with it and export it for the tests (fixtures never touch the real outputs)');

const VERIFY = path.resolve(__dirname, '../../../docs/verification/v5');
const serious = (res: any) => res.violations.filter((v: any) => v.impact === 'serious' || v.impact === 'critical');
const shot = async (page: Page, name: string) => { fs.mkdirSync(VERIFY, { recursive: true }); await page.screenshot({ path: path.join(VERIFY, name) }); };
const fmt = (fs_: Finding[]) => fs_.map((f) => `${f.kind} ${f.selector}: ${f.detail} ${JSON.stringify(f.text || '')}`);
const SIZES: Array<[number, number]> = [[1920, 1080], [1440, 900], [1366, 768], [1100, 800], [390, 844]];

async function demoSha(request: any): Promise<string> {
  const j = await (await request.get('/api/materials/catalog?source=demo&limit=1')).json();
  return j.sha256;
}
async function useSession(page: Page, sid: string, part?: string, hash = '#/workspace') {
  await page.goto('/#/home');
  await page.waitForFunction(() => !!(window as any).McA);
  await page.evaluate(([s, p]) => {
    const McA = (window as any).McA;
    McA.persist.set(McA.persist.KEYS.session, s);
    if (p) McA.persist.set(McA.persist.KEYS.selected, { session: s, part: p }); else McA.persist.remove(McA.persist.KEYS.selected);
  }, [sid, part || '']);
  await page.goto('/' + hash);
  await page.reload();
  await page.waitForFunction(() => !!(window as any).McA && (window as any).McA.store.get().session.id);
}
async function clearLibrary(request: any) { await request.delete('/api/materials/library'); }
async function resultsMaterial(page: Page, sid: string, part: string) {
  await useSession(page, sid, part, `#/results?run=${sid}|${part}&sec=material`);
  await expect(page.locator('#res-pane [data-sec="material"]')).toBeVisible({ timeout: 15_000 });
}

test.describe.configure({ mode: 'serial' });
test.describe('v5: materials', () => {
  let sha = '';
  let sid = '';
  const P = { ok: uniq('MatOk'), nospec: uniq('MatNone'), legacy: uniq('MatOld'), amb: uniq('MatAmb'), nocost: uniq('MatNoPrice') };

  test.beforeAll(async ({ request }) => {
    await clearLibrary(request);
    sha = await demoSha(request);
    sid = await seedMaterialPart(request, P.ok, 'verified', undefined, sha);
    await seedMaterialPart(request, P.nospec, 'notspec', sid, sha);
    await seedMaterialPart(request, P.legacy, 'legacy', sid, sha);
    await seedMaterialPart(request, P.amb, 'ambiguous', sid, sha);
    await seedMaterialPart(request, P.nocost, 'unpriced', sid, sha);
  });
  test.afterAll(async ({ request }) => { await clearLibrary(request); });

  test('90 the library control sits directly below Upload folder, in the DOM and on screen', async ({ page }) => {
    await useSession(page, sid, P.ok);
    const order = await page.evaluate(() => {
      const a = document.getElementById('batch-folder-lbl')!, b = document.getElementById('mat-lib')!;
      return { after: !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING), ta: a.getBoundingClientRect(), tb: b.getBoundingClientRect(),
        between: Array.from(document.querySelectorAll('#acc-setup > *')).map((e) => e.id || e.className).slice(0, 8) };
    });
    expect(order.after).toBe(true);
    expect(order.tb.top).toBeGreaterThanOrEqual(order.ta.bottom - 1);
    expect(order.tb.top - order.ta.bottom).toBeLessThan(60);                       // nothing else sits between them
    await expect(page.locator('#mat-lib-lbl')).toHaveText(/Browse Folder/);
    await expect(page.locator('#mat-lib-line')).toHaveText(/No company library\. Using the demo catalog\./);
    await expect(page.locator('#mat-lib-refresh')).toBeDisabled();
    await expect(page.locator('#mat-lib-clear')).toBeDisabled();
    await shot(page, 'part-setup-library-1440x900.png');
  });

  test('91 catalog preview opens, searches, shows price basis and closes with Escape', async ({ page }) => {
    await useSession(page, sid, P.ok);
    await page.click('#mat-lib-view');
    const dlg = page.locator('#dialog-root .dlg');
    await expect(dlg).toBeVisible();
    await expect(dlg.getByRole('heading', { name: 'Material catalog' })).toBeVisible();
    await expect(dlg.locator('tbody tr')).toHaveCount(3);
    await expect(dlg).toContainText('Generic carbon steel');
    await expect(dlg).toContainText('1.50 USD/kg');
    await expect(dlg).toContainText('synthetic demo usd per kg');
    await expect(dlg).toContainText('At build');
    await dlg.getByRole('searchbox').fill('copper');
    await expect(dlg.locator('tbody tr')).toHaveCount(1, { timeout: 5000 });
    await shot(page, 'catalog-preview-1440x900.png');
    expect(serious(await new AxeBuilder({ page }).include('#dialog-root').analyze())).toEqual([]);
    await page.keyboard.press('Escape');
    await expect(dlg).toHaveCount(0);
    await expect(page.locator('#mat-lib-view')).toBeFocused();
  });

  test('92 a company folder: browse upload, rejected count, refresh, demo fallback; files never touched', async ({ page, request }) => {
    const dir = writeLibrary(fs.mkdtempSync(path.join(os.tmpdir(), 'matlib-')));
    await useSession(page, sid, P.ok);
    await page.setInputFiles('#mat-lib-folder', dir);
    await expect(page.locator('#mat-lib-line')).toHaveText(/· 2 materials · 1 rejected/, { timeout: 15_000 });
    await expect(page.locator('#mat-lib-refresh')).toBeEnabled();
    await shot(page, 'part-setup-library-loaded-1440x900.png');
    // persists across a reload (server settings)
    await page.reload();
    await expect(page.locator('#mat-lib-line')).toHaveText(/2 materials · 1 rejected/, { timeout: 15_000 });
    // preview shows the company library first, with its rejection reason
    await page.click('#mat-lib-view');
    const dlg = page.locator('#dialog-root .dlg');
    await expect(dlg.locator('tbody tr')).toHaveCount(2);
    await expect(dlg).toContainText('1 record was rejected');
    await expect(dlg).toContainText('quote 2026');
    await page.keyboard.press('Escape');
    // a part resolved before the library existed is now out of date
    const m = await (await request.get(`/api/parts/${sid}/${P.ok}/material`)).json();
    expect(m.stale).toBe(true);
    await page.click('#mat-lib-refresh');
    await expect(page.locator('#toast-root, .toast').first()).toContainText(/refreshed/i, { timeout: 8000 });
    await page.click('#mat-lib-clear');
    await expect(page.locator('#mat-lib-line')).toHaveText(/Using the demo catalog\./, { timeout: 10_000 });
    expect(fs.existsSync(path.join(dir, 'materials.json'))).toBe(true);            // the user's folder is untouched
    // a folder with no usable file gives an actionable error and changes nothing
    const empty = fs.mkdtempSync(path.join(os.tmpdir(), 'matempty-'));
    fs.writeFileSync(path.join(empty, 'notes.txt'), 'x');
    await page.setInputFiles('#mat-lib-folder', empty);
    await expect(page.locator('#mat-lib-err')).toContainText(/no materials\.json/i);
    await expect(page.locator('#mat-lib-line')).toHaveText(/demo catalog/);
  });

  test('93 a server-side path can be entered; a bad path explains itself', async ({ page }) => {
    const dir = writeLibrary(fs.mkdtempSync(path.join(os.tmpdir(), 'matpath-')));
    await useSession(page, sid, P.ok);
    await page.locator('#mat-lib-path-box summary').click();
    await page.fill('#mat-lib-path', path.join(dir, 'nope'));
    await page.click('#mat-lib-path-go');
    await expect(page.locator('#mat-lib-err')).toContainText(/not a folder/);
    await page.fill('#mat-lib-path', dir);
    await page.click('#mat-lib-path-go');
    await expect(page.locator('#mat-lib-line')).toHaveText(/2 materials/, { timeout: 10_000 });
    await expect(page.locator('#mat-lib-err')).toBeHidden();
    await page.click('#mat-lib-clear');
    await expect(page.locator('#mat-lib-line')).toHaveText(/demo catalog/, { timeout: 10_000 });
  });

  test('94 the workspace card shows the verified material, its status and an illustrative cost', async ({ page }) => {
    await useSession(page, sid, P.ok);
    const card = page.locator('#mat-part');
    await expect(card).toContainText('Generic carbon steel', { timeout: 15_000 });
    await expect(card).toContainText('Verified on part');
    await expect(card).toContainText('0.99 USD');
    await expect(card).toContainText('illustrative');
    await page.goto('/#/workspace'); await useSession(page, sid, P.nospec);
    await expect(card).toContainText('No material specified on drawing', { timeout: 15_000 });
    await expect(card).toContainText('estimate unavailable');
    await useSession(page, sid, P.legacy);
    await expect(card).toContainText('Not evaluated yet', { timeout: 15_000 });
    await expect(card).toContainText('read from the drawing on the next run');
    await expect(card).not.toContainText('0.00');
  });

  test('95 Results > Material: evidence, catalog, native read-back, mass, cost label, caveats, files', async ({ page }) => {
    await resultsMaterial(page, sid, P.ok);
    const sec = page.locator('#res-pane [data-sec="material"]');
    await expect(sec).toContainText('Verified on part');
    await expect(sec).toContainText('MATERIAL: STEEL');
    await expect(sec).toContainText('page 1, region title_block');
    await expect(sec).toContainText('Interpretation (inferred, not quoted)');
    await expect(sec).toContainText('Catalog match');
    await expect(sec).toContainText('solidflow-demo (demo)');
    await expect(sec).toContainText('7,850 kg/m');
    await expect(sec).toContainText('Native read-back');
    await expect(sec).toContainText('Requested material');
    await expect(sec).toContainText('0.6594 kg');
    await expect(sec).toContainText('0.99 USD');
    await expect(sec).toContainText('Illustrative material estimate — not a supplier quote');
    await expect(sec).toContainText('Material only');
    await expect(sec).toContainText('From the last SolidWorks build');
    await expect(sec).toContainText('material_costing.json');
    await expect(sec).toContainText('appearance.json');
    expect(await sec.innerText()).not.toMatch(/hidden[\\/]server/);                  // absolute server paths never reach the page
    await expect(page.locator('#res-root .res-link[data-sec="material"]')).toHaveAttribute('data-tone', 'green');
    await shot(page, 'results-material-verified-1440x900.png');
    expect(serious(await new AxeBuilder({ page }).include('#res-pane').analyze())).toEqual([]);
  });

  test('96 not specified, ambiguous, unpriced and not-evaluated states are explicit', async ({ page }) => {
    await resultsMaterial(page, sid, P.nospec);
    let sec = page.locator('#res-pane [data-sec="material"]');
    await expect(sec).toContainText('No material specified on drawing');
    await expect(sec).toContainText('No material was assumed');
    await expect(sec).toContainText('estimate unavailable');
    await shot(page, 'results-material-not-specified-1440x900.png');
    await resultsMaterial(page, sid, P.amb);
    sec = page.locator('#res-pane [data-sec="material"]');
    await expect(sec).toContainText('Needs review');
    await expect(sec).toContainText('more than one material');
    await expect(sec).toContainText('Suggestions - approval required, never applied automatically');
    await expect(sec.getByRole('button', { name: /Use Generic carbon steel as the override/ })).toBeVisible();
    await expect(page.locator('#res-root .res-link[data-sec="material"]')).toHaveAttribute('data-tone', 'orange');
    await shot(page, 'results-material-ambiguous-1440x900.png');
    await resultsMaterial(page, sid, P.nocost);
    sec = page.locator('#res-pane [data-sec="material"]');
    await expect(sec).toContainText('estimate unavailable');
    await expect(sec).toContainText('no price');
    await expect(sec).not.toContainText('Illustrative material estimate');
    await resultsMaterial(page, sid, P.legacy);
    sec = page.locator('#res-pane [data-sec="material"]');
    await expect(sec).toContainText('Not evaluated yet');
    await expect(sec).toContainText('next run');
    await shot(page, 'results-material-not-evaluated-1440x900.png');
  });

  test('97 manual override: reason required, labelled as differing from the drawing, clearable', async ({ page, request }) => {
    await resultsMaterial(page, sid, P.nospec);
    const sec = page.locator('#res-pane [data-sec="material"]');
    const apply = sec.locator('#mat-ov-apply');
    await expect(apply).toHaveAttribute('aria-disabled', 'true');
    await expect(sec.locator('#mat-ov-why')).toHaveText('Choose a catalog material.');
    await sec.locator('#mat-ov-sel').selectOption('demo-copper');
    await expect(sec.locator('#mat-ov-why')).toHaveText('Enter a reason for the override.');
    await sec.locator('#mat-ov-reason').fill('Customer email 2026-11-02 asks for copper');
    await expect(apply).toHaveAttribute('aria-disabled', 'false');
    await apply.click();
    await expect(sec).toContainText('Manual override - differs from the drawing', { timeout: 10_000 });
    await expect(sec).toContainText('Drawing says: no material');
    await expect(sec).toContainText('Reason: Customer email 2026-11-02 asks for copper');
    await expect(sec).toContainText('Set by');
    await expect(sec).toContainText('Takes effect on the next run');
    await expect(sec).toContainText('Generic copper');
    await shot(page, 'results-material-override-1440x900.png');
    const api = await (await request.get(`/api/parts/${sid}/${P.nospec}/material`)).json();
    expect(api.resolution.selection_source).toBe('manual_override');
    await sec.locator('#mat-ov-clear').click();
    await expect(sec).not.toContainText('Manual override - differs', { timeout: 10_000 });
    await expect(sec).toContainText('No material specified on drawing');
  });

  test('98 refresh re-reads without SolidWorks or an API call and keeps build values labelled as the last build', async ({ page, request }) => {
    await resultsMaterial(page, sid, P.ok);
    const before = await (await request.get('/api/status')).json();
    await page.locator('#res-pane [data-sec="material"]').getByRole('button', { name: /Refresh material/ }).click();
    await expect(page.locator('#res-pane [data-sec="material"]')).toContainText('From the last SolidWorks build', { timeout: 10_000 });
    const after = await (await request.get('/api/status')).json();
    expect(after.live).toBe(before.live);
  });

  test('99 Projects and Recent: material and material cost are their own columns; unknown is never zero', async ({ page }) => {
    await useSession(page, sid, P.ok, '#/projects');
    const line = page.locator('#proj-mat-line');
    await expect(line).toContainText('estimate unavailable', { timeout: 15_000 });
    await expect(line).toContainText('not counted as zero');
    await expect(page.locator('#proj-body table th', { hasText: 'Material cost (estimate)' })).toBeVisible();
    const row = page.locator('#proj-body tbody tr', { hasText: P.ok });
    await expect(row).toContainText('Verified on part');
    await expect(row).toContainText('0.99 USD');
    const legacy = page.locator('#proj-body tbody tr', { hasText: P.legacy });
    await expect(legacy).toContainText('Not evaluated yet');
    await expect(legacy).toContainText('estimate unavailable');
    await expect(page.locator('#proj-body')).not.toContainText(/\b0\.00 USD/);
    await shot(page, 'projects-material-1440x900.png');
    expect(serious(await new AxeBuilder({ page }).include('#page-projects').analyze())).toEqual([]);
    await page.goto('/#/recent');
    await expect(page.locator('#recent-body table th', { hasText: 'Material' }).first()).toBeVisible({ timeout: 10_000 });
  });

  test('100 Run All Parts dialog names the catalog that will be used and links to change it', async ({ page }) => {
    await useSession(page, sid, P.ok, '#/projects');
    await page.evaluate(() => (window as any).McA.dom.dispatch('batch/request'));
    const dlg = page.locator('#dialog-root .dlg');
    // the run needs an API key; when absent the app explains instead of opening the dialog
    if (await dlg.count() === 0) { test.info().annotations.push({ type: 'note', description: 'no API key on the test server: dialog not reachable, covered by the unit test of runCatalogLine' }); return; }
    await expect(dlg.locator('#run-mat-line')).toContainText('Material library:');
    await expect(dlg.getByRole('button', { name: 'Change material library' })).toBeVisible();
    await page.keyboard.press('Escape');
  });

  test('101 viewer: the verified colour is applied only to the STL it was verified on; part switch and re-run drop it at once', async ({ page }) => {
    await useSession(page, sid, P.ok);
    const lg = page.locator('#stl-legend');
    await expect(lg).toHaveAttribute('data-state', 'verified', { timeout: 20_000 });
    await expect(lg).toContainText('Generic carbon steel');
    await expect(lg).toContainText('Illustrative appearance, not a finish specification');
    const toggle = page.locator('#stl-legend-grey');
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-pressed', 'true');
    await expect(lg).toContainText('default grey');
    await toggle.click();
    await shot(page, 'viewer-verified-appearance-1440x900.png');
    expect(serious(await new AxeBuilder({ page }).include('#vp-3d').analyze())).toEqual([]);
    // switch part: the old appearance is gone immediately, the new part is honestly unverified
    await page.evaluate(([s, p]) => (window as any).McA.openPart(s, p), [sid, P.nospec]);
    await expect(lg).toHaveAttribute('data-state', /checking|unverified/, { timeout: 20_000 });
    await expect(lg).not.toContainText('Generic carbon steel · Verified');
    await expect(lg).toContainText('Preview: material not verified', { timeout: 20_000 });
    await shot(page, 'viewer-unverified-preview-1440x900.png');
    // a re-run replaced the STL after the sidecar was written: the sidecar no longer matches, so no colour is applied
    replaceStl(P.ok);
    await page.evaluate(([s, p]) => (window as any).McA.openPart(s, p), [sid, P.ok]);
    await expect(lg).toContainText('Preview: material not verified', { timeout: 20_000 });
    await expect(lg).toContainText('different model file');
    await expect(toggle).toBeHidden();
  });

  test('102 layout: no overlaps, no sideways scroll, axe clean at every width, sidebar open and collapsed', async ({ page }) => {
    test.setTimeout(240_000);
    const bad: string[] = [];
    for (const [w, h] of SIZES) {
      for (const collapsed of [false, true]) {
        if (collapsed && w < 1100) continue;
        await page.setViewportSize({ width: w, height: h });
        await useSession(page, sid, P.ok);
        const tog = page.locator('#sb-toggle');
        if (await tog.isVisible().catch(() => false)) {
          const open = (await tog.getAttribute('aria-expanded')) === 'true';
          if (open === collapsed) { await tog.click(); await page.waitForTimeout(250); }
        }
        await page.waitForTimeout(900);
        for (const f of await auditLayout(page)) bad.push(`[${w}x${h}${collapsed ? ' rail' : ''}] workspace: ${fmt([f])[0]}`);
        if (w >= 1100) {
          await page.evaluate(() => { const b = document.getElementById('mat-lib-lbl'); if (b) b.scrollIntoView({ block: 'center' }); });
          if (!collapsed && (w === 1920 || w === 1100)) await shot(page, `workspace-material-${w}x${h}.png`);
        }
        await page.goto(`/#/results?run=${sid}|${P.ok}&sec=material`); await page.reload();
        await expect(page.locator('#res-pane [data-sec="material"]')).toBeVisible({ timeout: 15_000 });
        await page.waitForTimeout(600);
        for (const f of await auditLayout(page)) bad.push(`[${w}x${h}${collapsed ? ' rail' : ''}] results/material: ${fmt([f])[0]}`);
        expect(serious(await new AxeBuilder({ page }).analyze())).toEqual([]);
        if (!collapsed) await shot(page, `results-material-${w}x${h}.png`);
        await page.goto('/#/projects'); await page.reload(); await page.waitForTimeout(1200);
        for (const f of await auditLayout(page)) bad.push(`[${w}x${h}${collapsed ? ' rail' : ''}] projects: ${fmt([f])[0]}`);
      }
    }
    expect(summarise(bad)).toEqual([]);
  });
});
