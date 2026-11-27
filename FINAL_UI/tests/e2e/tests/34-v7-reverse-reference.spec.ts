import { test, expect, Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { execFileSync } from 'child_process';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import { watchConsole } from '../helpers/app';

// v7 3D -> 2D: setup rail (accordions, reference drawing, runtime & cost, run, export), left viewer toggle (3D Model | Source PDF), vertical layout
// (viewers, then the batch queue directly under them), export downloads. Asserts COMPUTED boxes; zoom is emulated with CDP device metrics
// (CSS viewport = size / zoom, deviceScaleFactor = zoom). The seed is helpers/make_v7_fixture.py (copies of a real generated run + labelled test
// PDFs; see its docstring). No test submits a real job: POST /api/reverse/jobs is intercepted wherever a submit is exercised, so the CAD worker is never used.
const DATA = process.env.MCAGENT_DATA ? path.resolve(process.env.MCAGENT_DATA) : '';
test.skip(!DATA, 'MCAGENT_DATA not set: start the server with it (isolated folder) and export it for the tests');

const VERIFY = path.resolve(__dirname, '../../../docs/verification/v7');
const J1 = 'r3d_7000000000000001', J2 = 'r3d_7000000000000002', J3 = 'r3d_7000000000000003';
const JOBS = path.join(DATA, 'outputs', '3d-to-2d');
const shot = async (page: Page, name: string) => { fs.mkdirSync(VERIFY, { recursive: true }); await page.screenshot({ path: path.join(VERIFY, name) }); };
const sha = (f: string) => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const sha1 = (b: Buffer) => crypto.createHash('sha256').update(b).digest('hex');
const part = (job: string, pid: string, rel: string) => path.join(JOBS, job, pid, 'active', rel);

test.beforeAll(() => {
  execFileSync(process.env.PYTHON || 'python', [path.resolve(__dirname, '../helpers/make_v7_fixture.py'), DATA, 'reset'], { encoding: 'utf-8', env: { ...process.env, PYTHONUTF8: '1' } });
});

// 100% zoom uses Playwright's own viewport (screenshots keep their size); other zooms use CDP device metrics (CSS viewport = size / zoom,
// deviceScaleFactor = zoom), which is what browser zoom does to layout. A screenshot drops a CDP override, so evidence shots are taken at zoom 1.
async function open(page: Page, job: string, partId = '', w = 1440, h = 900, o: { zoom?: number; rail?: boolean; cdp?: boolean } = {}) {
  const zoom = o.zoom || 1;
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
const box = async (page: Page, sel: string) => (await page.locator(sel).first().boundingBox())!;
const pdfReady = (page: Page) => expect(page.locator('#rv-2d .rv-paperwrap')).toBeVisible({ timeout: 15_000 });
const srcReady = (page: Page) => expect(page.locator('#rv-src-layer .rv-paperwrap')).toBeVisible({ timeout: 15_000 });
const expanded = async (page: Page, id: string) => (await page.locator(id).getAttribute('aria-expanded')) === 'true';
async function sel(page: Page, name: string) { await page.locator('.rv-pname', { hasText: name }).click(); await page.waitForTimeout(250); }
async function openAcc(page: Page, key: string) { const b = page.locator(`#rv-acc-${key}-btn`); if ((await b.getAttribute('aria-expanded')) !== 'true') await b.click(); }
const SLD = (name: string) => ({ name, mimeType: 'application/octet-stream', buffer: Buffer.from('SLDPRT-test-' + name) });

test.describe('v7: layout', () => {
  test('110 the viewers and the batch queue are one 12px apart (no blank band), at every size, zoom and sidebar state', async ({ page }) => {
    const bad = watchConsole(page);
    const sizes: Array<[number, number]> = [[1280, 720], [1440, 900], [1920, 1080], [2560, 1100]];
    const seen: string[] = [];
    for (const [w, h] of sizes) for (const zoom of [0.8, 1, 1.25]) for (const rail of [false, true]) {
      await open(page, J1, 'flange', w, h, { zoom, rail, cdp: true });
      const m = await page.evaluate(() => {
        const r = (s: string) => { const e = document.querySelector(s) as HTMLElement | null; if (!e) return null; const b = e.getBoundingClientRect(); return { top: b.top, bottom: b.bottom, left: b.left, right: b.right, h: b.height }; };
        return { p3d: r('#rv-3d'), p2d: r('#rv-2d'), queue: r('#rv-queue'), rail: r('#rv-setup'), run: r('#rv-run-sel'), exp: r('#rv-export'), docW: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
          vh: window.innerHeight, mainW: (document.getElementById('main') as HTMLElement).scrollWidth, mainC: (document.getElementById('main') as HTMLElement).clientWidth };
      });
      const tag = `${w}x${h}@${zoom}${rail ? ' rail' : ''}`;
      const gap = m.queue!.top - m.p3d!.bottom;
      seen.push(`${tag}: gap ${gap.toFixed(1)}`);
      expect(gap, `gap ${tag}`).toBeGreaterThanOrEqual(8); expect(gap, `gap ${tag}`).toBeLessThanOrEqual(16);
      expect(Math.abs(m.p3d!.h - m.p2d!.h), `equal viewer height ${tag}`).toBeLessThanOrEqual(1);
      expect(Math.abs(m.p3d!.top - m.p2d!.top), `aligned viewers ${tag}`).toBeLessThanOrEqual(1);
      expect(m.docW, `no horizontal overflow ${tag}`).toBeLessThanOrEqual(m.cw); expect(m.mainW, `main overflow ${tag}`).toBeLessThanOrEqual(m.mainC + 1);
      if (Math.round(w / zoom) < 1100) { expect(m.rail!.h, `below 1100px css the rail is a closed drawer ${tag}`).toBeGreaterThanOrEqual(0); continue; }
      expect(m.rail!.top, `rail starts with the viewers ${tag}`).toBeGreaterThanOrEqual(m.p3d!.top - 1);
      // the rail never makes the row taller: it ends no lower than the queue
      expect(m.rail!.bottom, `rail within the row ${tag}`).toBeLessThanOrEqual(m.queue!.bottom + 1);
      // Run and Export stay inside the rail (never clipped by it), and are on screen when the screen is tall enough
      expect(m.run!.bottom, `run inside rail ${tag}`).toBeLessThanOrEqual(m.rail!.bottom + 1); expect(m.exp!.bottom, `export inside rail ${tag}`).toBeLessThanOrEqual(m.rail!.bottom + 1);
      if (m.vh >= 780) { expect(m.exp!.bottom, `export on screen ${tag}`).toBeLessThanOrEqual(m.vh + 1); }
    }
    fs.writeFileSync(path.join(VERIFY, 'gap-matrix.txt'), seen.join('\n') + '\n');
    expect(bad.filter((b) => !/favicon|Failed to load resource/.test(b))).toEqual([]);
  });

  test('111 gap holds in every queue state: empty, one running job, a 5-row batch; and narrow widths stack without overflow', async ({ page }) => {
    await page.route('**/api/reverse/jobs', (r) => (r.request().method() === 'GET' ? r.fulfill({ json: { jobs: [] } }) : r.continue()));
    await open(page, '', '', 1440, 900);
    const gap = async () => (await box(page, '#rv-queue')).y - ((await box(page, '#rv-3d')).y + (await box(page, '#rv-3d')).height);
    await expect(page.locator('.rv-queue .rv-empty')).toContainText('No runs yet');
    expect(await gap()).toBeGreaterThanOrEqual(8); expect(await gap()).toBeLessThanOrEqual(16);
    await shot(page, 'after-empty-queue-1440x900.png');
    await page.unroute('**/api/reverse/jobs');
    for (const [job, p] of [[J2, 'busy'], [J1, 'flange']] as Array<[string, string]>) {
      await open(page, job, p, 1920, 1080);
      const g = await gap(); expect(g).toBeGreaterThanOrEqual(8); expect(g).toBeLessThanOrEqual(16);
      // the active job's status is in the always-visible queue header (never inside the scrolling rows)
      await expect(page.locator('.rv-qsum')).toContainText(job === J2 ? 'Running' : 'Completed');
    }
    for (const [w, h] of [[1000, 800], [800, 900], [390, 844]] as Array<[number, number]>) {
      await open(page, J1, 'flange', w, h);
      const m = await page.evaluate(() => { const b = (s: string) => document.querySelector(s)!.getBoundingClientRect(); return { a: b('#rv-3d'), c: b('#rv-2d'), q: b('#rv-queue'), docW: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }; });
      expect(m.docW).toBeLessThanOrEqual(m.cw);
      expect(m.q.top).toBeGreaterThanOrEqual(m.a.bottom + 7); expect(m.q.top).toBeLessThanOrEqual(m.c.bottom + 16);
      if (w <= 899) expect(m.c.top).toBeGreaterThanOrEqual(m.a.bottom + 7);                 // viewers stack
    }
  });

  test('112 before/after evidence screenshots and the Pipeline Results panel still collapses', async ({ page }) => {
    for (const [w, h] of [[1280, 720], [1440, 900], [1920, 1080]] as Array<[number, number]>) { await open(page, J1, 'flange', w, h); await pdfReady(page); await page.waitForTimeout(500); await shot(page, `after-flange-${w}x${h}.png`); }
    await open(page, J1, 'flange');
    const tg = page.locator('.rv-reshead > button[aria-controls="rv-results-body"]');
    await expect(tg).toHaveAttribute('aria-expanded', 'true');
    await tg.click(); await expect(page.locator('#rv-results-body')).toBeHidden(); await expect(tg).toHaveAttribute('aria-expanded', 'false');
    await tg.click(); await expect(page.locator('#rv-results-body')).toBeVisible();
  });
});

test.describe('v7: setup rail', () => {
  test('113 accordions: collapsed by default, button + aria-expanded/controls, Enter/Space, state survives re-renders, file inputs are never recreated', async ({ page }) => {
    await open(page, J1, 'flange');
    const keys = ['tpl', 'ref', 'adv', 'rt'];
    for (const k of keys) {
      const b = page.locator(`#rv-acc-${k}-btn`);
      expect(await b.evaluate((e) => e.tagName)).toBe('BUTTON');
      await expect(b).toHaveAttribute('aria-expanded', 'false');
      const ctl = await b.getAttribute('aria-controls');
      await expect(page.locator('#' + ctl)).toHaveCount(1); await expect(page.locator('#' + ctl)).toBeHidden();
    }
    // order in the rail: template, part selection, reference, advanced, runtime; run controls and export at the bottom
    const order = await page.locator('#rv-setup-scroll > *').evaluateAll((els) => els.map((e) => e.id || (e.getAttribute('aria-labelledby') || '')));
    expect(order).toEqual(['rv-acc-tpl', 'rv-parts-t', 'rv-acc-ref', 'rv-acc-adv', 'rv-acc-rt']);
    const rail = await box(page, '#rv-setup'), run = await box(page, '#rv-run-sel'), ex = await box(page, '#rv-export');
    expect(run.y).toBeGreaterThan((await box(page, '#rv-acc-rt')).y); expect(ex.y).toBeGreaterThan(run.y); expect(ex.y + ex.height).toBeLessThanOrEqual(rail.y + rail.height + 1);
    // click, keyboard
    const adv = page.locator('#rv-acc-adv-btn');
    await adv.click(); await expect(adv).toHaveAttribute('aria-expanded', 'true'); await expect(page.locator('#rv-acc-adv-body')).toBeVisible();
    await adv.focus(); await page.keyboard.press('Enter'); await expect(adv).toHaveAttribute('aria-expanded', 'false');
    await page.keyboard.press('Space'); await expect(adv).toHaveAttribute('aria-expanded', 'true');
    // expanding does not run anything
    await expect(page.locator('#rv-run-live')).toBeHidden();
    // type in Advanced, mark the persistent inputs, then force full re-renders (choose parts, mode switches): value, open state and input nodes survive
    await page.fill('#rv-cfg', 'Default');
    await page.evaluate(() => { for (const id of ['rv-files', 'rv-dir', 'rv-ref-file', 'rv-tpl-file']) (document.getElementById(id) as any).__mark = id; });
    await page.setInputFiles('#rv-files', [SLD('one.SLDPRT'), SLD('two.SLDPRT')]);
    await expect(page.locator('#rv-pk-sum')).toContainText('2 parts selected');
    await page.locator('#rv-acc-ref-btn').click(); await page.locator('#rv-ref-mode-standard').click();
    expect(await page.evaluate(() => ['rv-files', 'rv-dir', 'rv-ref-file', 'rv-tpl-file'].map((id) => (document.getElementById(id) as any).__mark))).toEqual(['rv-files', 'rv-dir', 'rv-ref-file', 'rv-tpl-file']);
    await expect(page.locator('#rv-acc-adv-btn')).toHaveAttribute('aria-expanded', 'true');
    await expect(page.locator('#rv-cfg')).toHaveValue('Default');
    await expect(page.locator('#rv-pk-sum')).toContainText('2 parts selected');
    // collapse and re-open: the chosen parts and values are still there
    await page.locator('#rv-acc-adv-btn').click(); await page.locator('#rv-acc-ref-btn').click();
    await page.locator('#rv-acc-adv-btn').click(); await expect(page.locator('#rv-cfg')).toHaveValue('Default');
    await expect(page.locator('#rv-pk-sum')).toContainText('2 parts selected');
    // state is per workspace session: it survives leaving the page and returning
    await page.goto('/#/home'); await page.goto(`/#/reverse?job=${J1}&part=flange`);
    await expect(page.locator('#rv-acc-adv-btn')).toHaveAttribute('aria-expanded', 'true');
  });

  test('114 polling never resets the rail: a running job is polled while accordions, scroll, focus and typed text stay put; the reference panel does not open by itself', async ({ page }) => {
    let polls = 0;
    await page.route(`**/api/reverse/jobs/${J2}`, async (r) => { polls++; await r.continue(); });
    await open(page, J2, 'busy');
    await expect(page.locator('.rv-qsum')).toContainText('Running');
    await openAcc(page, 'adv');
    await page.fill('#rv-cfg', 'ConfigA'); await page.locator('#rv-cfg').focus();
    await page.locator('#rv-setup-scroll').evaluate((e) => { e.scrollTop = 40; });
    const st0 = await page.evaluate(() => ({ ref: document.getElementById('rv-acc-ref-btn')!.getAttribute('aria-expanded'), top: document.getElementById('rv-setup-scroll')!.scrollTop }));
    const before = polls;
    await page.waitForTimeout(5200);
    expect(polls - before).toBeGreaterThanOrEqual(2);
    await expect(page.locator('#rv-acc-ref-btn')).toHaveAttribute('aria-expanded', st0.ref!);
    await expect(page.locator('#rv-acc-ref-btn')).toHaveAttribute('aria-expanded', 'false');
    await expect(page.locator('#rv-acc-adv-btn')).toHaveAttribute('aria-expanded', 'true');
    await expect(page.locator('#rv-cfg')).toHaveValue('ConfigA'); await expect(page.locator('#rv-cfg')).toBeFocused();
    expect(await page.locator('#rv-setup-scroll').evaluate((e) => e.scrollTop)).toBeGreaterThanOrEqual(Math.min(st0.top, 40) - 1);
    await expect(page.locator('#rv-run-live')).toBeVisible(); await expect(page.locator('#rv-run-live')).toContainText('part');
  });

  test('115 runtime and cost: collapsed with a visible summary; OpenAI cost and local CAD time are separate lines', async ({ page }) => {
    await open(page, J1, 'flange');
    await expect(page.locator('#rv-acc-rt-body')).toBeHidden();
    const sum = await page.locator('#rv-acc-rt-sum').innerText();
    expect(sum).toMatch(/OpenAI/); expect(sum.length).toBeGreaterThan(8);
    await openAcc(page, 'rt');
    await expect(page.locator('#rv-acc-rt-body')).toContainText('Local CAD time (no token cost)');
    await expect(page.locator('#rv-acc-rt-body')).toContainText('OpenAI (reference extraction only)');
    await expect(page.locator('#rv-openai')).toContainText(/OpenAI/);
    expect(await page.locator('#rv-openai').innerText()).not.toMatch(/NaN|undefined|null/);
    // after a run the OpenAI line comes from the parts' measured usage (the seed: bracket $0.0317 + flange $0.0000 + two parts without a record)
    await expect(page.locator('#rv-openai')).toContainText('$0.0317');
    await expect(page.locator('#rv-openai')).toContainText('others not recorded');
  });
});

test.describe('v7: reference drawing', () => {
  const CAND = (id: string, o: any = {}) => ({ artifact_id: id, filename: id + '.pdf', project: 'A001151E', run: 'run-3', date: '2026-11-20', pages: 2, confidence: 0.98, reasons: ['same SHA-256'], needs_confirmation: false, link: 'part_hash', ...o });
  async function mockLookup(page: Page) {
    const seen: any = { confirm: [], candidates: 0 };
    await page.route('**/api/reverse/reference/candidates', async (r) => {
      seen.candidates++;
      const req = JSON.parse(r.request().postData() || '{}');
      await r.fulfill({ json: { stage_id: req.stage_id, rows: [
        { key: 'p0', name: 'flange.sldprt', selected: CAND('pdf_aaaa1111'), candidates: [CAND('pdf_aaaa1111')] },
        { key: 'p1', name: 'bracket.sldprt', selected: null, candidates: [CAND('pdf_bbbb2222', { filename: 'bracket-revB.pdf', confidence: 0.5, needs_confirmation: true, reasons: ['same part number'], link: null }), CAND('pdf_cccc3333', { filename: 'bracket-revC.pdf', confidence: 0.5, needs_confirmation: true, link: null })] },
        { key: 'p2', name: 'cover.sldprt', selected: null, candidates: [], error: '' }] } });
    });
    await page.route('**/api/reverse/reference/confirm', async (r) => { seen.confirm.push(JSON.parse(r.request().postData() || '{}')); await r.fulfill({ json: { ok: true, artifact_id: seen.confirm[seen.confirm.length - 1].artifact_id, persisted: true } }); });
    return seen;
  }

  test('116 Standard is the default and never needs a reference; Match shows per-part status, ambiguous and unmatched rows block Run until resolved explicitly', async ({ page }) => {
    const seen = await mockLookup(page);
    const submits: any[] = [];
    await page.route('**/api/reverse/jobs', async (r) => {
      if (r.request().method() !== 'POST') return r.continue();
      submits.push({ ct: r.request().headers()['content-type'], body: r.request().postData() });
      await r.fulfill({ json: { job_id: J1, rejected: [], parts: [{ part_id: 'flange', name: 'flange' }] } });
    });
    await open(page, J1, 'flange');
    await page.setInputFiles('#rv-files', [SLD('flange.SLDPRT'), SLD('bracket.SLDPRT'), SLD('cover.SLDPRT')]);
    await expect(page.locator('#rv-ref-mode-standard')).toBeHidden();                         // the reference panel is collapsed until the user (or an actionable issue) opens it
    await expect(page.locator('#rv-acc-ref-sum')).toHaveText('Standard');
    await expect(page.locator('#rv-run-sel')).toBeEnabled();                                  // Standard needs no reference
    await page.locator('#rv-acc-ref-btn').click();
    await expect(page.locator('#rv-ref-mode')).toHaveAttribute('role', 'radiogroup');
    await expect(page.locator('#rv-ref-mode-standard')).toHaveAttribute('aria-checked', 'true');
    await page.locator('#rv-ref-mode-match').click();
    await expect(page.locator('#rv-ref-mode-match')).toHaveAttribute('aria-checked', 'true');
    await expect(page.locator('.rv-rrow')).toHaveCount(3, { timeout: 15_000 });
    await expect.poll(() => seen.candidates).toBeGreaterThanOrEqual(1);
    await expect(page.locator('.rv-rrow[data-key="p0"]')).toHaveAttribute('data-status', 'ready');
    await expect(page.locator('.rv-rrow[data-key="p0"]')).toContainText('Auto-matched: pdf_aaaa1111.pdf · 2 pages · A001151E / run-3 · 2026-11-20 · 98% confidence');
    await expect(page.locator('.rv-rrow[data-key="p1"]')).toHaveAttribute('data-status', 'needs_confirmation');
    await expect(page.locator('.rv-rrow[data-key="p1"]')).toContainText('2 possible matches');
    await expect(page.locator('.rv-rrow[data-key="p2"]')).toHaveAttribute('data-status', 'unmatched');
    await expect(page.locator('#rv-ref-status')).toHaveText('1 of 3 matched · 1 need confirmation · 1 unmatched');
    await expect(page.locator('#rv-acc-ref-sum')).toHaveText('1 of 3 matched · 1 need confirmation · 1 unmatched');
    await expect(page.locator('#rv-run-sel')).toBeDisabled();
    await expect(page.locator('#rv-run-why')).toContainText('Choose and confirm the reference for 1 part');
    await shot(page, 'after-reference-match-1440x900.png');
    // choose a candidate: it must be confirmed explicitly before the run can use it
    await page.locator('#rv-rsel-p1').selectOption('pdf_bbbb2222');
    await expect(page.locator('.rv-rrow[data-key="p1"]')).toContainText('Confirm: bracket-revB.pdf');
    await expect(page.locator('#rv-run-sel')).toBeDisabled();
    await page.locator('#rv-rconf-p1').click();
    await expect(page.locator('.rv-rrow[data-key="p1"]')).toHaveAttribute('data-status', 'ready');
    expect(seen.confirm[0]).toMatchObject({ key: 'p1', artifact_id: 'pdf_bbbb2222' });
    // the unmatched part: blocked until Upload or an explicit Standard choice
    await expect(page.locator('#rv-run-why')).toContainText('1 part has no reference. Upload one or choose Standard for it.');
    await page.locator('#rv-rstd-p2').click();
    await expect(page.locator('.rv-rrow[data-key="p2"]')).toHaveAttribute('data-status', 'standard');
    await expect(page.locator('#rv-run-sel')).toBeEnabled();
    await page.locator('#rv-rreset-p2').click();
    await expect(page.locator('#rv-run-sel')).toBeDisabled();
    await page.locator('#rv-rstd-p2').click();
    // submit: JSON with the stage, the keys, and ids only (no paths)
    await page.locator('#rv-run-sel').click();
    await expect.poll(() => submits.length).toBe(1);
    expect(submits[0].ct).toContain('application/json');
    const body = JSON.parse(submits[0].body);
    expect(body.keys).toEqual(['p0', 'p1', 'p2']); expect(body.stage_id).toMatch(/^s_[0-9a-f]{12}$/);
    expect(body.reference).toEqual({ mode: 'match', fallback_standard: true, per_part: { p0: { source: 'artifact', artifact_id: 'pdf_aaaa1111' }, p1: { source: 'artifact', artifact_id: 'pdf_bbbb2222' }, p2: { source: 'none' } } });
    expect(JSON.stringify(body)).not.toMatch(/pdf_path|[A-Za-z]:[\\/]|\/home\//);
  });

  test('117 explicit upload overrides the lookup for one row; the real upload route validates the PDF; errors are shown on the row', async ({ page }) => {
    await mockLookup(page);
    const submits: any[] = [];
    await page.route('**/api/reverse/jobs', async (r) => {
      if (r.request().method() !== 'POST') return r.continue();
      submits.push(JSON.parse(r.request().postData() || '{}'));
      await r.fulfill({ json: { job_id: J1, rejected: [], parts: [{ part_id: 'flange', name: 'flange' }] } });
    });
    await open(page, J1, 'flange');
    await page.setInputFiles('#rv-files', [SLD('flange.SLDPRT'), SLD('bracket.SLDPRT')]);
    await openAcc(page, 'ref'); await page.locator('#rv-ref-mode-match').click();
    await expect(page.locator('.rv-rrow')).toHaveCount(2, { timeout: 15_000 });
    // wrong type and oversize are refused in the browser; a non-PDF with a .pdf name is refused by the server (real route)
    const chooser = page.waitForEvent('filechooser'); await page.locator('#rv-rup-p0').click(); await (await chooser).setFiles({ name: 'fake.pdf', mimeType: 'application/pdf', buffer: Buffer.from('this is not a pdf') });
    await expect(page.locator('.rv-rrow[data-key="p0"] .rv-rrow-err')).toContainText(/not a PDF|signature/i);
    expect(await page.locator('#page-reverse').innerText()).not.toMatch(/[A-Za-z]:[\\/]Users/);
    // a real 2-page PDF (the seeded source test PDF) goes through the real route and the real backend validation
    const good = part(J1, 'flange', 'reference/source.pdf');
    const ch2 = page.waitForEvent('filechooser'); await page.locator('#rv-rup-p0').click(); await (await ch2).setFiles(good);
    await expect(page.locator('.rv-rrow[data-key="p0"]')).toContainText('Uploaded: source.pdf (2 pages)', { timeout: 15_000 });
    await expect(page.locator('.rv-rrow[data-key="p0"]')).toHaveAttribute('data-status', 'ready');
    await expect(page.locator('#rv-rup-p0')).toContainText('Replace PDF');
    // other row unaffected; resolve it and run: upload id (a sha256), never a path
    await page.locator('#rv-rsel-p1').selectOption('pdf_bbbb2222'); await page.locator('#rv-rconf-p1').click();
    await expect(page.locator('#rv-run-sel')).toBeEnabled();
    // Reset removes the override and the lookup applies again; upload again to continue
    await page.locator('#rv-rreset-p0').click();
    await expect(page.locator('.rv-rrow[data-key="p0"]')).toContainText('Auto-matched');
    const ch3 = page.waitForEvent('filechooser'); await page.locator('#rv-rup-p0').click(); await (await ch3).setFiles(good);
    await expect(page.locator('.rv-rrow[data-key="p0"]')).toContainText('Uploaded: source.pdf (2 pages)', { timeout: 15_000 });
    await page.locator('#rv-run-sel').click(); await expect.poll(() => submits.length).toBe(1);
    expect(submits[0].reference.per_part.p0).toEqual({ source: 'upload', upload_id: sha(good) });
    expect(submits[0].reference.per_part.p1.source).toBe('artifact');
  });

  test('118 the real lookup for an unknown part says so honestly (no saved source), and a backend without reference support disables Match with the reason', async ({ page }) => {
    await open(page, J1, 'flange');
    await page.setInputFiles('#rv-files', [SLD('mystery.SLDPRT')]);
    await openAcc(page, 'ref'); await page.locator('#rv-ref-mode-match').click();
    await expect(page.locator('.rv-rrow[data-key="p0"]')).toHaveAttribute('data-status', 'unmatched', { timeout: 20_000 });
    await expect(page.locator('.rv-rrow[data-key="p0"]')).toContainText('No saved source found');
    await expect(page.locator('#rv-run-sel')).toBeDisabled();
    await expect(page.locator('#rv-run-why')).toContainText('no reference');
    // capability absent
    await page.route('**/api/reverse/capabilities', (r) => r.fulfill({ json: { reference: false, candidates: false, upload: false, confirm: false, export: true } }));
    await open(page, J1, 'flange');
    await openAcc(page, 'ref');
    await expect(page.locator('#rv-ref-mode-match')).toHaveAttribute('aria-disabled', 'true');
    await expect(page.locator('#rv-ref-mode-match')).toHaveAttribute('title', /not available in this backend/);
    await page.locator('#rv-ref-mode-match').click({ force: true });
    await expect(page.locator('#rv-ref-mode-standard')).toHaveAttribute('aria-checked', 'true');
    await expect(page.locator('#rv-acc-ref-body')).toContainText('not available in this backend build');
  });

  test('119 stage lookup failure and an expired stage show an error, not a fake result', async ({ page }) => {
    await page.route('**/api/reverse/stage', (r) => (r.request().method() === 'POST' ? r.fulfill({ status: 500, json: { detail: 'The parts could not be saved.' } }) : r.continue()));
    await open(page, J1, 'flange');
    await page.setInputFiles('#rv-files', [SLD('a.SLDPRT')]);
    await openAcc(page, 'ref'); await page.locator('#rv-ref-mode-match').click();
    await expect(page.locator('#rv-acc-ref-body .banner')).toContainText('The parts could not be saved.', { timeout: 15_000 });
    await expect(page.locator('#rv-run-sel')).toBeDisabled();
  });

  test('120 provenance and extraction accordion shows what the selected finished part really used', async ({ page }) => {
    await open(page, J1, 'flange');
    await openAcc(page, 'ref'); await page.locator('#rv-acc-prov-btn').click();
    const body = page.locator('#rv-acc-prov-body');
    await expect(body).toContainText('Forward run history'); await expect(body).toContainText('flange-original.pdf (2 pages)');
    await expect(body).toContainText('Reused saved extraction (no new model call)'); await expect(body).toContainText('No OpenAI call in this run ($0.00)');
    await expect(body).toContainText('same part file (SHA-256)'); await expect(body).toContainText(sha(part(J1, 'flange', 'reference/source.pdf')).slice(0, 12));
    // switching the part updates it in place (and keeps it open); a Standard part says so; a blocked part shows its warning
    await sel(page, 'bracket'); await expect(body).toContainText('Uploaded PDF'); await expect(body).toContainText('Note N3 overlaps a view in the source drawing');
    await expect(page.locator('#rv-acc-prov-btn')).toHaveAttribute('aria-expanded', 'true');
    await sel(page, 'plate'); await expect(body).toContainText('No reference was used for the selected part.');
    await sel(page, 'cover'); await expect(body).toContainText('Two same-name revisions need confirmation');
    await expect(page.locator('.rv-tbl tr[data-part="cover"]')).toContainText('Reference blocked');
    await expect(page.locator('.rv-tbl tr[data-part="cover"] .rv-perr')).toContainText('REFERENCE_BLOCKED');
  });
});

test.describe('v7: export', () => {
  test('121 export is enabled only for artifacts that exist, bound to the selected part, with draft status and acknowledgement', async ({ page }) => {
    await open(page, J1, 'flange');
    const states = async () => page.evaluate(() => ['slddrw', 'pdf', 'zip'].map((k) => !(document.getElementById('rv-exp-' + k) as HTMLButtonElement).disabled));
    const status = () => page.locator('#rv-exp-status').innerText();
    // flange: verified draft, both artifacts: everything enabled, no acknowledgement control
    await expect(page.locator('#rv-exp-status')).toContainText('Draft: for review (not approved for manufacture)');
    expect(await states()).toEqual([true, true, true]); await expect(page.locator('#rv-exp-ack')).toHaveCount(0);
    for (const [k, l] of [['slddrw', 'Download SLDDRW'], ['pdf', 'Download PDF'], ['zip', 'Download both (ZIP)']]) expect(await page.locator(`#rv-exp-${k}`).getAttribute('title')).toContain(l);
    // bracket: review required: disabled until the explicit acknowledgement; reasons are visible
    await sel(page, 'bracket');
    await expect(page.locator('#rv-exp-status')).toContainText('Draft: review required');
    expect(await states()).toEqual([false, false, false]);
    await expect(page.locator('#rv-exp-pdf')).toHaveAttribute('title', /Tick the acknowledgement/);
    await page.locator('#rv-exp-ack').check(); expect(await states()).toEqual([true, true, true]);
    // moving to another part drops the acknowledgement (never carried over), and back again it is unticked
    await sel(page, 'plate'); await expect(page.locator('#rv-exp-ack')).not.toBeChecked();
    await expect(page.locator('#rv-exp-status')).toContainText('Draft: review required'); await expect(page.locator('#rv-exp-why')).toContainText('Verification was not completed');
    await sel(page, 'bracket'); await expect(page.locator('#rv-exp-ack')).not.toBeChecked(); expect(await states()).toEqual([false, false, false]);
    // failed (blocked) and canceled parts: nothing to export, with the reason
    await sel(page, 'cover'); expect(await states()).toEqual([false, false, false]);
    await expect(page.locator('#rv-exp-slddrw')).toHaveAttribute('title', /not produced|not finished|did not/i);
    await sel(page, 'gone'); expect(await states()).toEqual([false, false, false]); await expect(page.locator('#rv-exp-pdf')).toHaveAttribute('title', /canceled/);
    expect(await status()).toMatch(/Draft/);
    // running job: nothing exportable yet
    await open(page, J2, 'busy'); expect(await states()).toEqual([false, false, false]);
    // a PDF without an SLDDRW: only the PDF is offered
    await open(page, J3, 'pdfonly'); await expect(page.locator('#rv-exp-status')).toContainText('Draft: for review');
    expect(await states()).toEqual([false, true, false]); await expect(page.locator('#rv-exp-slddrw')).toHaveAttribute('title', /not produced/); await expect(page.locator('#rv-exp-zip')).toHaveAttribute('title', /Both/);
    await shot(page, 'after-export-pdf-only-1440x900.png');
  });

  test('122 downloads: PDF, SLDDRW and ZIP are the real artifact bytes of THIS part; filenames are sanitised; a notification confirms', async ({ page }) => {
    await open(page, J1, 'flange');
    const urls: string[] = [];
    page.on('request', (r) => { if (/\/export\//.test(r.url())) urls.push(r.url()); });
    const dl = async (id: string) => { const [d] = await Promise.all([page.waitForEvent('download'), page.locator(id).click()]); const p = await d.path(); return { name: d.suggestedFilename(), buf: fs.readFileSync(p!) }; };
    const pdf = await dl('#rv-exp-pdf');
    expect(pdf.name).toBe('flange-drawing.pdf'); expect(pdf.buf.subarray(0, 5).toString()).toBe('%PDF-'); expect(sha1(pdf.buf)).toBe(sha(part(J1, 'flange', 'drawing.pdf')));
    await expect(page.locator('.toast').last()).toContainText('Downloaded flange-drawing.pdf');
    const drw = await dl('#rv-exp-slddrw');
    expect(drw.name).toBe('flange-drawing.slddrw'); expect(sha1(drw.buf)).toBe(sha(part(J1, 'flange', 'drawing.slddrw'))); expect(drw.buf.length).toBeGreaterThan(1000);
    const zip = await dl('#rv-exp-zip');
    expect(zip.name).toBe('flange-drawing.zip'); expect(zip.buf.subarray(0, 4).toString('hex')).toBe('504b0304');
    expect(zip.buf.toString('latin1')).toContain('flange-drawing.slddrw'); expect(zip.buf.toString('latin1')).toContain('flange-drawing.pdf');
    expect(urls.every((u) => u.includes(`/jobs/${J1}/parts/flange/export/`))).toBe(true);
    // a download after switching part goes to that part, not the previous one
    await sel(page, 'bracket'); await page.locator('#rv-exp-ack').check();
    urls.length = 0; const b = await dl('#rv-exp-pdf');
    expect(urls[0]).toContain(`/jobs/${J1}/parts/bracket/export/pdf`); expect(urls[0]).toContain('ack=1'); expect(sha1(b.buf)).toBe(sha(part(J1, 'bracket', 'drawing.pdf')));
    expect(b.name).toBe('bracket-drawing.pdf');
  });

  test('123 server refusals are shown as notifications and nothing is saved: stale file, canceled part, missing acknowledgement', async ({ page }) => {
    await open(page, J1, 'flange');
    await page.route('**/export/pdf*', (r) => r.fulfill({ status: 409, json: { detail: 'This file changed since the page was loaded. Refresh and try again.' } }));
    let downloads = 0; page.on('download', () => downloads++);
    await page.locator('#rv-exp-pdf').click();
    await expect(page.locator('.toast.is-err').last()).toContainText('changed since the page was loaded');
    await expect(page.locator('.toast.is-err').last()).toContainText('flange');
    expect(downloads).toBe(0);
    await page.unroute('**/export/pdf*');
    // the real server enforces acknowledgement itself, whatever the browser does
    const r1 = await page.request.get(`/api/reverse/jobs/${J1}/parts/bracket/export/pdf`);
    expect(r1.status()).toBe(409); expect((await r1.json()).detail).toMatch(/Acknowledge/);
    expect((await page.request.get(`/api/reverse/jobs/${J1}/parts/gone/export/pdf?ack=1`)).status()).toBe(409);
    expect((await page.request.get(`/api/reverse/jobs/${J1}/parts/cover/export/slddrw?ack=1`)).status()).toBe(404);
    expect((await page.request.get(`/api/reverse/jobs/${J1}/parts/flange/export/pdf?expect=1`)).status()).toBe(409);
    expect((await page.request.get(`/api/reverse/jobs/${J1}/parts/..%2f..%2fx/export/pdf`)).status()).toBeGreaterThanOrEqual(400);
    expect((await page.request.get(`/api/reverse/jobs/${J3}/parts/flange/export/pdf?ack=1`)).status()).toBe(404);           // wrong job for that part
  });
});

test.describe('v7: left viewer toggle', () => {
  test('124 Source PDF shows the real original file (not the generated one); pages, zoom, fit, labels, provenance; 3D model is untouched', async ({ page }) => {
    const bad = watchConsole(page);
    const pdfBodies: Record<string, string> = {};
    page.on('response', async (r) => { if (/\.pdf(\?|$)/.test(r.url()) && r.status() === 200) { try { pdfBodies[r.url().split('/files/')[1].split('?')[0]] = sha1(await r.body()); } catch { /* ignore */ } } });
    await page.addInitScript(() => { const o = URL.createObjectURL; (window as any).__blobs = 0; URL.createObjectURL = function (b: any) { (window as any).__blobs++; return o.call(URL, b); }; });
    await open(page, J1, 'flange');
    await pdfReady(page);
    const seg = page.locator('#rv-left-seg');
    await expect(seg).toHaveAttribute('role', 'group');
    await expect(page.locator('#rv-3d-t')).toHaveText('3D Model (STL)');
    await expect(page.locator('#rv-left-3d')).toHaveAttribute('aria-pressed', 'true'); await expect(page.locator('#rv-left-src')).toHaveAttribute('aria-disabled', 'false');
    await expect(page.locator('#rv-gen-lbl')).toHaveText('Generated');
    await expect(page.locator('#rv-3d canvas').first()).toBeVisible();
    await page.locator('#rv-left-src').click();
    await srcReady(page);
    await expect(page.locator('#rv-3d-t')).toHaveText('Source PDF (Original)'); await expect(page.locator('#rv-left-src')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('#rv-src-prov')).toContainText('Original reference. flange-original.pdf · 2 pages · Forward run history · SHA-256 ' + sha(part(J1, 'flange', 'reference/source.pdf')).slice(0, 12));
    await expect(page.locator('#rv-stl-layer')).toBeHidden(); await expect(page.locator('#rv-3d .rv-pagelbl')).toHaveText('Page 1 of 2');
    // exactly the original bytes were loaded for the left viewer; the generated PDF is a different file on the right
    const srcRel = `flange/active/reference/source.pdf`, genRel = `flange/active/drawing.pdf`;
    const key = Object.keys(pdfBodies).find((k) => k.endsWith(srcRel))!;
    expect(pdfBodies[key]).toBe(sha(part(J1, 'flange', 'reference/source.pdf')));
    expect(pdfBodies[Object.keys(pdfBodies).find((k) => k.endsWith(genRel))!]).toBe(sha(part(J1, 'flange', 'drawing.pdf')));
    expect(sha(part(J1, 'flange', 'reference/source.pdf'))).not.toBe(sha(part(J1, 'flange', 'drawing.pdf')));
    // the left canvas was painted (white sheet with the test drawing's black lines); the right one is unchanged
    const painted = (sel_: string) => page.evaluate((s) => { const c = document.querySelector(s) as HTMLCanvasElement; if (!c || !c.width) return false; const d = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data; let dark = 0; for (let i = 0; i < d.length; i += 4 * 5) if (d[i] < 120) dark++; return dark > 5; }, sel_);
    expect(await painted('#rv-src-layer canvas.rv-paper')).toBe(true); expect(await painted('#rv-2d canvas.rv-paper')).toBe(true);
    // pages, zoom, fit
    await page.locator('#rv-3d .rv-src-tools button[aria-label^="Next page"]').click(); await expect(page.locator('#rv-3d .rv-pagelbl')).toHaveText('Page 2 of 2');
    await page.locator('#rv-3d .rv-src-tools button[aria-label^="Zoom in"]').click(); await expect(page.locator('#rv-3d .rv-zoomlbl')).toHaveText('125%');
    await page.locator('#rv-3d .rv-src-tools button[aria-label^="Fit"]').click(); await expect(page.locator('#rv-3d .rv-zoomlbl')).toHaveText('100%');
    await expect(page.locator('#rv-2d .rv-pagelbl')).toHaveText('Sheet 1 of 1');                  // the right viewer did not move
    // pan: drag a zoomed sheet
    await page.locator('#rv-3d .rv-src-tools button[aria-label^="Zoom in"]').click(); await page.locator('#rv-3d .rv-src-tools button[aria-label^="Zoom in"]').click(); await page.locator('#rv-3d .rv-src-tools button[aria-label^="Zoom in"]').click();
    const wrap = page.locator('#rv-src-layer .rv-paperwrap'); const bb = (await wrap.boundingBox())!;
    const before = await wrap.evaluate((e) => [e.scrollLeft, e.scrollTop]);
    await page.mouse.move(bb.x + bb.width / 2, bb.y + bb.height / 2); await page.mouse.down(); await page.mouse.move(bb.x + bb.width / 2 - 60, bb.y + bb.height / 2 - 40, { steps: 4 }); await page.mouse.up();
    const after = await wrap.evaluate((e) => [e.scrollLeft, e.scrollTop]); expect(after[0] + after[1]).toBeGreaterThan(before[0] + before[1]);
    await shot(page, 'after-source-pdf-1440x900.png');
    // fullscreen control exists and is wired to the panel
    expect(await page.locator('#rv-src-fs').getAttribute('aria-label')).toBe('Fullscreen source PDF');
    // back to the 3D model: unchanged viewer, STL still loaded
    await page.locator('#rv-left-3d').click(); await expect(page.locator('#rv-stl-layer')).toBeVisible(); await expect(page.locator('#rv-3d-t')).toHaveText('3D Model (STL)');
    await expect(page.locator('#rv-3d .vp-empty:visible')).toHaveCount(0);
    expect(await page.evaluate(() => (window as any).__blobs)).toBe(0);                            // viewing never creates object URLs (downloads do, and revoke them)
    expect(bad.filter((b) => !/favicon|Failed to load resource/.test(b))).toEqual([]);
  });

  test('125 unavailable source: disabled with a reason for Standard, blocked and in-progress parts; the generated PDF is never shown as the source', async ({ page }) => {
    await open(page, J1, 'plate');
    const src = page.locator('#rv-left-src');
    await expect(src).toHaveAttribute('aria-disabled', 'true'); await expect(src).toHaveAttribute('title', /Standard mode/);
    await src.click({ force: true });
    await expect(page.locator('#rv-left-3d')).toHaveAttribute('aria-pressed', 'true'); await expect(page.locator('#rv-src-layer')).toBeHidden(); await expect(page.locator('#rv-3d-t')).toHaveText('3D Model (STL)');
    await sel(page, 'cover'); await expect(src).toHaveAttribute('aria-disabled', 'true'); await expect(src).toHaveAttribute('title', /blocked/);
    await sel(page, 'gone'); await expect(src).toHaveAttribute('aria-disabled', 'true');
    await open(page, J2, 'later'); await expect(src).toHaveAttribute('aria-disabled', 'true');
    await open(page, J3, 'pdfonly'); await expect(src).toHaveAttribute('title', /Standard mode/);
    // a stale selection cannot show a source that the part lacks: select flange + Source PDF, then the Standard part
    await open(page, J1, 'flange'); await src.click(); await srcReady(page);
    await sel(page, 'plate');
    await expect(page.locator('#rv-3d-t')).toHaveText('3D Model (STL)'); await expect(page.locator('#rv-src-layer')).toBeHidden();
    expect(await page.evaluate(() => (window as any).McA.pages.reverse._state.partId)).toBe('plate');
  });

  test('126 view state is kept per part and mode: switching part resets the viewers (no stale sheet), returning restores that part\'s mode, page and zoom', async ({ page }) => {
    await open(page, J1, 'flange'); await pdfReady(page);
    await page.locator('#rv-left-src').click(); await srcReady(page);
    await page.locator('#rv-3d .rv-src-tools button[aria-label^="Next page"]').click(); await expect(page.locator('#rv-3d .rv-pagelbl')).toHaveText('Page 2 of 2');
    await page.locator('#rv-3d .rv-src-tools button[aria-label^="Zoom in"]').click();
    await sel(page, 'bracket');
    await expect(page.locator('#rv-3d-t')).toHaveText('3D Model (STL)');                          // bracket has its own (default) mode
    await page.locator('#rv-left-src').click(); await srcReady(page);
    await expect(page.locator('#rv-3d .rv-pagelbl')).toHaveText('Page 1 of 1'); await expect(page.locator('#rv-3d .rv-zoomlbl')).toHaveText('100%');
    await expect(page.locator('#rv-src-prov')).toContainText('bracket-customer.pdf');             // its own provenance, not flange's
    await sel(page, 'flange'); await srcReady(page);
    await expect(page.locator('#rv-3d .rv-pagelbl')).toHaveText('Page 2 of 2'); await expect(page.locator('#rv-3d .rv-zoomlbl')).toHaveText('125%');
    await expect(page.locator('#rv-src-prov')).toContainText('flange-original.pdf');
  });

  test('127 synchronised page/zoom is optional, only offered when the sheets correspond, and works in both directions', async ({ page }) => {
    await open(page, J1, 'flange'); await pdfReady(page);                                          // 2 source pages vs 1 generated sheet: not corresponding
    await page.locator('#rv-left-src').click(); await srcReady(page);
    await expect(page.locator('#rv-sync')).toHaveAttribute('aria-disabled', 'true'); await expect(page.locator('#rv-sync')).toHaveAttribute('title', /do not correspond \(2 source vs 1 generated\)/);
    await page.locator('#rv-sync').click({ force: true }); await expect(page.locator('#rv-sync')).toHaveAttribute('aria-pressed', 'false');
    // bracket: a 1-page source against its 1-sheet generated drawing
    await open(page, J1, 'bracket'); await pdfReady(page);
    await page.locator('#rv-left-src').click(); await srcReady(page);
    await expect(page.locator('#rv-3d .rv-pagelbl')).toHaveText('Page 1 of 1');
    await expect(page.locator('#rv-sync')).toHaveAttribute('aria-disabled', 'false');
    await expect(page.locator('#rv-sync')).toHaveAttribute('aria-pressed', 'true');                  // v8: on by default when the page counts match (v7 started off)
    await page.locator('#rv-2d button[aria-label="Zoom in"]').click(); await expect(page.locator('#rv-3d .rv-zoomlbl')).toHaveText('125%');     // right drives left
    await page.locator('#rv-3d .rv-src-tools button[aria-label^="Zoom in"]').click(); await expect(page.locator('#rv-2d .rv-zoomlbl')).toHaveText('150%');       // left drives right
    await page.locator('#rv-sync').click(); await expect(page.locator('#rv-sync')).toHaveAttribute('aria-pressed', 'false');
    await page.locator('#rv-2d button[aria-label="Fit sheet to view"]').click(); await expect(page.locator('#rv-3d .rv-zoomlbl')).toHaveText('150%');  // independent again
  });

  test('128 loading, error and retry states: a source PDF that fails to load shows an error with Retry, never a stale or generated sheet', async ({ page }) => {
    let fail = true;
    await page.route('**/reference/source.pdf*', (r) => (fail ? r.abort() : r.continue()));
    await open(page, J1, 'flange'); await pdfReady(page);
    await page.locator('#rv-left-src').click();
    await expect(page.locator('#rv-src-layer .vp-empty')).toContainText(/could not be read|could not be shown/, { timeout: 15_000 });
    await expect(page.locator('#rv-src-layer .rv-paperwrap')).toBeHidden();
    fail = false;
    await page.locator('#rv-src-layer button', { hasText: 'Retry' }).click();
    await srcReady(page); await expect(page.locator('#rv-3d .rv-pagelbl')).toHaveText('Page 1 of 2');
  });
});

test.describe('v7: stages, keyboard and accessibility', () => {
  test('129 stages follow the job: Standard parts show the three reference stages as Not applicable and they do not count', async ({ page }) => {
    await open(page, J1, 'plate');
    await expect(page.locator('.rv-tracker .trk-step')).toHaveCount(10);
    await expect(page.locator('.rv-tracker .trk-step[data-state="na"]')).toHaveCount(3);
    await expect(page.locator('.rv-tracker .trk-step[data-state="na"] .sr-only').first()).toContainText('Not applicable');
    await expect(page.locator('.rv-tracker .trk-step[data-state="succeeded"]')).toHaveCount(7);
    await expect(page.locator('.rv-tbl tr[data-part="plate"] .rv-segn')).toHaveText('7/7');
    await sel(page, 'flange'); await expect(page.locator('.rv-tracker .trk-step[data-state="succeeded"]')).toHaveCount(10);
    await expect(page.locator('.rv-tbl tr[data-part="flange"] .rv-segn')).toHaveText('10/10');
    await sel(page, 'cover'); await expect(page.locator('.rv-tracker .trk-step[data-state="failed"]')).toHaveCount(1);
    await expect(page.locator('.rv-tracker .trk-stage')).toContainText('Reference failed');
    await open(page, J1, 'bracket'); await page.locator('#rv-tab-verification').click();
    await expect(page.locator('#rv-results-body')).toContainText('Review required'); await expect(page.locator('#rv-results-body')).toContainText('9 of 10 (1 unresolved)'); expect(await page.locator('#rv-results-body').innerText()).not.toContain('[object');
    await expect(page.locator('#rv-results-body')).toContainText('R12 not found in the model'); await expect(page.locator('#rv-results-body')).toContainText('Correction passes'); await expect(page.locator('.rv-cmp img')).toHaveCount(1);
  });

  test('130 keyboard and ARIA: radiogroups with arrow keys, labelled controls, visible focus, no axe serious violations', async ({ page }) => {
    await open(page, J1, 'flange');
    for (const k of ['tpl', 'ref', 'adv', 'rt', 'prov']) await openAcc(page, k);
    // ref radiogroups
    const mode = page.locator('#rv-ref-mode');
    await page.locator('#rv-ref-mode-standard').focus(); await page.keyboard.press('ArrowRight');
    await expect(page.locator('#rv-ref-mode-match')).toHaveAttribute('aria-checked', 'true');
    await expect(page.locator('#rv-ref-source')).toBeVisible();
    await page.locator('#rv-ref-source-auto').focus(); await page.keyboard.press('ArrowRight');
    await expect(page.locator('#rv-ref-source-upload')).toHaveAttribute('aria-checked', 'true');
    await page.keyboard.press('ArrowLeft'); await expect(page.locator('#rv-ref-source-auto')).toHaveAttribute('aria-checked', 'true');
    await page.locator('#rv-ref-mode-standard').click();
    // every button and field in the rail has an accessible name
    const unnamed = await page.locator('#rv-setup button, #rv-setup input:not(.dz-input), #rv-setup select, #rv-setup [role="radio"]').evaluateAll((els) => els.filter((e) => {
      const el = e as HTMLElement; const id = el.id; const lab = id ? document.querySelector(`label[for="${id}"]`) : null;
      return !(el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || (el.textContent || '').trim() || (lab && (lab.textContent || '').trim()) || el.getAttribute('title'));
    }).map((e) => (e as HTMLElement).id || (e as HTMLElement).outerHTML.slice(0, 80)));
    expect(unnamed).toEqual([]);
    // keyboard focus is visible on an accordion header
    await page.locator('#rv-acc-adv-btn').focus(); await page.keyboard.press('Shift+Tab'); await page.keyboard.press('Tab');
    const outline = await page.locator('#rv-acc-adv-btn').evaluate((e) => getComputedStyle(e).outlineStyle + ' ' + getComputedStyle(e).outlineWidth);
    expect(outline).not.toMatch(/^none/);
    // axe: no serious / critical violations in the page with everything open
    const res = await new AxeBuilder({ page }).include('#page-reverse').analyze();
    const serious = res.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
    expect(serious.map((v) => v.id + ': ' + v.nodes.slice(0, 2).map((n) => n.target.join(' ')).join(' | '))).toEqual([]);
  });

  test('131 narrow widths: the rail is a drawer with Run and Export inside it; Escape closes it and focus returns to Setup', async ({ page }) => {
    // narrow: the rail is a drawer, Escape closes it and focus returns to Setup
    await open(page, J1, 'flange', 1000, 800);
    await page.locator('#rv-setup-btn').click(); await expect(page.locator('#rv-setup')).toBeVisible();
    await expect(page.locator('#rv-run-sel')).toBeVisible(); await expect(page.locator('#rv-export')).toBeVisible();
    await shot(page, 'after-narrow-rail-1000x800.png');
    // (a screenshot briefly resizes the emulated viewport, which can flip the rail's media-query state: open it again before testing Escape)
    if (!(await page.locator('#rv-setup').isVisible())) await page.locator('#rv-setup-btn').click();
    await expect(page.locator('#rv-setup')).toBeVisible();
    await page.keyboard.press('Escape'); await expect(page.locator('#rv-setup')).toBeHidden(); await expect(page.locator('#rv-setup-btn')).toBeFocused();
  });
});
