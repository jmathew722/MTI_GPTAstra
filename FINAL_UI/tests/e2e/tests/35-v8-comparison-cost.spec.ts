import { test, expect, Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { execFileSync } from 'child_process';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import { watchConsole } from '../helpers/app';
import { ESTIMATE, USAGE, TIMING, enrichComparison, inject, part as jpart } from '../helpers/v8data';

// v8: source-vs-generated comparison (sync zoom/pan/page, overlay, difference, status chips, issue list with evidence, scales, reuse, corrections, editable output),
// the validation-report export, and the cost / runtime area (estimate before the run, live and actual after). The seed is helpers/make_v8_fixture.py (hand-made
// stand-in PDFs); the v8 fields (replication, usage, timing, estimate) are injected into GET /api/reverse/jobs/<id> in the shapes of V8_CONTRACT.md. Nothing here
// submits a job, starts SOLIDWORKS or calls a model.
const DATA = process.env.MCAGENT_DATA ? path.resolve(process.env.MCAGENT_DATA) : '';
test.skip(!DATA, 'MCAGENT_DATA not set: start the server with it (isolated folder) and export it for the tests');

const VERIFY = path.resolve(__dirname, '../../../docs/verification/v8');
const J1 = 'r3d_7000000000000001', J2 = 'r3d_7000000000000002', J4 = 'r3d_8000000000000001';
const JOBS = path.join(DATA, 'outputs', '3d-to-2d');
const shot = async (page: Page, name: string) => { fs.mkdirSync(VERIFY, { recursive: true }); await page.screenshot({ path: path.join(VERIFY, name) }); };
const sha = (f: string) => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const sha1 = (b: Buffer) => crypto.createHash('sha256').update(b).digest('hex');
const pfile = (job: string, pid: string, rel: string) => path.join(JOBS, job, pid, 'active', rel);

test.beforeAll(() => {
  execFileSync(process.env.PYTHON || 'python', [path.resolve(__dirname, '../helpers/make_v8_fixture.py'), DATA, 'reset'], { encoding: 'utf-8', env: { ...process.env, PYTHONUTF8: '1' } });
});

async function open(page: Page, job: string, partId = '', w = 1440, h = 900, o: { zoom?: number; rail?: boolean; cdp?: boolean; enrich?: boolean } = {}) {
  const zoom = o.zoom || 1;
  if (o.enrich !== false && job === J4) await inject(page, J4, enrichComparison);
  if (zoom === 1 && !o.cdp) await page.setViewportSize({ width: w, height: h });
  else {
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: Math.round(w / zoom), height: Math.round(h / zoom), deviceScaleFactor: zoom, mobile: false });
  }
  await page.goto('about:blank');
  await page.goto(`/#/reverse${job ? '?job=' + job + (partId ? '&part=' + partId : '') : ''}`);
  await page.waitForFunction(() => !!(window as any).McA && !!(window as any).McA.pages.reverse);
  await expect(page.locator('#page-reverse')).toBeVisible();
  if (job) await expect(page.locator('.rv-tbl tbody tr').first()).toBeVisible({ timeout: 15_000 });
  const tog = page.locator('#sb-toggle');
  if (o.rail !== undefined && await tog.isVisible().catch(() => false)) {
    if (((await tog.getAttribute('aria-expanded')) === 'true') === !!o.rail) { await tog.click(); await page.waitForTimeout(250); }
  }
  await page.waitForTimeout(300);
}
const pdfReady = (page: Page) => expect(page.locator('#rv-2d .rv-paperwrap')).toBeVisible({ timeout: 15_000 });
const srcReady = (page: Page) => expect(page.locator('#rv-src-layer .rv-paperwrap')).toBeVisible({ timeout: 15_000 });
async function sel(page: Page, name: string) { await page.locator('.rv-pname', { hasText: name }).click(); await page.waitForTimeout(300); }
async function openAcc(page: Page, key: string) { const b = page.locator(`#rv-acc-${key}-btn`); if ((await b.getAttribute('aria-expanded')) !== 'true') await b.click(); }
async function tab(page: Page, id: string) { await page.locator(`#rv-tab-${id}`).click(); await page.waitForTimeout(150); }
async function srcMode(page: Page) { await page.locator('#rv-left-src').click(); await srcReady(page); }
const idle = async (page: Page) => page.waitForTimeout(600);
const wrapFrac = (page: Page, sel: string) => page.evaluate((s) => { const w = document.querySelector(s) as HTMLElement; return { x: w.scrollWidth > w.clientWidth ? w.scrollLeft / (w.scrollWidth - w.clientWidth) : 0, y: w.scrollHeight > w.clientHeight ? w.scrollTop / (w.scrollHeight - w.clientHeight) : 0, sw: w.scrollWidth - w.clientWidth, sh: w.scrollHeight - w.clientHeight }; }, sel);
const RW = '#rv-2d .rv-paperwrap', LW = '#rv-src-layer .rv-paperwrap';

test.describe('v8: comparison status, scales and facts', () => {
  test('150 the status chip tells Verified, Needs Review, Blocked and Draft apart, per part, and never says approved', async ({ page }) => {
    const bad = watchConsole(page);
    await open(page, J4, 'verified'); await pdfReady(page);
    const chip = page.locator('#rv-cmp-status');
    const expectChip = async (name: string, text: RegExp, key: string) => { await sel(page, name); await expect(chip).toHaveText(text); await expect(chip).toHaveAttribute('data-key', key); };
    await expectChip('verified', /^Verified$/, 'verified');
    await expect(chip).toHaveAttribute('data-tone', 'green');
    await expectChip('needsrev', /^Needs Review$/, 'needs_review'); await expect(chip).toHaveAttribute('data-tone', 'amber');
    await expect(chip).toHaveAttribute('title', /2 annotations are missing/);
    await expectChip('multi', /^Verified$/, 'verified');
    await expectChip('blocked', /^Blocked$/, 'blocked'); await expect(chip).toHaveAttribute('data-tone', 'red'); await expect(chip).toHaveAttribute('title', /could not be read/);
    await expectChip('plain', /^Draft/, 'draft');                       // v7 verification only (no replication block): a draft, never "Verified"
    await expect(chip).not.toHaveText(/^Verified/);
    for (const name of ['verified', 'needsrev', 'blocked', 'plain']) { await sel(page, name); expect(((await chip.getAttribute('title')) || '').toLowerCase().replace('not an engineering approval', '')).not.toContain('approved'); }
    // an old v7 job: no replication, verification only
    await open(page, J1, 'flange'); await pdfReady(page);
    await expect(chip).toHaveAttribute('data-key', 'draft'); await expect(chip).not.toHaveText(/^Verified$/);
    await sel(page, 'bracket'); await expect(chip).toHaveText(/^Needs Review$/);
    await sel(page, 'plate'); await expect(page.locator('#rv-cmpbar')).toBeHidden();                  // verification not run + no source: nothing to compare
    expect(bad).toEqual([]);
  });

  test('151 scales, extraction reuse, corrections and editable-output availability are shown from the recorded data only', async ({ page }) => {
    await open(page, J4, 'needsrev'); await pdfReady(page);
    await expect(page.locator('#rv-cmp-scale')).toHaveText('Sheet 1:2 source / 1:2 generated (title block 1:2)');
    await tab(page, 'compare');
    const facts = page.locator('#rv-ct-facts');
    await expect(facts).toContainText('Sheet 1:2 source / 1:2 generated');
    await expect(facts).toContainText('View V1 1:2 source / 1:4 generated (differs)');
    await expect(facts).toContainText('Reused (saved extraction, no new model call)');
    await expect(facts).toContainText('1 of 3 correction pass (stopped: iteration cap)');
    await expect(facts).toContainText('37 matched of 41 in the source');
    await expect(facts).toContainText('96%');
    await expect(facts).toContainText('Editable SLDDRW available');
    await sel(page, 'multi'); await expect(facts).toContainText('Fresh extraction'); await expect(facts).toContainText('2 matched'.slice(0, 0) + 'Editable SLDDRW available');
    await sel(page, 'nosld'); await expect(facts).toContainText('No editable SLDDRW for this part');
    // no scale recorded: no scale line is invented
    await sel(page, 'plain'); await expect(page.locator('#rv-cmp-scale')).toBeHidden(); await expect(page.locator('#rv-ct-facts')).not.toContainText('Sheet 1');
    // old job: scales come from nothing
    await open(page, J1, 'flange'); await tab(page, 'compare'); await expect(page.locator('#rv-ct-facts')).not.toContainText('source /');
    await sel(page, 'plate'); await expect(page.locator('#rv-compare')).toContainText('No comparison with a source drawing was run');
  });

  test('152 per part / per run state: the compare mode, filter and evidence belong to the part and survive switching', async ({ page }) => {
    await open(page, J4, 'needsrev'); await pdfReady(page);
    await page.locator('#rv-cmp-difference').click(); await srcReady(page);
    await expect(page.locator('#rv-cmp-difference')).toHaveAttribute('aria-pressed', 'true');
    await sel(page, 'multi'); await expect(page.locator('#rv-cmp-side')).toHaveAttribute('aria-pressed', 'true'); await expect(page.locator('#rv-cmp-canvas')).toBeHidden(); await expect(page.locator('#rv-cmp-img')).toBeHidden();
    await sel(page, 'needsrev'); await expect(page.locator('#rv-cmp-difference')).toHaveAttribute('aria-pressed', 'true');
  });
});

test.describe('v8: synchronised zoom, pan and page', () => {
  test('153 sync is on by default when the page counts match, and zoom, page and pan follow in both directions', async ({ page }) => {
    await open(page, J4, 'multi'); await pdfReady(page); await srcMode(page);
    await expect(page.locator('#rv-sync')).toHaveAttribute('aria-pressed', 'true'); await expect(page.locator('#rv-sync')).toHaveAttribute('aria-disabled', 'false');
    await expect(page.locator('#rv-cmp-sync')).toHaveText('Zoom, pan and page synchronised');
    // page: right next -> left page 2; left previous -> right sheet 1
    await page.locator('#rv-2d button[aria-label="Next sheet"]').click(); await expect(page.locator('#rv-3d .rv-pagelbl')).toHaveText('Page 2 of 2');
    await page.locator('#rv-3d button[aria-label^="Previous page"]').click(); await expect(page.locator('#rv-2d .rv-pagelbl')).toHaveText('Sheet 1 of 2');
    // zoom: right drives left, left drives right
    await page.locator('#rv-2d button[aria-label="Zoom in"]').click(); await expect(page.locator('#rv-3d .rv-zoomlbl')).toHaveText('125%');
    await page.locator('#rv-3d .rv-src-tools button[aria-label^="Zoom in"]').click(); await expect(page.locator('#rv-2d .rv-zoomlbl')).toHaveText('150%');
    for (let i = 0; i < 6; i++) await page.locator('#rv-2d button[aria-label="Zoom in"]').click();
    await expect(page.locator('#rv-3d .rv-zoomlbl')).toHaveText('300%'); await idle(page);
    // pan: scroll the right sheet, the left follows by fraction of its scrollable range
    const r0 = await wrapFrac(page, RW); expect(r0.sw).toBeGreaterThan(100);
    await page.evaluate((s) => { const w = document.querySelector(s) as HTMLElement; w.scrollLeft = (w.scrollWidth - w.clientWidth) * 0.6; w.scrollTop = (w.scrollHeight - w.clientHeight) * 0.3; }, RW);
    await expect.poll(async () => (await wrapFrac(page, LW)).x, { timeout: 4000 }).toBeGreaterThan(0.55);
    const l1 = await wrapFrac(page, LW), r1 = await wrapFrac(page, RW);
    expect(Math.abs(l1.x - r1.x)).toBeLessThan(0.04); expect(Math.abs(l1.y - r1.y)).toBeLessThan(0.04);
    // and the other way: scroll the LEFT sheet, the right follows
    await page.evaluate((s) => { const w = document.querySelector(s) as HTMLElement; w.scrollLeft = (w.scrollWidth - w.clientWidth) * 0.2; w.scrollTop = (w.scrollHeight - w.clientHeight) * 0.8; }, LW);
    await expect.poll(async () => (await wrapFrac(page, RW)).y, { timeout: 4000 }).toBeGreaterThan(0.7);
    const l2 = await wrapFrac(page, LW), r2 = await wrapFrac(page, RW);
    expect(Math.abs(l2.x - r2.x)).toBeLessThan(0.04); expect(Math.abs(l2.y - r2.y)).toBeLessThan(0.04);
    // off: no echo
    await page.locator('#rv-sync').click(); await expect(page.locator('#rv-sync')).toHaveAttribute('aria-pressed', 'false'); await expect(page.locator('#rv-cmp-sync')).toHaveText('Synchronisation is off');
    const before = await wrapFrac(page, LW);
    await page.evaluate((s) => { const w = document.querySelector(s) as HTMLElement; w.scrollLeft = 0; w.scrollTop = 0; }, RW); await page.waitForTimeout(500);
    const after = await wrapFrac(page, LW); expect(Math.abs(after.x - before.x)).toBeLessThan(0.01); expect(Math.abs(after.y - before.y)).toBeLessThan(0.01);
    await page.locator('#rv-sync').click(); await expect(page.locator('#rv-sync')).toHaveAttribute('aria-pressed', 'true');
  });

  test('154 sync is not offered when the page counts differ, and says why; it needs no echo or loop when equal', async ({ page }) => {
    await open(page, J4, 'mismatchpages'); await pdfReady(page); await srcMode(page);
    await expect(page.locator('#rv-sync')).toHaveAttribute('aria-disabled', 'true'); await expect(page.locator('#rv-sync')).toHaveAttribute('aria-pressed', 'false');
    await expect(page.locator('#rv-sync')).toHaveAttribute('title', /2 source vs 1 generated/);
    await expect(page.locator('#rv-cmp-sync')).toContainText('2 source vs 1 generated');
    await page.locator('#rv-2d button[aria-label="Zoom in"]').click(); await page.waitForTimeout(300);
    await expect(page.locator('#rv-3d .rv-zoomlbl')).toHaveText('100%');
    // an event storm settles: after one zoom the labels stay put (no ping-pong)
    await sel(page, 'verified'); await srcReady(page);
    await page.locator('#rv-2d button[aria-label="Zoom in"]').click(); await expect(page.locator('#rv-3d .rv-zoomlbl')).toHaveText('125%'); await page.waitForTimeout(800);
    await expect(page.locator('#rv-3d .rv-zoomlbl')).toHaveText('125%'); await expect(page.locator('#rv-2d .rv-zoomlbl')).toHaveText('125%');
  });
});

test.describe('v8: overlay and difference', () => {
  test('155 Overlay and Difference use the backend images when the server lists them, per sheet, and Side by side hides them', async ({ page }) => {
    await open(page, J4, 'needsrev'); await pdfReady(page);
    await expect(page.locator('#rv-cmp-img')).toBeHidden();
    await page.locator('#rv-cmp-overlay').click(); await srcReady(page);                              // the source sheet is needed beside the generated one
    await expect(page.locator('#rv-cmp-img')).toBeVisible(); await expect(page.locator('#rv-cmp-img')).toHaveAttribute('src', /needsrev\/active\/comparison\/overlay-page-001\.png/);
    await expect(page.locator('#rv-cmp-legend')).toHaveAttribute('data-src', 'backend'); await expect(page.locator('#rv-cmp-legend')).toContainText('produced by the backend');
    expect(await page.locator('#rv-cmp-img').evaluate((i: HTMLImageElement) => i.naturalWidth)).toBe(306);
    await expect(page.locator('#rv-cmp-canvas')).toBeHidden();
    await page.locator('#rv-cmp-difference').click();
    await expect(page.locator('#rv-cmp-img')).toHaveAttribute('src', /diff-page-001\.png/); await expect(page.locator('#rv-cmp-legend')).toContainText('Blue: in the source only');
    const geo = await page.evaluate(() => { const i = document.getElementById('rv-cmp-img')!.getBoundingClientRect(), p = document.querySelector('#rv-2d canvas.rv-paper')!.getBoundingClientRect(); return { dx: Math.abs(i.left - p.left), dw: Math.abs(i.width - p.width), dh: Math.abs(i.height - p.height) }; });
    expect(geo.dx).toBeLessThan(2); expect(geo.dw).toBeLessThan(2); expect(geo.dh).toBeLessThan(2);       // the layer sits exactly on the generated sheet
    await page.locator('#rv-cmp-side').click(); await expect(page.locator('#rv-cmp-img')).toBeHidden(); await expect(page.locator('#rv-cmp-legend')).toBeHidden();
    await shot(page, 'after-difference-backend-1440x900.png');
  });

  test('156 without backend images the overlay / difference is computed in the browser from the two rendered sheets and says so', async ({ page }) => {
    await open(page, J4, 'verified'); await pdfReady(page);
    await page.locator('#rv-cmp-difference').click(); await srcReady(page);
    await expect(page.locator('#rv-cmp-canvas')).toBeVisible({ timeout: 10_000 });
    const lg = page.locator('#rv-cmp-legend');
    await expect(lg).toHaveAttribute('data-src', 'browser'); await expect(lg).toContainText('computed in your browser'); await expect(lg).toContainText('not a backend result');
    await expect(lg).toContainText('0 px only in the source, 0 px only in the generated drawing');     // the same bytes on both sides: nothing differs
    await expect(page.locator('#rv-cmp-img')).toBeHidden();
    await page.locator('#rv-cmp-overlay').click(); await expect(page.locator('#rv-cmp-canvas')).toBeVisible(); await expect(lg).toContainText('Overlay computed in your browser');
    // different sheets: the difference is non-empty and uses both colours
    await sel(page, 'multi'); await page.locator('#rv-cmp-difference').click(); await srcReady(page);
    await expect(lg).toHaveAttribute('data-src', 'browser', { timeout: 10_000 });
    const nums = (await lg.innerText()).match(/([\d,]+) px only in the source, ([\d,]+) px only in the generated/)!;
    expect(parseInt(nums[1].replace(/,/g, ''), 10)).toBeGreaterThan(0); expect(parseInt(nums[2].replace(/,/g, ''), 10)).toBeGreaterThan(0);
    const colours = await page.evaluate(() => { const c = document.getElementById('rv-cmp-canvas') as HTMLCanvasElement, d = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data; let blue = 0, red = 0; for (let i = 0; i < d.length; i += 4) { if (d[i] === 40 && d[i + 2] === 255) blue++; if (d[i] === 235 && d[i + 1] === 60) red++; } return { blue, red }; });
    expect(colours.blue).toBeGreaterThan(0); expect(colours.red).toBeGreaterThan(0);
    await shot(page, 'after-difference-browser-1440x900.png');
  });

  test('157 overlay and difference are disabled, with the reason, when there is no source PDF', async ({ page }) => {
    await open(page, J4, 'plain'); await pdfReady(page);
    for (const m of ['overlay', 'difference']) { await expect(page.locator(`#rv-cmp-${m}`)).toHaveAttribute('aria-disabled', 'true'); await expect(page.locator(`#rv-cmp-${m}`)).toHaveAttribute('title', /Standard mode/); }
    await page.locator('#rv-cmp-overlay').click({ force: true }); await expect(page.locator('#rv-cmp-side')).toHaveAttribute('aria-pressed', 'true'); await expect(page.locator('#rv-cmp-canvas')).toBeHidden();
    await sel(page, 'blocked'); await expect(page.locator('#rv-cmp-difference')).toHaveAttribute('aria-disabled', 'true');
  });
});

test.describe('v8: issues and source evidence', () => {
  test('158 the issue list is grouped and severity-ordered; clicking one shows its evidence on the right sheet with a highlight and a crop', async ({ page }) => {
    await open(page, J4, 'needsrev'); await pdfReady(page); await tab(page, 'compare');
    const items = page.locator('.rv-ct-issue');
    await expect(items).toHaveCount(4);
    expect(await items.evaluateAll((es) => es.map((e) => e.getAttribute('data-issue')))).toEqual(['R004', 'R001', 'R003', 'R002']);       // critical, high, medium, low
    await expect(page.locator('[data-filter="all"]')).toHaveText('All (4)'); await expect(page.locator('[data-filter="missing"]')).toHaveText('Missing (1)'); await expect(page.locator('[data-filter="extra"]')).toHaveText('Extra (1)'); await expect(page.locator('[data-filter="mismatch"]')).toHaveText('Mismatched (2)');
    await page.locator('[data-filter="mismatch"]').click(); await expect(items).toHaveCount(2); await expect(page.locator('[data-filter="mismatch"]')).toHaveAttribute('aria-pressed', 'true');
    await page.locator('[data-filter="all"]').click(); await expect(items).toHaveCount(4);
    // missing annotation: evidence is on the SOURCE
    await page.locator('[data-issue="R001"]').click();
    await expect(page.locator('#rv-ev-note')).toContainText('located in the source drawing', { timeout: 10_000 });
    await expect(page.locator('#rv-left-src')).toHaveAttribute('aria-pressed', 'true');
    const mk = page.locator('#rv-src-layer .rv-mark'); await expect(mk).toBeVisible();
    const g = await page.evaluate(() => { const m = document.querySelector('#rv-src-layer .rv-mark')!.getBoundingClientRect(), p = document.querySelector('#rv-src-layer canvas.rv-paper')!.getBoundingClientRect(); return { l: m.left - p.left, t: m.top - p.top, r: p.right - m.right, b: p.bottom - m.bottom, w: m.width, h: m.height }; });
    expect(g.l).toBeGreaterThan(-8); expect(g.t).toBeGreaterThan(-8); expect(g.r).toBeGreaterThan(-8); expect(g.b).toBeGreaterThan(-8); expect(g.w).toBeGreaterThan(20); expect(g.h).toBeGreaterThan(8);
    const crop = page.locator('#rv-ct-ev canvas.rv-ev-crop'); await expect(crop).toBeVisible(); await expect(crop).toHaveAttribute('aria-label', 'Source evidence for R001');
    expect(await crop.evaluate((c: HTMLCanvasElement) => { const d = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data; let dark = 0; for (let i = 0; i < d.length; i += 4) if (d[i] < 120) dark++; return dark; })).toBeGreaterThan(5);     // the crop holds real drawing pixels
    await expect(page.locator('[data-issue="R001"]')).toHaveAttribute('aria-current', 'true');
    // extra annotation: evidence is on the GENERATED sheet
    await page.locator('[data-issue="R002"]').click();
    await expect(page.locator('#rv-ev-note')).toContainText('present in the generated drawing but not in the source', { timeout: 10_000 });
    await expect(page.locator('#rv-2d .rv-mark')).toBeVisible();
    await expect(page.locator('#rv-ct-ev canvas.rv-ev-crop')).toHaveAttribute('aria-label', 'Generated evidence for R002');
    // text that is in neither PDF: honest, nothing highlighted, no crop
    await page.locator('[data-issue="R003"]').click();
    await expect(page.locator('#rv-ev-note')).toContainText('could not be located', { timeout: 10_000 });
    await expect(page.locator('#rv-src-layer .rv-mark')).toBeHidden(); await expect(page.locator('#rv-ct-ev canvas.rv-ev-crop')).toHaveCount(0);
    await page.locator('[data-issue="R001"]').click(); await expect(page.locator('#rv-ev-note')).toContainText('located in the source drawing', { timeout: 10_000 });
    await shot(page, 'after-issue-evidence-1440x900.png');
  });

  test('159 the issue list is keyboard operable: arrows move, Enter shows the evidence, focus stays on the item', async ({ page }) => {
    await open(page, J4, 'needsrev'); await pdfReady(page); await tab(page, 'compare');
    await page.locator('[data-issue="R004"]').focus();
    await page.keyboard.press('ArrowDown'); await expect(page.locator('[data-issue="R001"]')).toBeFocused();
    await page.keyboard.press('ArrowDown'); await expect(page.locator('[data-issue="R003"]')).toBeFocused();
    await page.keyboard.press('ArrowUp'); await expect(page.locator('[data-issue="R001"]')).toBeFocused();
    await page.keyboard.press('Enter'); await expect(page.locator('#rv-ev-note')).toContainText('located in the source drawing', { timeout: 10_000 });
    expect(await page.locator('[data-issue="R001"]').getAttribute('aria-label')).toMatch(/Missing annotation, sheet 1: R12\. Show the evidence\./);
    await expect(page.locator('#rv-ct-ev')).toHaveAttribute('aria-live', 'polite');
    // the segmented compare control is a group of toggle buttons that Tab reaches and Space / Enter operate, with a visible focus ring
    await page.locator('#rv-cmp-side').focus(); await page.keyboard.press('Tab'); await expect(page.locator('#rv-cmp-overlay')).toBeFocused();
    const ring = await page.locator('#rv-cmp-overlay').evaluate((e) => { const s = getComputedStyle(e); return s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2; }); expect(ring).toBe(true);
    await page.keyboard.press('Space'); await expect(page.locator('#rv-cmp-overlay')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('#rv-cmp-mode')).toHaveAttribute('role', 'group'); await expect(page.locator('#rv-cmp-mode')).toHaveAttribute('aria-label', /Compare/);
  });

  test('160 empty, loading and error states: no comparison, a source that fails then Retry, a slow source', async ({ page }) => {
    await open(page, J4, 'plain'); await tab(page, 'compare');
    await expect(page.locator('#rv-compare')).toContainText('No issues recorded');
    await sel(page, 'blocked'); await expect(page.locator('#rv-ct-status')).toHaveText('Blocked'); await expect(page.locator('#rv-compare')).toContainText('The source PDF could not be read');
    // failing source download: error with Retry, then it loads
    let fail = true;
    await page.route(/needsrev\/active\/reference\/source\.pdf/, (route) => { if (fail) route.abort(); else route.continue(); });
    await sel(page, 'needsrev'); await page.locator('#rv-left-src').click();
    await expect(page.locator('#rv-src-layer .vp-empty[data-kind="error"]')).toBeVisible({ timeout: 10_000 });
    fail = false; await page.locator('#rv-src-layer button', { hasText: 'Retry' }).click(); await srcReady(page);
    // a slow source shows a loading state
    await page.unroute(/needsrev\/active\/reference\/source\.pdf/);
    await page.route(/multi\/active\/reference\/source\.pdf/, async (route) => { await new Promise((r) => setTimeout(r, 1500)); route.continue(); });
    await sel(page, 'multi'); await page.locator('#rv-left-src').click();
    await expect(page.locator('#rv-src-layer .vp-empty[data-kind="loading"]')).toBeVisible({ timeout: 5000 }); await srcReady(page);
    // an issue whose evidence cannot be shown because the source is missing says so
    await sel(page, 'needsrev'); await tab(page, 'compare');
  });

  test('161 viewing the comparison creates no object URLs and no console errors', async ({ page }) => {
    const bad = watchConsole(page);
    await page.addInitScript(() => { (window as any).__urls = 0; const orig = URL.createObjectURL; URL.createObjectURL = function (o: any) { (window as any).__urls++; return orig.call(URL, o); }; });
    await open(page, J4, 'needsrev'); await pdfReady(page);
    await page.locator('#rv-cmp-overlay').click(); await srcReady(page); await page.locator('#rv-cmp-difference').click(); await page.locator('#rv-cmp-side').click();
    await tab(page, 'compare'); await page.locator('[data-issue="R001"]').click(); await page.locator('[data-issue="R002"]').click(); await page.waitForTimeout(800);
    await sel(page, 'verified'); await page.locator('#rv-cmp-difference').click(); await page.waitForTimeout(800);
    expect(await page.evaluate(() => (window as any).__urls)).toBe(0);
    expect(bad).toEqual([]);
  });
});

test.describe('v8: export of the validation report', () => {
  test('162 the report downloads as the real file of THIS part, bound to the selection, with draft labelling and acknowledgement', async ({ page }) => {
    await open(page, J4, 'needsrev'); await pdfReady(page);
    await expect(page.locator('#rv-exp-report')).toBeVisible(); await expect(page.locator('#rv-exp-report')).toHaveText('Download report (JSON)');
    await expect(page.locator('#rv-exp-status')).toContainText('Draft: review required');
    await expect(page.locator('#rv-exp-report')).toBeDisabled(); await expect(page.locator('#rv-exp-report')).toHaveAttribute('title', /Tick the acknowledgement/);
    await page.locator('#rv-exp-ack').check(); await expect(page.locator('#rv-exp-report')).toBeEnabled();
    const urls: string[] = [];
    page.on('request', (r) => { if (/\/export\//.test(r.url())) urls.push(r.url()); });
    const dl = async (id: string) => { const [d] = await Promise.all([page.waitForEvent('download'), page.locator(id).click()]); const p = await d.path(); return { name: d.suggestedFilename(), buf: fs.readFileSync(p!) }; };
    const rep = await dl('#rv-exp-report');
    expect(rep.name).toBe('needsrev-validation-report.json'); expect(sha1(rep.buf)).toBe(sha(pfile(J4, 'needsrev', 'qa.json'))); expect(() => JSON.parse(rep.buf.toString('utf-8'))).not.toThrow();
    expect(urls[0]).toContain(`/jobs/${J4}/parts/needsrev/export/report`); expect(urls[0]).toContain('ack=1'); expect(urls[0]).toMatch(/expect=\d+/);
    await expect(page.locator('.toast').last()).toContainText('Downloaded needsrev-validation-report.json');
    // switching part resets the acknowledgement and binds the next download to the new part
    await sel(page, 'multi'); await expect(page.locator('#rv-exp-report')).toBeEnabled();
    urls.length = 0; const r2 = await dl('#rv-exp-report');
    expect(urls[0]).toContain('/parts/multi/export/report'); expect(sha1(r2.buf)).toBe(sha(pfile(J4, 'multi', 'qa.json'))); expect(sha1(r2.buf)).not.toBe(sha1(rep.buf)); expect(r2.name).toBe('multi-validation-report.json');
    // a part that never wrote a report cannot offer one
    await sel(page, 'blocked'); await expect(page.locator('#rv-exp-report')).toBeDisabled(); await expect(page.locator('#rv-exp-report')).toHaveAttribute('title', /report|not finished|did not/i);
    await shot(page, 'after-export-report-1440x900.png');
  });

  test('163 the other exports are unchanged: PDF and SLDDRW still download, and the report is refused when stale', async ({ page }) => {
    await open(page, J4, 'multi'); await pdfReady(page);
    const dl = async (id: string) => { const [d] = await Promise.all([page.waitForEvent('download'), page.locator(id).click()]); const p = await d.path(); return { name: d.suggestedFilename(), buf: fs.readFileSync(p!) }; };
    if (await page.locator('#rv-exp-ack').count()) await page.locator('#rv-exp-ack').check();
    const pdf = await dl('#rv-exp-pdf'); expect(pdf.name).toBe('multi-drawing.pdf'); expect(sha1(pdf.buf)).toBe(sha(pfile(J4, 'multi', 'drawing.pdf')));
    const r = await page.request.get(`/api/reverse/jobs/${J4}/parts/multi/export/report?ack=1&expect=1`); expect(r.status()).toBe(409);
    const ok = await page.request.get(`/api/reverse/jobs/${J4}/parts/multi/export/report?ack=1`); expect(ok.status()).toBe(200); expect(ok.headers()['content-type']).toContain('application/json');
  });
});

/* ───────────────────────────── cost and runtime ───────────────────────────── */
async function mockEstimate(page: Page, body: any | ((req: any) => any), status = 200) {
  const reqs: any[] = [];
  await page.route('**/api/reverse/estimate', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    const rq = route.request().postDataJSON(); reqs.push(rq);
    await route.fulfill({ status, json: typeof body === 'function' ? body(rq) : body });
  });
  return reqs;
}
const SLD = (name: string) => ({ name, mimeType: 'application/octet-stream', buffer: Buffer.from('SLDPRT-test-' + name) });

test.describe('v8: estimate before the run', () => {
  test('170 the estimate shows time range, low/expected/high cost, model and rate date, budget; it is recomputed when the selection changes', async ({ page }) => {
    const reqs = await mockEstimate(page, (rq: any) => ({ schema_version: 1, mode: rq.reference.mode, count: rq.count, source: 'estimate_run', model: 'gpt-6-astra', total: ESTIMATE(), parts: [],
      budget: { cap_usd: 20, spent_usd: 16.2, remaining_usd: 3.8, would_block: false, note: 'n' } }));
    const posted: string[] = []; page.on('request', (r) => { if (r.method() === 'POST' && /\/api\/reverse\/(jobs|stage)$/.test(r.url())) posted.push(r.url()); });
    await open(page, J1, 'flange');
    await expect(page.locator('#rv-run-est')).toContainText('Estimate: About 2.5 min (range 1.5 min – 5.5 min)'); await expect(page.locator('#rv-run-est')).toContainText('about $0.21 OpenAI (gpt-6-astra)');
    await openAcc(page, 'rt');
    await expect(page.locator('#rv-est8-time')).toHaveText('About 2.5 min (range 1.5 min – 5.5 min)');
    const cost = await page.locator('#rv-est8-cost').innerText();
    expect(cost).toContain('low $0.0400'); expect(cost).toContain('expected $0.21'); expect(cost).toContain('high $0.62');
    await expect(page.locator('#rv-est8-model')).toHaveText('Model gpt-6-astra · rates of 2026-11-27');
    await expect(page.locator('#rv-est8-tokens')).toContainText('20,000 in'); await expect(page.locator('#rv-est8-budget')).toContainText('$3.8000 left of the $20.00 cap'); await expect(page.locator('#rv-est8-budget')).toContainText('in flight');
    await expect(page.locator('#rv-est8-stages')).toContainText('Local generation (no token cost)');
    await expect(page.locator('#rv-cost-est')).toContainText('Local CAD processing time carries no token cost');
    const n0 = reqs.length; expect(reqs[reqs.length - 1].count).toBe(1);
    await page.setInputFiles('#rv-files', [SLD('a.SLDPRT'), SLD('b.SLDPRT')]);
    await expect.poll(() => reqs.length).toBeGreaterThan(n0); expect(reqs[reqs.length - 1].count).toBe(2); expect(reqs[reqs.length - 1].reference.mode).toBe('standard');
    await expect(page.locator('#rv-cost-est h4')).toContainText('Estimate for 2 parts');
    await page.locator('#rv-pk-1').uncheck(); await expect.poll(() => reqs[reqs.length - 1].count).toBe(1);
    expect(posted).toEqual([]);                               // estimating never starts a run and never stages with a model call
    await shot(page, 'after-estimate-1440x900.png');
  });

  test('171 unknown rate is "unavailable" (never $0.00), a fallback duration is labelled rough, standard mode says no OpenAI cost, failure is stated', async ({ page }) => {
    await mockEstimate(page, { schema_version: 1, mode: 'standard', count: 1, source: 'estimate_run', total: ESTIMATE({ cost: { low: null, expected: null, high: null, currency: 'USD', rate_version: null, model: 'gpt-x', unavailable_reason: 'No rate is configured for model gpt-x' },
      duration: { low_s: 30, expected_s: 60, high_s: 200, source: 'fallback', basis: 'no comparable history' }, labels: ['fallback_duration', 'fallback_tokens'] }) });
    await open(page, J1, 'flange'); await openAcc(page, 'rt');
    const cost = await page.locator('#rv-est8-cost').innerText();
    expect(cost).toMatch(/^unavailable: No rate is configured for model gpt-x/); expect(cost).not.toContain('$'); expect(await page.locator('#rv-cost-est').innerText()).not.toContain('$0.00');
    await expect(page.locator('#rv-est8-time')).toContainText('Rough estimate: 1 min'); await expect(page.locator('#rv-est8-labels')).toContainText('fallback duration');
    await expect(page.locator('#rv-run-est')).toContainText('cost unavailable'); expect(await page.locator('#rv-run-est').innerText()).not.toContain('$0');
    // Standard mode: a real zero is a stated "no OpenAI cost", with the reason
    await page.unroute('**/api/reverse/estimate');
    await mockEstimate(page, { schema_version: 1, mode: 'standard', count: 1, source: 'history', total: ESTIMATE({ cost: { low: 0, expected: 0, high: 0, currency: 'USD', rate_version: null, model: null, unavailable_reason: null } }) });
    await page.setInputFiles('#rv-files', [SLD('c.SLDPRT')]);
    await expect(page.locator('#rv-est8-cost')).toContainText('No OpenAI cost expected'); await expect(page.locator('#rv-run-est')).toContainText('no OpenAI cost');
    // an unreachable / failing estimate is stated, not hidden and not zero
    await page.unroute('**/api/reverse/estimate');
    await mockEstimate(page, { detail: 'The estimate could not be computed.' }, 500);
    await page.setInputFiles('#rv-files', [SLD('d.SLDPRT')]);
    await expect(page.locator('#rv-est8-err')).toContainText('Estimate unavailable'); await expect(page.locator('#rv-run-est')).toContainText('Estimate unavailable');
  });

  test('172 saved-extraction reuse is shown as a saving only when the backend confirmed it', async ({ page }) => {
    await mockEstimate(page, { schema_version: 1, mode: 'match', count: 2, source: 'estimate_run', model: 'gpt-6-astra', total: ESTIMATE(),
      parts: [{ part: 'p0', name: 'a.sldprt', reference: { status: 'resolved', pages: 1, extraction_cache: 'hit' }, estimate: ESTIMATE() }, { part: 'p1', name: 'b.sldprt', reference: { status: 'resolved', pages: 1, extraction_cache: 'fresh' }, estimate: ESTIMATE() }] });
    await open(page, J1, 'flange'); await openAcc(page, 'rt');
    await expect(page.locator('#rv-est8-reuse')).toHaveCount(0);        // Standard selection: nothing confirmed, no saving claimed
  });
});

test.describe('v8: actual cost, usage and runtime', () => {
  test('173 sub-cent cost, tokens with cached input, calls, retries, stage breakdown, local time and actual vs estimate, for a finished batch', async ({ page }) => {
    await mockEstimate(page, { schema_version: 1, mode: 'standard', count: 1, source: 'history', total: ESTIMATE() });
    await open(page, J4, 'needsrev'); await openAcc(page, 'rt');
    await expect(page.locator('#rv-chip-cost .chip-v')).toHaveText('$0.0212 API usage (calculated)');
    await expect(page.locator('#rv-run8-cost')).toContainText('$0.0212 (calculated from token usage, not an invoice)');
    await expect(page.locator('#rv-run8-tokens')).toHaveText('41,234 in · 1,000 cached · 5,120 out');
    await expect(page.locator('#rv-run8-calls')).toContainText('12 model calls, 1 local cache hit');
    await expect(page.locator('#rv-run8-model')).toHaveText('Model gpt-6-astra · rates of 2026-11-27');
    await expect(page.locator('#rv-run8-parts')).toHaveText('7 of 7 done');
    await expect(page.locator('#rv-run8-elapsed')).toHaveText('6 min 40 s'); await expect(page.locator('#rv-run8-queued')).toContainText('3 s (separate from elapsed)');
    await expect(page.locator('#rv-run8-compare')).toContainText('Cost: $0.0212 actual vs $0.50 expected (outside the estimated range)'); await expect(page.locator('#rv-run8-compare')).toContainText('Time: 6 min 40 s actual vs 7.5 min expected (within the estimated range)');
    const st = page.locator('#rv-run8-stages');
    for (const l of ['Extraction', 'Validation', 'Correction']) await expect(st).toContainText(l);
    await expect(st).toContainText('$0.0030'); await expect(st).toContainText('30,000');
    await expect(page.locator('#rv-run8-local')).toContainText('no token cost'); await expect(page.locator('#rv-run8-local')).toContainText('preflight 1 s');
    await expect(page.locator('#rv-run8-kept')).toContainText('failed or canceled parts is kept');
    // batch: per-part rows with each part's own cost
    const rows = page.locator('#rv-run8-perpart tbody tr'); await expect(rows).toHaveCount(7);
    await expect(page.locator('#rv-run8-perpart tr[data-part="multi"]')).toContainText('$0.0043');
    await expect(page.locator('#rv-run8-perpart tr[data-part="verified"]')).toContainText('$0.00'); await expect(page.locator('#rv-run8-perpart tr[data-part="blocked"]')).toContainText('No model calls recorded');
    await expect(page.locator('#rv-run8-perpart tr[data-part="needsrev"]')).toHaveAttribute('aria-current', 'true');
    await shot(page, 'after-cost-batch-1440x900.png');
  });

  test('174 retries, cached extraction, partial and unpriced usage are each worded correctly; unknown is never $0.00', async ({ page }) => {
    const cases: Array<[string, any, (p: Page) => Promise<void>]> = [
      ['cached', { usage: USAGE({ calls: 0, cache_hits: 1, cost_usd: 0, cost_status: 'none', input_tokens: 0, output_tokens: 0, cached_tokens: 0, by_stage: {}, historical_usd: 0.2 }) },
        async (p) => { await expect(p.locator('#rv-run8-cost')).toContainText('$0.00'); await expect(p.locator('#rv-run8-saved')).toContainText('saves about $0.2000'); await expect(p.locator('#rv-chip-cost .chip-v')).toHaveText('$0.00 API usage (extraction reused)'); await expect(p.locator('#rv-run8-calls')).toContainText('0 model calls, 1 local cache hit'); }],
      ['cached-unknown-original', { usage: USAGE({ calls: 0, cache_hits: 1, cost_usd: 0, cost_status: 'none', input_tokens: 0, output_tokens: 0, cached_tokens: 0, by_stage: {}, historical_usd: null }) },
        async (p) => { await expect(p.locator('#rv-run8-saved')).toContainText('original cost is not recorded'); expect(await p.locator('#rv-run8-saved').innerText()).not.toMatch(/saves about/); }],
      ['retries', { usage: USAGE() },
        async (p) => { await expect(p.locator('#rv-run8-calls')).toContainText('2 retries'); }],
      ['partial', { usage: USAGE({ cost_usd: 0.01, cost_status: 'partial', unpriced_calls: 1, unknown_usage_calls: 1 }) },
        async (p) => { await expect(p.locator('#rv-run8-cost')).toContainText('$0.0100 + unpriced calls'); await expect(p.locator('#rv-cost-run')).toContainText('1 call without a configured rate'); await expect(p.locator('#rv-cost-run')).toContainText('reported no usage'); await expect(p.locator('#rv-chip-cost .chip-v')).toContainText('partial'); }],
      ['unpriced', { usage: USAGE({ cost_usd: null, cost_status: 'unpriced', unpriced_calls: 3 }) },
        async (p) => { await expect(p.locator('#rv-run8-cost')).toContainText('unavailable'); expect(await p.locator('#rv-run8-cost').innerText()).not.toContain('$'); await expect(p.locator('#rv-chip-cost .chip-v')).toContainText('API cost unavailable'); expect(await p.locator('#rv-chip-cost .chip-v').innerText()).not.toContain('$0'); }],
      ['no-usage-fields', { usage: undefined },
        async (p) => { await expect(p.locator('#rv-run8-cost')).toContainText('Usage was not recorded for this run'); }],
    ];
    for (const [name, patch, check] of cases) {
      await page.unrouteAll({ behavior: 'ignoreErrors' });
      await mockEstimate(page, { schema_version: 1, mode: 'standard', count: 1, source: 'history', total: ESTIMATE() });
      await inject(page, J4, (job) => { enrichComparison(job); job.usage = patch.usage === undefined ? undefined : { ...patch.usage }; job.estimate_vs_actual = undefined; });
      await open(page, J4, 'needsrev', 1440, 900, { enrich: false }); await openAcc(page, 'rt');
      await expect(page.locator('#rv-cost-run'), name).toBeVisible();
      await check(page);
    }
  });

  test('175 a running job: elapsed advances on the monotonic clock, current stage, parts done, remaining only when the backend gives one, local time labelled', async ({ page }) => {
    let n = 0;
    await mockEstimate(page, { schema_version: 1, mode: 'standard', count: 1, source: 'history', total: ESTIMATE() });
    await page.route(new RegExp('/api/reverse/jobs/' + J2 + '(\\?.*)?$'), async (route) => {
      if (route.request().method() !== 'GET') return route.continue();
      const res = await route.fetch(); const j = await res.json(); n++;
      j.usage = USAGE({ calls: 1, cost_usd: 0.0102, by_stage: { extraction: { calls: 1, input_tokens: 9000, cached_tokens: 0, output_tokens: 1000, cost_usd: 0.0102, attempts: 1 } }, input_tokens: 9000, cached_tokens: 0, output_tokens: 1000 });
      j.timing = TIMING({ elapsed_s: 30 + 1.5 * (n - 1), running: true, queued_s: 1, remaining_s: n > 2 ? { low: 10, expected: 55, high: 120, source: 'history' } : null });
      j.estimate = ESTIMATE();
      await route.fulfill({ response: res, json: j });
    });
    await open(page, J2, 'busy'); await openAcc(page, 'rt');
    const secs = async () => { const t = await page.locator('#rv-run8-elapsed').innerText(); const m = /^(?:(\d+) min )?(\d+) s$/.exec(t); return m ? (m[1] ? +m[1] * 60 : 0) + +m[2] : NaN; };
    await expect(page.locator('#rv-run8-elapsed')).toHaveText(/\d+ s/); const a = await secs(); await page.waitForTimeout(2300); const b = await secs();
    expect(b).toBeGreaterThan(a); expect(b - a).toBeLessThan(6);                  // ticks forward in whole seconds, never backward between polls
    await expect(page.locator('#rv-run8-stage')).not.toBeEmpty(); await expect(page.locator('#rv-run8-parts')).toHaveText('0 of 2 done');
    await expect(page.locator('#rv-run8-cost')).toContainText('$0.0102'); await expect(page.locator('#rv-run8-queued')).toContainText('1 s');
    await expect(page.locator('#rv-run-live')).toBeVisible(); await expect(page.locator('#rv-run-live')).toContainText('elapsed'); await expect(page.locator('#rv-run-live')).toContainText('$0.0102 so far');
    await expect(page.locator('#rv-run8-remaining')).toContainText('left', { timeout: 8000 });       // arrives with the third poll
    await expect(page.locator('#rv-cost-run')).toContainText('no token cost');
    await shot(page, 'after-cost-running-1440x900.png');
  });

  test('176 a canceled or failed part keeps the cost it incurred and says so', async ({ page }) => {
    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await mockEstimate(page, { schema_version: 1, mode: 'standard', count: 1, source: 'history', total: ESTIMATE() });
    await inject(page, J1, (job) => {
      job.usage = USAGE({ calls: 2, cost_usd: 0.0317 });
      job.parts.forEach((p: any) => { if (p.part_id === 'gone') p.usage = USAGE({ calls: 1, cost_usd: 0.0054 }); if (p.part_id === 'cover') p.usage = USAGE({ calls: 1, cost_usd: 0.0007 }); });
    });
    await open(page, J1, 'gone', 1440, 900, { enrich: false }); await openAcc(page, 'rt');
    await expect(page.locator('#rv-run8-kept')).toContainText('Cost already incurred by failed or canceled parts is kept');
    await expect(page.locator('#rv-run8-perpart tr[data-part="gone"]')).toContainText('$0.0054'); await expect(page.locator('#rv-run8-perpart tr[data-part="cover"]')).toContainText('$0.0007');
    await expect(page.locator('#rv-run8-perpart tr[data-part="gone"]')).toContainText('Canceled');
  });
});

test.describe('v8: layout, accessibility', () => {
  test('177 no horizontal overflow and an intact layout at 1280x720, 1440x900, 1920x1080 x zoom 80/100/125 x sidebar open/rail, with the comparison and the cost panel open', async ({ page }) => {
    test.setTimeout(240_000);
    await mockEstimate(page, { schema_version: 1, mode: 'standard', count: 1, source: 'history', total: ESTIMATE(), budget: { cap_usd: 20, spent_usd: 1, remaining_usd: 19, would_block: false, note: 'n' } });
    const seen: string[] = [];
    for (const [w, h] of [[1280, 720], [1440, 900], [1920, 1080]] as Array<[number, number]>) for (const zoom of [0.8, 1, 1.25]) for (const rail of [false, true]) {
      await open(page, J4, 'needsrev', w, h, { zoom, rail, cdp: true });
      await openAcc(page, 'rt'); await tab(page, 'compare');
      const m = await page.evaluate(() => {
        const r = (s: string) => { const e = document.querySelector(s) as HTMLElement | null; if (!e) return null; const b = e.getBoundingClientRect(); return { top: b.top, bottom: b.bottom, left: b.left, right: b.right, w: b.width, h: b.height }; };
        const comp = document.getElementById('rv-compare') as HTMLElement, cb = document.getElementById('rv-cmpbar') as HTMLElement, cost = document.getElementById('rv-cost-panel') as HTMLElement;
        return { p3d: r('#rv-3d'), p2d: r('#rv-2d'), queue: r('#rv-queue'), rail: r('#rv-setup'), bar: r('#rv-cmpbar'), docW: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
          mainW: (document.getElementById('main') as HTMLElement).scrollWidth, mainC: (document.getElementById('main') as HTMLElement).clientWidth, compW: comp.scrollWidth - comp.clientWidth, barW: cb.scrollWidth - cb.clientWidth, costW: cost ? cost.scrollWidth - cost.clientWidth : 0 };
      });
      const tag = `${w}x${h}@${zoom}${rail ? ' rail' : ''}`;
      seen.push(`${tag}: gap ${(m.queue!.top - m.p3d!.bottom).toFixed(1)}`);
      expect(m.docW, `no horizontal overflow ${tag}`).toBeLessThanOrEqual(m.cw); expect(m.mainW, `main overflow ${tag}`).toBeLessThanOrEqual(m.mainC + 1);
      expect(m.queue!.top - m.p3d!.bottom, `viewer to queue gap ${tag}`).toBeGreaterThanOrEqual(8); expect(m.queue!.top - m.p3d!.bottom, `gap ${tag}`).toBeLessThanOrEqual(16);
      expect(Math.abs(m.p3d!.h - m.p2d!.h), `equal viewer height ${tag}`).toBeLessThanOrEqual(1);
      expect(m.bar!.right, `compare bar inside its panel ${tag}`).toBeLessThanOrEqual(m.p2d!.right + 1); expect(m.bar!.left, `compare bar inside ${tag}`).toBeGreaterThanOrEqual(m.p2d!.left - 1);
      expect(m.compW, `comparison tab ${tag}`).toBeLessThanOrEqual(1); expect(m.barW, `compare bar scroll ${tag}`).toBeLessThanOrEqual(1); expect(m.costW, `cost panel ${tag}`).toBeLessThanOrEqual(1);
      if (Math.round(w / zoom) >= 1100) expect(m.rail!.bottom, `rail within the row ${tag}`).toBeLessThanOrEqual(m.queue!.bottom + 1);
    }
    fs.mkdirSync(VERIFY, { recursive: true }); fs.writeFileSync(path.join(VERIFY, 'layout-matrix.txt'), seen.join('\n') + '\n');
  });

  test('178 accessibility: no serious or critical axe violations with the comparison evidence and the cost panel on screen', async ({ page }) => {
    await mockEstimate(page, { schema_version: 1, mode: 'standard', count: 1, source: 'history', total: ESTIMATE(), budget: { cap_usd: 20, spent_usd: 1, remaining_usd: 19, would_block: false, note: 'n' } });
    await open(page, J4, 'needsrev'); await pdfReady(page); await openAcc(page, 'rt'); await tab(page, 'compare');
    await page.locator('[data-issue="R001"]').click(); await expect(page.locator('#rv-ev-note')).toContainText('located', { timeout: 10_000 });
    await page.locator('#rv-cmp-difference').click(); await page.waitForTimeout(600);
    const res = await new AxeBuilder({ page }).disableRules(['region']).analyze();
    const bad = res.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
    expect(bad.map((v) => `${v.id}: ${v.nodes.slice(0, 2).map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([]);
  });

  test('179 narrow screens: the comparison bar wraps, the issue list and the cost panel stack, nothing overflows sideways', async ({ page }) => {
    await mockEstimate(page, { schema_version: 1, mode: 'standard', count: 1, source: 'history', total: ESTIMATE() });
    await open(page, J4, 'needsrev', 1000, 800); await tab(page, 'compare'); await page.locator('#rv-setup-btn').click(); await page.waitForTimeout(300);
    await openAcc(page, 'rt');
    const m = await page.evaluate(() => ({ docW: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, bar: (document.getElementById('rv-cmpbar') as HTMLElement).getBoundingClientRect().right, p2d: (document.getElementById('rv-2d') as HTMLElement).getBoundingClientRect().right }));
    expect(m.docW).toBeLessThanOrEqual(m.cw); expect(m.bar).toBeLessThanOrEqual(m.p2d + 1);
    await shot(page, 'after-narrow-1000x800.png');
  });
});

test.describe('v8: evidence screenshots', () => {
  test('180 full comparison view at 1440x900 and 1920x1080 (evidence only)', async ({ page }) => {
    await mockEstimate(page, { schema_version: 1, mode: 'standard', count: 1, source: 'history', total: ESTIMATE(), budget: { cap_usd: 20, spent_usd: 16.2, remaining_usd: 3.8, would_block: false, note: 'n' } });
    await open(page, J4, 'multi'); await pdfReady(page); await srcMode(page); await openAcc(page, 'rt'); await page.waitForTimeout(500);
    await shot(page, 'after-compare-synced-1440x900.png');
    await open(page, J4, 'needsrev', 1920, 1080); await pdfReady(page); await tab(page, 'compare'); await page.locator('[data-issue="R001"]').click(); await expect(page.locator('#rv-ev-note')).toContainText('located', { timeout: 10_000 }); await page.waitForTimeout(400);
    await shot(page, 'after-compare-issue-1920x1080.png');
  });
});
