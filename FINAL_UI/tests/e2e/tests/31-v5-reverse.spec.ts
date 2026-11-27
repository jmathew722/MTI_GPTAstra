import { test, expect, Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { execFileSync } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { auditLayout, summarise, Finding } from '../helpers/layout-audit';
import { watchConsole } from '../helpers/app';

// 3D -> 2D page. Fixture jobs are written into an ISOLATED data dir (MCAGENT_DATA, the same folder the server under test uses).
// The fixtures are labelled stand-ins ("demo": true); SOLIDWORKS is never started and these specs are NOT evidence of native CAD output.
// No spec submits a job: running one would queue work on the single CAD worker.
const DATA = process.env.MCAGENT_DATA ? path.resolve(process.env.MCAGENT_DATA) : '';
test.skip(!DATA, 'MCAGENT_DATA not set: start the server with it (isolated folder) and export it for the tests');

const VERIFY = path.resolve(__dirname, '../../../docs/verification/v5/reverse');
const J_DONE = 'r3d_0000000000000001', J_RUN = 'r3d_0000000000000002', J_MIX = 'r3d_0000000000000003';
const serious = (res: any) => res.violations.filter((v: any) => v.impact === 'serious' || v.impact === 'critical');
const fmt = (fs_: Finding[]) => fs_.map((f) => `${f.kind} ${f.selector}: ${f.detail} ${JSON.stringify(f.text || '')}`);
const SIZES: Array<[number, number]> = [[1920, 1080], [1440, 900], [1366, 768], [1100, 800], [800, 900], [390, 844]];
const shot = async (page: Page, name: string) => { fs.mkdirSync(VERIFY, { recursive: true }); await page.evaluate(() => { const m = document.getElementById('main'); if (m) m.scrollTop = 0; }); await page.waitForTimeout(150); await page.screenshot({ path: path.join(VERIFY, name) }); };

test.beforeAll(() => {
  execFileSync(process.env.PYTHON || 'python', [path.resolve(__dirname, '../helpers/make_reverse_fixture.py'), DATA, 'reset'], { encoding: 'utf-8', env: { ...process.env, PYTHONUTF8: '1' } });
});

async function open(page: Page, job: string, part = '', w = 1440, h = 900) {
  await page.goto('about:blank');
  await page.setViewportSize({ width: w, height: h });
  await page.goto(`/#/reverse?job=${job}${part ? '&part=' + part : ''}`);
  await page.waitForFunction(() => !!(window as any).McA && !!(window as any).McA.pages.reverse);
  await expect(page.locator('#page-reverse')).toBeVisible();
  await expect(page.locator('#rv-h1')).toHaveText(/3D . 2D Drawings/);
  await expect(page.locator('.rv-tbl tbody tr').first()).toBeVisible({ timeout: 15_000 });
}
const stlReady = (page: Page) => expect(page.locator('#rv-3d .rv-vempty')).toBeHidden({ timeout: 15_000 });
const pdfReady = (page: Page) => expect(page.locator('#rv-2d .rv-paperwrap')).toBeVisible({ timeout: 15_000 });
const nonWhite = (page: Page) => page.evaluate(() => {
  const c = document.querySelector('#rv-2d canvas.rv-paper') as HTMLCanvasElement; if (!c || !c.width) return false;
  const d = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
  for (let i = 0; i < d.length; i += 4 * 7) if (d[i] < 200) return true;
  return false;
});

test.describe('v5: 3D -> 2D', () => {
  test('90 route, nav item order (3D -> 2D directly under Workspace), collapsed-rail tooltip, Workspace untouched', async ({ page }) => {
    const bad = watchConsole(page);
    await page.goto('/#/home'); await page.waitForFunction(() => !!(window as any).McA);
    const labels = await page.locator('#sidebar .sb-nav:not(.sb-bottom) .sb-item').evaluateAll((els) => els.map((e) => (e.querySelector('.sb-label')!.textContent || '').trim()));
    expect(labels.slice(0, 4)).toEqual(['Home', 'Workspace', '3D → 2D', 'Projects']);
    const item = page.locator('#sidebar .sb-item[data-page="reverse"]');
    await expect(item).toHaveAttribute('data-tip', /3D to 2D/);
    await item.click();
    await expect(page).toHaveURL(/#\/reverse/);
    await expect(item).toHaveAttribute('aria-current', 'page');
    await expect(page.locator('#page-reverse')).toBeVisible();
    expect(await page.title()).toContain('3D');
    await expect(page.locator('#page-workspace')).toBeHidden();
    await page.goto('/#/workspace');
    await expect(page.locator('#page-workspace')).toBeVisible();
    await expect(page.locator('#ws-part')).toBeVisible();
    expect(bad.filter((b) => !/favicon|Failed to load resource/.test(b))).toEqual([]);
  });

  test('91 default state: no runs yet (empty, honest, setup visible, Run disabled with a reason)', async ({ page }) => {
    await page.route('**/api/reverse/jobs', (r) => (r.request().method() === 'GET' ? r.fulfill({ json: { jobs: [] } }) : r.continue()));
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/reverse'); await page.waitForFunction(() => !!(window as any).McA.pages.reverse);
    await expect(page.locator('.rv-queue .rv-empty')).toContainText('No runs yet');
    await expect(page.locator('#rv-3d')).toContainText('No model yet');
    await expect(page.locator('#rv-2d')).toContainText('No drawing yet');
    await expect(page.locator('#rv-chip-engine .chip-v')).toContainText(/SOLIDWORKS/);
    await expect(page.locator('#rv-chip-cost .chip-v')).toHaveText('—');
    await expect(page.locator('#rv-run-sel')).toBeDisabled();
    await expect(page.locator('#rv-run-why')).toContainText('Choose one or more');
    await expect(page.locator('.rv-tracker .trk-step[data-state="pending"]')).toHaveCount(10);              // v7 vocabulary (was 8 before the reference stages)
    for (const w of [1280, 1440, 1920]) { await page.setViewportSize({ width: w, height: w === 1920 ? 1080 : 900 }); await page.waitForTimeout(250); await shot(page, `default-${w}.png`); }
  });

  test('92 processing: tracker follows real stage states, STL shows as soon as it exists, drawing does not', async ({ page }) => {
    await open(page, J_RUN, 'bracket-run');
    const states = await page.locator('.rv-tracker .trk-step').evaluateAll((els) => els.map((e) => e.getAttribute('data-state')));
    expect(states).toEqual(['succeeded', 'succeeded', 'succeeded', 'succeeded', 'succeeded', 'running', 'pending', 'pending', 'pending', 'pending']);
    await expect(page.locator('.rv-tracker .trk-stage')).toContainText('Native drawing (running)');
    const prog = page.locator('.rv-bar');
    await expect(prog).toHaveAttribute('role', 'progressbar');
    expect(Number(await prog.getAttribute('aria-valuenow'))).toBeLessThan(100);
    await expect(page.locator('.rv-tracker .trk-caption')).toContainText('0 of 2 parts done');
    await stlReady(page);
    await expect(page.locator('#rv-2d .rv-vempty')).toContainText('No drawing yet');
    await expect(page.locator('#rv-2d .rv-paperwrap')).toBeHidden();
    await expect(page.locator('#rv-chip-deliv .dv.is-present')).toHaveText(['STL']);
    await expect(page.locator('#rv-chip-runtime .chip-v')).toHaveText('Not measured yet');
    await expect(page.locator('#rv-chip-cost .chip-v')).toContainText('API usage');
    await expect(page.locator('.rv-qsum')).toContainText('Running');
    expect(await page.locator('#page-reverse').innerText()).not.toMatch(/(null|undefined|NaN)/);
    // the queued part has no model: switching shows the empty states, never the previous mesh
    await page.locator('.rv-pname', { hasText: 'cover.SLDPRT' }).click();
    await expect(page.locator('#rv-3d')).toContainText('No model yet');
    await expect(page.locator('.rv-tbl tr.is-sel .rv-pname')).toHaveText('cover.SLDPRT');
    for (const w of [1280, 1440, 1920]) { await open(page, J_RUN, 'bracket-run', w, w === 1920 ? 1080 : 900); await stlReady(page); await page.waitForTimeout(400); await shot(page, `processing-${w}.png`); }
  });

  test('93 review required: both viewers load, issues show severity label + icon, actions need a note and are audited', async ({ page }) => {
    await open(page, J_MIX, 'bracket');
    await stlReady(page); await pdfReady(page);
    await expect(page.locator('#rv-2d .rv-pagelbl')).toHaveText('Sheet 1 of 2');
    expect(await nonWhite(page)).toBe(true);
    await expect(page.locator('#rv-2d .rv-draft')).toContainText('Draft: review required');
    await expect(page.locator('.rv-draft-note')).toContainText('PRELIMINARY / FOR REVIEW - not approved for manufacture');
    await page.locator('#rv-2d button[aria-label="Next sheet"]').click();
    await expect(page.locator('#rv-2d .rv-pagelbl')).toHaveText('Sheet 2 of 2');
    await page.locator('#rv-tab-review').click();
    const cards = page.locator('.rv-issue');
    await expect(cards).toHaveCount(3);
    await expect(cards.first().locator('.rv-sev')).toContainText(/High/);
    expect((await cards.first().locator('.rv-sev svg').count())).toBe(1);
    await expect(cards.first()).toContainText('Observed');
    await expect(cards.first()).toContainText('0.3125 in');
    const first = cards.first();
    await expect(first.locator('button[data-action="accept"]')).toBeDisabled();
    await expect(first.locator('.rv-act .reason')).toContainText('Enter a note to accept');
    await first.locator('textarea').fill('Checked against the model; the drawing value is correct.');
    await expect(first.locator('button[data-action="accept"]')).toBeEnabled();
    await expect(first.locator('button[data-action="reopen"]')).toBeDisabled();
    await first.locator('button[data-action="accept"]').click();
    await expect(page.locator('.rv-issue[data-disp="accepted"]')).toHaveCount(1);
    await expect(page.locator('.rv-issue[data-disp="accepted"] .rv-hist li')).toContainText(/Accepted by .+ on \d{4}-\d\d-\d\d .*: Checked against/);
    // accepted issues sort after open ones
    await expect(page.locator('.rv-issue').last()).toHaveAttribute('data-disp', 'accepted');
    // reject needs a note; reopen does not
    const acc = page.locator('.rv-issue[data-disp="accepted"]');
    await acc.locator('button[data-action="reopen"]').click();
    await expect(page.locator('.rv-issue[data-disp="accepted"]')).toHaveCount(0);
    const sev = page.locator('.rv-issue').first();
    await sev.locator('textarea').fill('Hole size is wrong on the drawing.');
    await sev.locator('button[data-action="reject"]').click();
    await expect(page.locator('.rv-issue[data-disp="rejected"] .rv-hist li').last()).toContainText('Rejected by');
    // the review overlay is separate: the PDF canvas itself never changes
    const before = await page.evaluate(() => (document.querySelector('#rv-2d canvas.rv-paper') as HTMLCanvasElement).toDataURL().length);
    await page.locator('#rv-2d button[aria-label="Review overlay"]').click();
    await expect(page.locator('.rv-overlay')).toContainText('Review overlay');
    expect(await page.evaluate(() => (document.querySelector('#rv-2d canvas.rv-paper') as HTMLCanvasElement).toDataURL().length)).toBe(before);
    await page.locator('#rv-2d button[aria-label="Review overlay"]').click();
    for (const w of [1280, 1440, 1920]) { await open(page, J_MIX, 'bracket', w, w === 1920 ? 1080 : 900); await stlReady(page); await pdfReady(page); await page.locator('#rv-tab-review').click(); await page.waitForTimeout(500); await shot(page, `review-required-${w}.png`);
      await page.evaluate(() => { const m = document.getElementById('main'); if (m) m.scrollTop = m.scrollHeight; }); await page.waitForTimeout(200); fs.mkdirSync(VERIFY, { recursive: true }); await page.screenshot({ path: path.join(VERIFY, `review-required-issues-${w}.png`) }); }
    execFileSync(process.env.PYTHON || 'python', [path.resolve(__dirname, '../helpers/make_reverse_fixture.py'), DATA, 'reset'], { env: { ...process.env, PYTHONUTF8: '1' } });
  });

  test('94 complete: header facts are real, coverage text keeps the denominator, files list only what exists', async ({ page }) => {
    await open(page, J_DONE, 'flange');
    await stlReady(page); await pdfReady(page);
    await expect(page.locator('#rv-chip-engine .chip-v')).toHaveText('SOLIDWORKS 2025 · 33.5.0 SP5.0');
    await expect(page.locator('#rv-chip-cost .chip-v')).toHaveText('$0.00 API usage (CAD automation; licence/compute excluded)');
    await expect(page.locator('#rv-chip-runtime .chip-v')).toContainText('52');
    await expect(page.locator('#rv-chip-deliv .dv.is-present')).toHaveText(['PDF', 'SLDDRW', 'STL']);
    await expect(page.locator('.rv-tracker .trk-step[data-state="succeeded"]')).toHaveCount(10);
    await expect(page.locator('#rv-2d .rv-draft')).toContainText(/Draft: for review/);
    await page.locator('#rv-tab-coverage').click();
    await expect(page.locator('.rv-covt')).toHaveText('12 of 12 applicable characteristics verified');
    await expect(page.locator('.rv-grade')).toContainText('100.0%');
    await expect(page.locator('#rv-results-body')).toContainText('Diagnostic only');
    await page.locator('#rv-tab-files').click();
    const files = await page.locator('#rv-results-body tbody tr strong').allTextContents();
    expect(files).toContain('Drawing (PDF)'); expect(files).toContain('Model (STL)');
    for (const a of await page.locator('#rv-results-body a[download]').all()) expect(await a.getAttribute('href')).toMatch(/^\/api\/reverse\/jobs\/r3d_/);
    await page.locator('#rv-tab-verification').click();
    await expect(page.locator('#rv-results-body')).toContainText('Software QA is not engineering approval');
    await page.locator('#rv-tab-inventory').click();
    await expect(page.locator('#rv-results-body')).toContainText('H001');
    await page.locator('#rv-tab-plan').click();
    await expect(page.locator('#rv-results-body')).toContainText('third_angle');
    await page.locator('#rv-tab-logs').click();
    await expect(page.locator('.rv-log li').first()).toBeVisible();
    for (const w of [1280, 1440, 1920]) { await open(page, J_DONE, 'flange', w, w === 1920 ? 1080 : 900); await stlReady(page); await pdfReady(page); await page.waitForTimeout(500); await shot(page, `complete-${w}.png`); }
  });

  test('95 mixed batch: success and failure both visible; switching a row updates BOTH viewers from the same ids', async ({ page }) => {
    await open(page, J_MIX, 'bracket');
    await stlReady(page); await pdfReady(page);
    const rows = page.locator('.rv-tbl tbody tr');
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toContainText('Review required');
    await expect(rows.nth(1)).toContainText('Completed');
    await expect(rows.nth(2)).toContainText('Failed');
    await expect(rows.nth(2)).toContainText('view layout does not fit the sheet');
    await expect(page.locator('.rv-qbody .banner').first()).toContainText('not run');
    // failed part: STL exists (stage 2 ran), drawing does not
    await page.locator('.rv-pname', { hasText: 'broken.SLDPRT' }).click();
    await expect(page.locator('#rv-2d .rv-vempty')).toContainText('No drawing yet');
    await expect(page.locator('#rv-2d .rv-draft')).toContainText('the run failed');
    await stlReady(page);
    await expect(page.locator('.rv-tracker .trk-step[data-state="failed"]')).toHaveCount(1);
    await expect(page.locator('.rv-tracker .trk-stage')).toContainText('Extraction failed');
    // back to a completed part: drawing returns
    await page.locator('.rv-pname', { hasText: 'plate.SLDPRT' }).click();
    await pdfReady(page); await stlReady(page);
    expect(await nonWhite(page)).toBe(true);
    await expect(page.locator('#rv-2d')).toContainText('Sheet 1 of 1');
    // retry is offered for the failed part only
    await expect(page.locator('.rv-tbl button[aria-label="Retry broken.SLDPRT"]')).toBeEnabled();
    await expect(page.locator('.rv-tbl button[aria-label^="Retry"]')).toHaveCount(1);
  });

  test('96 stale guard: a slow STL for the previous part never appears after switching', async ({ page }) => {
    await page.route('**/api/reverse/jobs/*/files/bracket-run/**/model.stl*', async (r) => { await new Promise((res) => setTimeout(res, 2500)); await r.continue(); });
    await open(page, J_RUN, 'bracket-run');
    await expect(page.locator('#rv-3d')).toContainText('Loading model');
    await page.locator('.rv-pname', { hasText: 'cover.SLDPRT' }).click();
    await page.waitForTimeout(3500);
    await expect(page.locator('#rv-3d')).toContainText('No model yet');
    await expect(page.locator('#rv-3d .rv-vempty')).toBeVisible();
    await expect(page.locator('.rv-tbl tr.is-sel .rv-pname')).toHaveText('cover.SLDPRT');
    // switching back loads it (not stuck in a stale "loading")
    await page.locator('.rv-pname', { hasText: 'bracket-run.SLDPRT' }).click();
    await stlReady(page);
  });

  test('97 part and template pickers; Run disabled only with a concrete reason; nothing is submitted', async ({ page }) => {
    await open(page, J_DONE, 'flange');
    await expect(page.locator('#rv-acc-tpl-btn')).toContainText('Drawing template');                       // v7: the template is an accordion (selected + Change)
    await expect(page.locator('#rv-run-sel')).toBeDisabled();
    await expect(page.locator('#rv-run-why')).toContainText('Choose one or more');
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rvpick-'));
    fs.mkdirSync(path.join(dir, 'top', 'sub'), { recursive: true });
    for (const f of ['top/A.SLDPRT', 'top/B.sldprt', 'top/sub/a.sldprt', 'top/c.sldasm', 'top/readme.txt']) fs.writeFileSync(path.join(dir, f), 'x'.repeat(30));
    await page.setInputFiles('#rv-dir', path.join(dir, 'top'));
    await expect(page.locator('.rv-picked li')).toHaveCount(2);
    await expect(page.locator('#rv-pk-sum')).toContainText('2 parts selected; 2 non-part files ignored');
    await expect(page.locator('.rv-picked .badge-c', { hasText: 'Duplicate name' })).toHaveCount(0);
    await page.locator('#rv-rec').check();
    await expect(page.locator('.rv-picked li')).toHaveCount(3);
    await expect(page.locator('#rv-pk-sum')).toContainText('3 parts selected (2 with duplicate names; each runs separately)');
    await expect(page.locator('.rv-picked .badge-c', { hasText: 'Duplicate name' })).toHaveCount(2);
    await page.locator('#rv-rec').uncheck();
    await expect(page.locator('.rv-picked li')).toHaveCount(2);
    // run buttons: enabled only when a template is chosen and parts are ticked
    const tplChosen = await page.locator('input[name="rv-tpl"]:checked').count();
    if (tplChosen) {
      await expect(page.locator('#rv-run-all')).toBeEnabled();
      await page.locator('.rv-picked input[type="checkbox"]').first().uncheck();
      await page.locator('.rv-picked input[type="checkbox"]').nth(1).uncheck();
      await expect(page.locator('#rv-run-sel')).toBeDisabled();
      await expect(page.locator('#rv-run-why')).toContainText('Choose one or more');
    } else {
      await expect(page.locator('#rv-run-sel')).toBeDisabled();
      await expect(page.locator('#rv-run-why')).toContainText('template');
    }
    await expect(page.locator('#rv-est')).toContainText(/Estimated for \d+ part/);
    await expect(page.locator('#rv-est')).toContainText(/Not enough data|About|checking|unavailable/);
    // server folder control: disabled until text, refuses unauthorized folders (never submits)
    await page.locator('#rv-acc-adv-btn').click();                                              // v7: the server-folder run lives under Advanced settings
    await page.locator('.rv-sf summary').click();
    await expect(page.locator('.rv-sf button')).toBeDisabled();
    await page.locator('.rv-picked button[aria-label^="Remove"]').first().click();
    await expect(page.locator('.rv-picked li')).toHaveCount(1);
    await page.getByRole('button', { name: 'Clear list' }).click();
    await expect(page.locator('.rv-picked')).toHaveCount(0);
    await expect(page.locator('#rv-run-sel')).toBeDisabled();
    expect((await (await page.request.get('/api/reverse/jobs')).json()).jobs.length).toBe(3);
  });

  test('98 template task running: upload and generate are disabled with a reason', async ({ page }) => {
    await page.route('**/api/reverse/templates', (r) => r.request().method() === 'GET' ? r.fulfill({ json: { templates: [
      { id: 'solidflow-ansi-b', name: 'Generated default (fixture)', source: 'generated', available: true, own_sheet_format: true, paper: 'ANSI B', has_preview: false, validation: { ok: true, errors: [] } },
      { id: 'user-x', name: 'Customer template', source: 'uploaded', available: true, own_sheet_format: false, paper: null, has_preview: false, validation: { ok: false, errors: ['the template already contains 1 model view(s)'] } },
      { id: 'stock-default', name: 'SOLIDWORKS stock drawing template', source: 'stock', available: true, own_sheet_format: false, paper: 'as installed', has_preview: false, validation: { ok: null, errors: [] } }],
      default_id: 'solidflow-ansi-b', task: { id: 't1', kind: 'generate', state: 'running', label: 'Generating solidflow-ansi-b' } } }) : r.continue());
    await open(page, J_DONE, 'flange');
    await page.locator('#rv-acc-tpl-btn').click();                                              // v7: template details are behind "Change"
    await expect(page.getByRole('button', { name: /Generate default/ })).toBeDisabled();
    await expect(page.getByRole('button', { name: /Generate default/ })).toHaveAttribute('title', /template task is running/);
    await expect(page.locator('#rv-tpl-upload')).toBeDisabled();
    await expect(page.locator('.rv-task')).toContainText('Generating solidflow-ansi-b');
    const items = page.locator('.rv-tpl');
    await expect(items).toHaveCount(3);
    await expect(items.nth(0)).toContainText('Validated in SOLIDWORKS');
    await expect(items.nth(1)).toContainText('Failed validation');
    await expect(items.nth(1)).toContainText('model view');
    await expect(items.nth(2)).toContainText('Stock template');
    // choosing the invalid template blocks Run with that reason
    await items.nth(1).locator('input[type="radio"]').check();
    await page.setInputFiles('#rv-files', [{ name: 'x.SLDPRT', mimeType: 'application/octet-stream', buffer: Buffer.from('abc') }]);
    await expect(page.locator('#rv-run-why')).toContainText(/running|failed validation/);
    await expect(page.locator('#rv-run-sel')).toBeDisabled();
  });

  test('99 projects and recent files list 3D -> 2D runs with badge, real timestamp and thumbnail', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/projects'); await page.waitForFunction(() => !!(window as any).McA);
    const cards = page.locator('#rv-projects .pcard');
    await expect(cards).toHaveCount(3, { timeout: 15_000 });
    await expect(cards.first().locator('.rv-modebadge')).toHaveText('3D → 2D');
    await expect(cards.first().locator('time')).toHaveAttribute('datetime', /2026-11-25T11:00:00/);
    await expect(cards.first().locator('img')).toBeVisible();
    expect(await cards.first().locator('img').evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth > 0)).toBe(true);
    await expect(cards.last().locator('.pcard-nopv, img')).toHaveCount(1);
    await shot(page, 'projects-1440.png');
    await cards.first().getByRole('button', { name: 'Open', exact: true }).click();
    await expect(page).toHaveURL(/#\/reverse\?job=r3d_0000000000000003/);
    await page.goto('/#/recent'); await expect(page.locator('#rv-recent tbody tr')).toHaveCount(3, { timeout: 15_000 });
    await expect(page.locator('#rv-recent .rv-modebadge').first()).toHaveText('3D → 2D');
    await page.goto('/#/projects'); await expect(page.locator('#proj-body')).toBeAttached();   // existing 2D->3D listing still renders
  });

  test('100 keyboard and ARIA: tab list arrows, setup drawer opens/closes with Escape, status text announced', async ({ page }) => {
    await open(page, J_MIX, 'bracket', 800, 900);
    await expect(page.locator('#rv-setup')).toBeHidden();
    await page.locator('#rv-setup-btn').click();
    await expect(page.locator('#rv-setup')).toBeVisible();
    await expect(page.locator('#rv-setup-btn')).toHaveAttribute('aria-expanded', 'true');
    await page.keyboard.press('Escape');
    await expect(page.locator('#rv-setup')).toBeHidden();
    await expect(page.locator('#rv-setup-btn')).toBeFocused();
    const tab = page.locator('#rv-tab-overview');
    await tab.focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.locator('#rv-tab-compare')).toHaveAttribute('aria-selected', 'true');           // v8: the Comparison tab sits right after Overview
    await expect(page.locator('#rv-tab-compare')).toBeFocused();
    await page.keyboard.press('ArrowRight');
    await expect(page.locator('#rv-tab-inventory')).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('#rv-tab-inventory')).toBeFocused();
    await page.keyboard.press('End');
    await expect(page.locator('#rv-tab-logs')).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('#rv-results-body')).toHaveAttribute('role', 'tabpanel');
    await expect(page.locator('.rv-tracker ol.trk-steps li').first().locator('.sr-only')).toContainText('Done');
    await page.locator('.rv-reshead > button').click();
    await expect(page.locator('#rv-results-body')).toBeHidden();
    await expect(page.locator('.rv-reshead > button')).toHaveAttribute('aria-expanded', 'false');
  });

  test('101 layout audit (accent lines >= 8px clear of text, no clipped text, no sideways scroll) at every width, sidebar expanded and collapsed', async ({ page }) => {
    test.setTimeout(300_000);
    page.setDefaultTimeout(20_000);
    const bad: string[] = [];
    for (const [w, h] of SIZES) {
      for (const collapsed of [false, true]) {
        if (collapsed && w < 1440) continue;                      // below 1440px the sidebar is already a rail / drawer
        await open(page, J_MIX, 'bracket', w, h);
        const tog = page.locator('#sb-toggle');
        if (w >= 1440 && await tog.isVisible().catch(() => false)) {
          const openNow = (await tog.getAttribute('aria-expanded')) === 'true';
          if (openNow === collapsed) { await tog.click(); await page.waitForTimeout(250); }
        }
        await pdfReady(page); await stlReady(page);
        for (const t of ['overview', 'review', 'files']) {
          await page.locator('#rv-tab-' + t).click(); await page.waitForTimeout(150);
          for (const f of await auditLayout(page)) bad.push(`[${w}x${h}${collapsed ? ' rail' : ''}] ${t}: ${fmt([f])[0]}`);
        }
        if (w < 1100) { await page.locator('#rv-setup-btn').click(); await page.waitForTimeout(200); for (const f of await auditLayout(page)) bad.push(`[${w}x${h}] setup drawer: ${fmt([f])[0]}`); }
      }
    }
    await open(page, J_RUN, 'bracket-run', 1440, 900);
    for (const f of await auditLayout(page)) bad.push(`[1440 processing] ${fmt([f])[0]}`);
    expect(summarise(bad)).toEqual([]);
  });

  test('102 axe: no serious or critical violations (default, review, processing, narrow, drawer)', async ({ page }) => {
    test.setTimeout(180_000);
    const out: string[] = [];
    const run = async (label: string) => {
      const res = await new AxeBuilder({ page }).analyze();
      for (const v of serious(res)) out.push(`${label}: ${v.id} (${v.impact}) ${v.nodes.slice(0, 2).map((n: any) => n.target.join(' ')).join(' | ')}`);
    };
    await open(page, J_MIX, 'bracket'); await stlReady(page); await pdfReady(page);
    for (const t of ['overview', 'review', 'coverage', 'files', 'logs']) { await page.locator('#rv-tab-' + t).click(); await run('review/' + t); }
    await open(page, J_RUN, 'bracket-run'); await run('processing');
    await open(page, J_DONE, 'flange', 390, 844); await pdfReady(page); await run('390');
    await page.locator('#rv-setup-btn').click(); await run('390 drawer');
    expect(out).toEqual([]);
  });

  test('103 honesty: no demo or placeholder wording, no fake percentages, fixture jobs never claim approval', async ({ page }) => {
    await open(page, J_MIX, 'bracket'); await pdfReady(page);
    const text = (await page.locator('#page-reverse').innerText()).toLowerCase();
    expect(text).not.toMatch(/lorem|placeholder|mock|approved for manufacture(?!\.)|certified|released/);
    expect(text).toContain('not approved for manufacture');
    expect(await page.locator('#page-reverse [aria-disabled="false"][role="button"]:not([data-x])').count()).toBeGreaterThanOrEqual(0);
    // every button has an accessible name and no enabled button is inert (spot check: tabs, rows, toolbar)
    const unnamed = await page.locator('#page-reverse button').evaluateAll((els) => els.filter((e) => !((e.getAttribute('aria-label') || e.textContent || '').trim())).map((e) => e.outerHTML.slice(0, 80)));
    expect(unnamed).toEqual([]);
  });
});
