import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { execFileSync } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { STAGE2_OUT, uniq } from '../helpers/stage3';

test.skip(!STAGE2_OUT, 'STAGE2_OUT not set: start the server with MCAGENT_FINAL_OUTPUTS=$STAGE2_OUT and export STAGE2_OUT');

const VERIFY = path.resolve(__dirname, '../../../docs/verification/v4');
const serious = (res: any) => res.violations.filter((v: any) => v.impact === 'serious' || v.impact === 'critical');
const shot = async (page: any, name: string) => { fs.mkdirSync(VERIFY, { recursive: true }); await page.screenshot({ path: path.join(VERIFY, name) }); };

function batchFolder() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'v4batch-'));
  const out = execFileSync(process.env.PYTHON || 'python', [path.resolve(__dirname, '../helpers/make_batch_folder.py'), path.join(dir, 'drawings')], { encoding: 'utf-8', env: { ...process.env, PYTHONUTF8: '1' } });
  return JSON.parse(out.trim().split('\n').pop()!);
}
async function newSessionPage(page: any, request: any) {
  const session = (await (await request.post('/api/session')).json()).session as string;
  await page.goto('/#/home');
  await page.waitForFunction(() => !!(window as any).McA);
  await page.evaluate((sid: string) => { const McA = (window as any).McA; McA.persist.set(McA.persist.KEYS.session, sid); }, session);
  await page.reload();
  await page.waitForFunction(() => !!(window as any).McA && (window as any).McA.store.get().session.id);
  return session;
}
/** Run history the estimate is computed from: three completed runs (2, 3 and 4 minutes) with priced ledger rows. */
function seedHistory(part: string) {
  const dir = path.join(STAGE2_OUT, part); fs.mkdirSync(dir, { recursive: true });
  const ev: any[] = [], led: any[] = [];
  [[120, 0.10], [180, 0.15], [240, 0.20]].forEach(([sec, cost], i) => {
    const rid = `run_v4_${part}_${i}`, t0 = Date.UTC(2026, 10, 1 + i, 10, 0, 0);
    ev.push({ run_id: rid, attempt: 1, part_id: part, kind: 'run.started', occurred_at: new Date(t0).toISOString() });
    ev.push({ run_id: rid, attempt: 1, part_id: part, kind: 'run.completed', occurred_at: new Date(t0 + sec * 1000).toISOString() });
    led.push({ run_id: rid, run_attempt: 1, part, cost_usd: cost, priced: true, row_id: 'r' + rid });
  });
  fs.writeFileSync(path.join(dir, 'run_events.jsonl'), ev.map((e) => JSON.stringify(e)).join('\n') + '\n');
  fs.mkdirSync(path.join(STAGE2_OUT, 'usage'), { recursive: true });
  fs.appendFileSync(path.join(STAGE2_OUT, 'usage', 'usage_ledger.jsonl'), led.map((e) => JSON.stringify(e)).join('\n') + '\n');
}

test.describe('v4: batch folders (PDF and images)', () => {
  test('61 a mixed folder: counts, page totals, skipped files named, bad files flagged, valid ones become parts', async ({ page, request }) => {
    await newSessionPage(page, request);
    const fx = batchFolder();
    await page.goto('/#/home');
    await page.setInputFiles('#home-folder', fx.dir);
    const sum = page.locator('#home-staged-sum');
    await expect(sum).toBeVisible({ timeout: 20_000 });
    await expect(sum.locator('.st-sum')).toContainText('5 supported inputs', { timeout: 20_000 });
    await expect(sum.locator('.st-sum')).toContainText('6 pages in total');          // 2 + 1 + 1 + 1 + 1: each image is one page
    await expect(sum.locator('.st-sum')).toContainText('2 cannot be used');
    await expect(sum).toContainText('empty.pdf');
    await expect(sum).toContainText('notes.docx');
    await expect(sum).not.toContainText('.DS_Store');                                // hidden files are ignored quietly
    const items = page.locator('#home-staged li');
    await expect(items).toHaveCount(7);
    await expect(items.filter({ hasText: 'corrupt.pdf' }).locator('.st-p')).toContainText(/could not be read|not a PDF/i);
    await expect(items.filter({ hasText: 'renamed.pdf' }).locator('.st-p')).toContainText('content is PNG');
    await expect(items.filter({ hasText: 'Alpha_Bracket_rev_2' })).toContainText('2 pages');
    await expect(items.filter({ hasText: 'BETA' })).toContainText('PDF');
    await expect(page.locator('#home-create-label')).toHaveText('Create 5 3D models');
    await shot(page, 'batch-preflight-1440x900.png');
    expect(serious(await new AxeBuilder({ page }).include('#page-home').analyze())).toEqual([]);

    await page.locator('#home-create').click();
    await page.waitForURL(/#\/projects/, { timeout: 60_000 });
    for (const name of fx.valid) await expect(page.locator('.pcard-n', { hasText: new RegExp('^' + name + '$') })).toBeVisible({ timeout: 20_000 });
    await expect(page.locator('.pcard-n', { hasText: 'corrupt' })).toHaveCount(0);
  });

  test('62 an empty folder and an all-unsupported folder give actionable errors and nothing is staged', async ({ page, request }) => {
    await newSessionPage(page, request);
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'v4none-')); const f = path.join(dir, 'only'); fs.mkdirSync(f);
    fs.writeFileSync(path.join(f, 'readme.docx'), 'x'); fs.writeFileSync(path.join(f, 'model.step'), 'x');
    await page.goto('/#/home');
    await page.setInputFiles('#home-folder', f);
    await expect(page.locator('.toast').filter({ hasText: 'No supported files in that folder' })).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('#home-staged li')).toHaveCount(0);
    await expect(page.locator('#home-create')).toHaveAttribute('aria-disabled', 'true');
  });
});

test.describe('v4: Projects previews and order', () => {
  test('63 real first-page previews, newest activity first, timestamps shown and kept after reload', async ({ page, request }) => {
    const session = await newSessionPage(page, request);
    const fx = batchFolder();
    const pdf = path.join(fx.dir, 'Alpha Bracket (rev 2).pdf'), png = path.join(fx.dir, 'gamma.PNG');
    const mk = async (part: string, file: string, mime: string) => {
      const r = await request.post('/api/parts', { multipart: { session, part, original: { name: path.basename(file), mimeType: mime, buffer: fs.readFileSync(file) } } });
      expect(r.ok()).toBeTruthy();
    };
    await mk('PrevOld', pdf, 'application/pdf');
    await new Promise((r) => setTimeout(r, 1200));
    await mk('PrevMid', png, 'image/png');
    await new Promise((r) => setTimeout(r, 1200));
    await mk('PrevNew', pdf, 'application/pdf');
    await page.goto('/#/projects');
    await page.reload();
    const cards = page.locator('#proj-body .pcard');
    await expect(cards.first()).toBeVisible({ timeout: 15_000 });
    const names = await cards.locator('.pcard-n').allTextContents();
    expect(names.indexOf('PrevNew')).toBeLessThan(names.indexOf('PrevMid'));
    expect(names.indexOf('PrevMid')).toBeLessThan(names.indexOf('PrevOld'));            // newest first, not alphabetical
    const card = (n: string) => cards.filter({ has: page.locator('.pcard-n', { hasText: new RegExp('^' + n + '$') }) });
    for (const n of ['PrevNew', 'PrevMid', 'PrevOld']) {
      const th = card(n).locator('.pcard-th');
      await expect(th).toHaveAttribute('data-state', 'preview', { timeout: 20_000 });
      const dims = await th.locator('img').evaluate((i: HTMLImageElement) => ({ w: i.naturalWidth, h: i.naturalHeight, fit: getComputedStyle(i).objectFit }));
      expect(dims.w).toBeGreaterThan(200); expect(dims.fit).toBe('contain');             // whole sheet, never cropped
      await expect(card(n).locator('time.pcard-when')).toHaveAttribute('datetime', /^\d{4}-\d\d-\d\dT/);
      await expect(card(n).locator('time.pcard-when')).not.toHaveText('Date unknown');
    }
    // a PDF source renders a real picture, not the blank file icon: the PNG response is a real image
    const res = await request.get(`/api/parts/${session}/PrevNew/preview.png`);
    expect(res.status()).toBe(200); expect(res.headers()['content-type']).toBe('image/png');
    await shot(page, 'projects-previews-1440x900.png');
    await page.reload();
    await expect(page.locator('#proj-body .pcard .pcard-n')).toHaveCount(3, { timeout: 15_000 });                 // wait for the cards before reading their order
    const again = await page.locator('#proj-body .pcard .pcard-n').allTextContents();
    expect(again.slice(0, 3)).toEqual(['PrevNew', 'PrevMid', 'PrevOld']);               // order survives a reload
    await card('PrevMid').locator('.pcard-th').click();                                   // clicking the preview opens that project
    await expect(page.locator('#ws-part')).toHaveText('PrevMid', { timeout: 15_000 });
    expect(serious(await new AxeBuilder({ page }).analyze())).toEqual([]);
  });

  test('64 a corrupt source shows the labelled fallback and does not break the page', async ({ page, request }) => {
    const session = await newSessionPage(page, request);
    const r = await request.post('/api/parts', { multipart: { session, part: 'BadSrc', original: { name: 'x.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 broken') } } });
    expect(r.ok()).toBeTruthy();
    await page.goto('/#/projects'); await page.reload();
    const th = page.locator('#proj-body .pcard', { has: page.locator('.pcard-n', { hasText: /^BadSrc$/ }) }).locator('.pcard-th');
    await expect(th).toHaveAttribute('data-state', 'unavailable', { timeout: 20_000 });
    await expect(th).toContainText('Preview unavailable');
    await expect(page.locator('#proj-body .pgrid')).toBeVisible();
  });
});

test.describe('v4: Run Pipeline estimates', () => {
  test('65 estimate shows time and cost ranges from finished runs, a batch total, and recomputes on selection', async ({ page, request }) => {
    const session = await newSessionPage(page, request);
    seedHistory(uniq());
    const fx = batchFolder();
    for (const p of ['EstA', 'EstB']) await request.post('/api/parts', { multipart: { session, part: p, original: { name: 'a.pdf', mimeType: 'application/pdf', buffer: fs.readFileSync(path.join(fx.dir, 'BETA.PDF')) } } });
    await page.evaluate(([sid]: string[]) => { const McA = (window as any).McA; McA.persist.set(McA.persist.KEYS.selected, { session: sid, part: 'EstA' }); }, [session]);
    await page.goto('/#/workspace'); await page.reload();
    const box = page.locator('#run-estimate');
    await expect(box).toBeVisible();
    await expect(page.locator('#est-time')).toHaveText(/^Estimated time: .*min/, { timeout: 15_000 });
    await expect(page.locator('#est-cost')).toHaveText(/^Estimated cost: \$\d+\.\d\d.\$\d+\.\d\d$/);
    await expect(page.locator('#est-detail')).toContainText('1 input');
    await expect(page.locator('#est-detail')).toContainText('Run All Parts (2)');
    await expect(page.locator('#est-detail')).toContainText('one part at a time');
    const y = (await page.locator('#run-btn').boundingBox())!.y, ey = (await box.boundingBox())!.y;
    expect(ey).toBeGreaterThan(y);                                                         // placed beneath the Run Pipeline button
    await expect(page.locator('#run-btn')).toHaveCSS('background-color', 'rgb(214, 175, 107)');   // champagne gold preserved
    await shot(page, 'workspace-estimate-1440x900.png');
    // switching the selected part recomputes (and a stale slow answer never wins)
    let calls = 0;
    await page.route('**/api/estimate**', async (route) => { calls++; if (calls === 1) await new Promise((r) => setTimeout(r, 1500)); await route.continue(); });
    await page.evaluate(([sid]: string[]) => { const McA = (window as any).McA; McA.store.dispatch('parts/select', { session: sid, part: 'EstB' }); }, [session]);
    await page.evaluate(([sid]: string[]) => { const McA = (window as any).McA; McA.store.dispatch('parts/select', { session: sid, part: 'EstA' }); }, [session]);
    await expect(page.locator('#est-time')).toHaveText(/^Estimated time: .*min/, { timeout: 15_000 });
    expect(calls).toBeGreaterThanOrEqual(2);
  });

  test('66 no history is "insufficient history" and an unpriced model is "unavailable", never $0.00', async ({ page, request }) => {
    const session = await newSessionPage(page, request);
    await page.route('**/api/estimate**', (route) => route.fulfill({ json: { inputs: 1, concurrency: 1, serialized_reason: 'x',
      time: { available: false, reason: 'No finished runs to estimate from yet.' }, cost: { available: false, reason: 'No priced runs to estimate from yet (cost is unavailable, not zero).' }, parts: [] } }));
    const fx = batchFolder();
    await request.post('/api/parts', { multipart: { session, part: 'NoHist', original: { name: 'a.pdf', mimeType: 'application/pdf', buffer: fs.readFileSync(path.join(fx.dir, 'BETA.PDF')) } } });
    await page.evaluate(([sid]: string[]) => { const McA = (window as any).McA; McA.persist.set(McA.persist.KEYS.selected, { session: sid, part: 'NoHist' }); }, [session]);
    await page.goto('/#/workspace'); await page.reload();
    await expect(page.locator('#est-time')).toHaveText('Estimated time: insufficient history', { timeout: 15_000 });
    await expect(page.locator('#est-cost')).toHaveText('Estimated cost: unavailable');
    await expect(page.locator('#run-estimate')).not.toContainText('$0.00');
  });

  test('67 the last run keeps its actual time and measured cost after a refresh', async ({ page, request }) => {
    const session = await newSessionPage(page, request);
    const part = 'Last' + uniq();
    seedHistory(part);
    const fx = batchFolder();
    await request.post('/api/parts', { multipart: { session, part, original: { name: 'a.pdf', mimeType: 'application/pdf', buffer: fs.readFileSync(path.join(fx.dir, 'BETA.PDF')) } } });
    await page.evaluate(([sid, p]: string[]) => { const McA = (window as any).McA; McA.persist.set(McA.persist.KEYS.selected, { session: sid, part: p }); }, [session, part]);
    await page.goto('/#/workspace'); await page.reload();
    const live = page.locator('#est-live');
    await expect(live).toBeVisible({ timeout: 15_000 });
    await expect(live).toContainText('Last run');
    await expect(live).toContainText('actual 4 min');                                       // the newest seeded run took 240 s
    await expect(live).toContainText('$0.20 (measured)');
    await page.reload();
    await expect(page.locator('#est-live')).toContainText('$0.20 (measured)', { timeout: 15_000 });
    expect(serious(await new AxeBuilder({ page }).include('#run-estimate').analyze())).toEqual([]);
  });
});

function scoredPart(part: string, kind: 'good' | 'stale' | 'badhole' | 'nomesh') {
  execFileSync(process.env.PYTHON || 'python', [path.resolve(__dirname, '../helpers/make_scored_part.py'), STAGE2_OUT, part, kind], { encoding: 'utf-8', env: { ...process.env, PYTHONUTF8: '1' } });
}

test.describe('v4: Scoring tab (Extraction-to-Model Fidelity)', () => {
  test('68 the sidebar has Scoring; overview, results, methodology and the labelled example render with colour bands', async ({ page, request }) => {
    await newSessionPage(page, request);
    const good = 'Sg' + uniq(), bad = 'Sb' + uniq();
    scoredPart(good, 'good'); scoredPart(bad, 'stale');
    const pending = 'Sp' + uniq();
    const dir = path.join(STAGE2_OUT, pending); fs.mkdirSync(dir, { recursive: true }); fs.writeFileSync(path.join(dir, pending + '_extraction.json'), '{}');
    const ev = await request.post('/api/scoring/evaluate', { data: { parts: [good, bad] } });
    expect(ev.ok()).toBeTruthy();
    await page.goto('/#/home');
    await page.locator('#sidebar a.sb-item[data-page="scoring"]').click();
    await expect(page).toHaveURL(/#\/scoring/);
    await expect(page.locator('#sidebar a.sb-item[data-page="scoring"]')).toHaveAttribute('aria-current', 'page');
    await expect(page.locator('#page-scoring h1')).toHaveText('Scoring');
    await expect(page.locator('.sc-stat')).toHaveCount(5, { timeout: 15_000 });
    await expect(page.locator('.sc-stat', { hasText: 'Rubric' }).last()).toContainText('emf-');
    await expect(page.locator('.sc-legend .band-pill')).toHaveCount(6);                       // Poor to Perfect, each with a word
    await expect(page.locator('.sc-dist')).toBeVisible();
    await expect(page.locator('.sc-attn li', { hasText: bad })).toBeVisible();
    await shot(page, 'scoring-overview-1440x900.png');

    await page.getByRole('tab', { name: 'Part results' }).click();
    const gRow = page.locator('.sc-tbl tr', { hasText: good }), bRow = page.locator('.sc-tbl tr', { hasText: bad }), pRow = page.locator('.sc-tbl tr', { hasText: pending });
    await expect(gRow).toHaveAttribute('data-band', /^(excellent|perfect)$/);
    await expect(gRow.locator('.sc-score-n')).toHaveText(/^(9\d|100)(\.\d)?$/);
    await expect(gRow.locator('.band-pill').first()).toContainText(/Excellent|Perfect/);
    await expect(bRow).toHaveAttribute('data-band', /^(poor|below)$/);
    await expect(bRow.locator('.sev-pill.sev-critical')).toBeVisible();
    await expect(bRow.locator('.band-pill').first()).toContainText(/Poor|Below Average/);
    await expect(gRow.locator('.sc-strip-c')).toHaveCount(6);
    await expect(pRow).toContainText('Pending evaluation');
    await expect(pRow.locator('.sc-score-n')).toHaveCount(0);                                  // not evaluated: no number, never 0
    await page.getByLabel('Search part results').fill('zzz-nothing');
    await expect(page.locator('.sc-tbl')).toHaveCount(0);
    await page.getByLabel('Search part results').fill(good);
    await expect(page.locator('.sc-tbl tr', { hasText: good })).toBeVisible();
    await page.getByLabel('Search part results').fill('');
    await shot(page, 'scoring-results-1440x900.png');

    await page.getByRole('tab', { name: 'Scoring methodology' }).click();
    await expect(page.locator('.sc-method')).toContainText('Total possible: 100 points', { timeout: 15_000 });
    await expect(page.locator('.sc-method')).toContainText('Extraction-to-Model Fidelity');
    await expect(page.locator('.sc-method table').first()).toContainText('Overall size');
    await expect(page.locator('.sc-method')).toContainText('exp(-(e - 1) /');
    await expect(page.locator('.sc-method')).toContainText('Grading spectrum out of 100');
    await shot(page, 'scoring-methodology-1440x900.png');

    await page.getByRole('tab', { name: 'Worked example' }).click();
    const ex = page.locator('.sc-example');
    await expect(ex).toContainText('Illustrative example, not a measured part', { timeout: 15_000 });
    await expect(ex.locator('tr', { hasText: 'Everything matches the drawing' })).toContainText('100.0');
    await expect(ex.locator('tr', { hasText: 'Everything matches the drawing' }).locator('.band-pill')).toContainText('Perfect');
    await expect(ex.locator('tr', { hasText: 'critical gate' })).toContainText('49.9');
    await expect(ex.locator('tr', { hasText: 'critical gate' }).locator('.band-pill')).toContainText('Below Average');
    await shot(page, 'scoring-example-1440x900.png');
    expect(serious(await new AxeBuilder({ page }).include('#page-scoring').analyze())).toEqual([]);
  });

  test('69 part detail: score ring, six coloured categories, issues by severity, what was checked, history', async ({ page, request }) => {
    await newSessionPage(page, request);
    const part = 'Sd' + uniq();
    scoredPart(part, 'badhole');
    await page.goto('/#/scoring');
    await page.getByRole('tab', { name: 'Part results' }).click();
    const row = page.locator('.sc-tbl tr', { hasText: part });
    await expect(row).toBeVisible({ timeout: 15_000 });
    await row.getByRole('button', { name: 'Evaluate' }).click();
    await expect(row.locator('.sc-score-n')).toBeVisible({ timeout: 60_000 });
    await row.getByRole('button', { name: 'Details' }).click();
    const det = page.locator('.sc-detail');
    await expect(det.locator('.sc-ring')).toBeVisible({ timeout: 15_000 });
    await expect(det.locator('.sc-cat')).toHaveCount(6);
    await expect(det.locator('.sc-cat[data-cat="envelope"] .sc-cat-n')).toHaveText('100');
    await expect(det.locator('.sc-cat[data-cat="envelope"]')).toHaveClass(/band-perfect/);
    await expect(det.locator('.sc-cat[data-cat="hole_accuracy"]')).not.toHaveClass(/band-(perfect|excellent)/);       // the oversize hole costs points
    await expect(det.locator('.sc-iss-g .sev-pill.sev-medium, .sc-iss-g .sev-pill.sev-high').first()).toBeVisible();
    await expect(det).toContainText('HOLE_DIAMETER');
    await expect(det).toContainText('PATTERN_SPACING');
    await expect(det.locator('.sc-det', { hasText: 'Hole and bore accuracy' }).first()).toBeVisible();
    await expect(det).toContainText('Measured on the real SolidWorks part');
    await expect(det).toContainText('Answer-key benchmark (optional)');
    await shot(page, 'scoring-detail-1440x900.png');
    await det.getByRole('button', { name: 'Re-evaluate' }).click();
    await expect(det).toContainText('Evaluation history', { timeout: 60_000 });                         // two stored evaluations, none overwritten
    expect(serious(await new AxeBuilder({ page }).include('#page-scoring').analyze())).toEqual([]);
  });

  test('70 a stale mesh is red with a critical issue; no mesh is Incomplete; no part is its own state', async ({ page, request }) => {
    await newSessionPage(page, request);
    const stale = 'St' + uniq(), nomesh = 'Sn' + uniq(), nopart = 'Sq' + uniq();
    scoredPart(stale, 'stale'); scoredPart(nomesh, 'nomesh');
    const qd = path.join(STAGE2_OUT, nopart); fs.mkdirSync(qd, { recursive: true }); fs.writeFileSync(path.join(qd, nopart + '_extraction.json'), JSON.stringify({ units: 'inch', features: [], dimensions: [], hole_callouts: [] }));
    await request.post('/api/scoring/evaluate', { data: { parts: [stale, nomesh, nopart] } });
    await page.goto('/#/scoring');
    await page.getByRole('tab', { name: 'Part results' }).click();
    await expect(page.locator('.sc-tbl tr', { hasText: nomesh })).toContainText('Incomplete: No exported STL', { timeout: 15_000 });
    await expect(page.locator('.sc-tbl tr', { hasText: nomesh }).locator('.sc-score-n')).toHaveCount(0);
    await expect(page.locator('.sc-tbl tr', { hasText: nopart })).toContainText('Build failed or no part');
    await page.locator('.sc-tbl tr', { hasText: stale }).getByRole('button', { name: 'Details' }).click();
    const det = page.locator('.sc-detail');
    await expect(det.locator('.sc-ring')).toHaveClass(/band-(poor|below)/, { timeout: 15_000 });
    await expect(det.locator('.sc-head')).toContainText('critical');                       // the header names the critical issue; a cap banner appears only when the raw score was above the cap
    const stl = det.locator('.sc-iss.sev-critical', { hasText: 'STL_NOT_THIS_BUILD' });
    await expect(stl).toContainText('not the model that was built');
    await shot(page, 'scoring-stale-red-1440x900.png');
  });

  test('71 narrow layout: Scoring, Projects and the Workspace fit without horizontal scroll', async ({ page, request }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await newSessionPage(page, request);
    for (const hash of ['#/scoring', '#/projects', '#/workspace']) {
      await page.goto('/' + hash); await page.reload();
      await page.waitForTimeout(400);
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(over, hash).toBeLessThanOrEqual(1);
    }
    await shot(page, 'scoring-narrow-390x844.png');
  });
});
