import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { execFileSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { STAGE2_OUT, uniq } from '../helpers/stage3';

test.skip(!STAGE2_OUT, 'STAGE2_OUT not set: start the server with MCAGENT_FINAL_OUTPUTS=$STAGE2_OUT and export STAGE2_OUT');

const VERIFY = path.resolve(__dirname, '../../../docs/verification/v4');
const serious = (res: any) => res.violations.filter((v: any) => v.impact === 'serious' || v.impact === 'critical');
const shot = async (page: any, name: string) => { fs.mkdirSync(VERIFY, { recursive: true }); await page.screenshot({ path: path.join(VERIFY, name) }); };

/** An IR build exactly as the pipeline writes it: plan.json is {dims, plan:{features}} (NO "steps" array) and ir_report.json holds sw_features. */
function irBuild(part: string, sw: Record<string, string>, extra: any = {}) {
  const out = path.join(STAGE2_OUT, part); fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(path.join(out, 'plan.json'), JSON.stringify({
    dims: { D001: 8, D002: 0.5, D010: 3.501, D099: 7 }, reference_ids: ['D002'],
    plan: { ir_version: '2.0', part, frame: { origin_kind: 'axis_end', units: 'inch', view_map: { front: '-Z' } }, notes: ['Planner note one'], features: [
      { id: 'F001', kind: 'revolve', op: 'add', rationale: 'Turn the cylindrical shaft along Z.', source_callouts: ['8.000', '3.501 DIA'], outer: [{ z: '0', r: 'D010 / 2' }, { z: 'D001', r: 'D010 / 2' }] },
      { id: 'F002', kind: 'prism', op: 'cut', rationale: 'Cut the entrance recess.', depth: 'D001 / 4', profile: { shape: 'rect', w: 'D010', h: 'D002' }, justification: 'Section A-A shows the floor.' },
      { id: 'F003', kind: 'hole', rationale: 'Drill the tapped hole.', diameter: '0.3125', depth: 'D002 * 2' },
      { id: 'F004', kind: 'edge_op', rationale: 'Chamfer the shaft end.' }] } }));
  fs.writeFileSync(path.join(out, 'ir_report.json'), JSON.stringify({ part, sw_ok: true, gate1: 'OK', planned: 4, questions: [], sw_features: sw,
    flagged: ['F002: use the section view to place the floor'], defaults: ['F004: D7 chamfer 0.25'], ...extra }));
  fs.writeFileSync(path.join(out, `${part}_extraction.json`), JSON.stringify({ units: 'inch', features: [], dimensions: [], hole_callouts: [] }));
  return out;
}
async function openPart(page: any, request: any, part: string) {
  const session = (await (await request.post('/api/session')).json()).session as string;
  const up = await request.post('/api/parts', { multipart: { session, part, original: { name: 'd.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 x') } } });
  expect(up.ok()).toBeTruthy();
  await page.goto('/#/home');
  await page.waitForFunction(() => !!(window as any).McA);
  await page.evaluate(([sid, p]: string[]) => { const McA = (window as any).McA; McA.persist.set(McA.persist.KEYS.session, sid); McA.persist.set(McA.persist.KEYS.selected, { session: sid, part: p }); }, [session, part]);
  await page.evaluate(() => { location.hash = '#/workspace'; });
  await page.reload();
  await expect(page.locator('#ws-part')).toHaveText(part, { timeout: 15_000 });
  return session;
}
async function openSection(page: any, id: string) {
  await page.evaluate((sid: string) => (window as any).McA.dom.setUi({ drawerOpen: true, drawerSection: sid, drawerMode: 'results' }), id);
  await expect(page.locator(`#dr-results section[data-sec="${id}"]`)).toBeVisible({ timeout: 15_000 });
  return page.locator(`#dr-results section[data-sec="${id}"]`);
}

test.describe('v4: Build Plan for Feature-IR builds', () => {
  test('72 an IR build shows its operations, SolidWorks status, resolved numbers, flags and dimensions (the tab was empty before)', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = 'Bp' + uniq();
    irBuild(part, { F001: 'built', F002: 'built (2 edges selected)', F003: 'built (Hole Wizard tapped)', F004: 'skipped: nothing to chamfer' });
    await openPart(page, request, part);
    const sec = await openSection(page, 'build_plan');
    await expect(sec.locator('.rsec-note.is-warn', { hasText: 'No "steps" array' })).toHaveCount(0);        // the old message every IR build used to show
    await expect(sec.locator('.facts')).toContainText('Feature IR v2.0');
    await expect(sec.locator('.facts')).toContainText('3 of 4 built');
    const ops = sec.locator('ol.ops > li');
    await expect(ops).toHaveCount(4);
    await expect(ops.nth(0)).toContainText('F001');
    await expect(ops.nth(0).locator('details')).toHaveAttribute('data-tone', 'blue');                       // revolve: blue
    await expect(ops.nth(1).locator('details')).toHaveAttribute('data-tone', 'orange');                     // cut: orange
    await expect(ops.nth(2).locator('details')).toHaveAttribute('data-tone', 'violet');                     // hole: violet
    await expect(ops.nth(3).locator('details')).toHaveAttribute('data-tone', 'amber');                      // edge treatment: amber
    await expect(ops.nth(0).locator('summary .badge-c.ok')).toHaveText('Built');                             // green chip
    await expect(ops.nth(3).locator('summary .badge-c.err')).toHaveText('Skipped');                          // red chip
    await expect(sec.locator('.plan-sum .badge-c.ok')).toContainText('3 built');
    await expect(sec.locator('.plan-sum .badge-c.err')).toContainText('1 skipped');
    await ops.nth(1).locator('summary').click();
    const body = ops.nth(1).locator('.op-body');
    await expect(body).toContainText('built (2 edges selected)');
    await expect(body.locator('tr', { hasText: 'depth' })).toContainText('D001 / 4');
    await expect(body.locator('tr', { hasText: 'depth' }).locator('td.num')).toHaveText('2');               // 8 / 4 resolved
    await expect(body).toContainText('Flag: use the section view');
    await expect(body.locator('.rsec-note.is-warn').first()).toBeVisible();
    await ops.nth(0).locator('summary').click();
    await expect(ops.nth(0).locator('tr', { hasText: 'outer[1].r' }).locator('td.num')).toHaveText('1.7505');
    await expect(ops.nth(0).locator('.op-co .badge-c')).toHaveCount(2);                                      // drawing callouts
    const dims = sec.locator('details.op-dims');
    await dims.locator('summary').click();
    await expect(dims.locator('tr', { hasText: 'D099' })).toContainText('unused');
    await expect(dims.locator('tr', { hasText: 'D002' })).toContainText('reference only');
    await expect(sec).toContainText('Planner notes');
    await shot(page, 'build-plan-ir-1440x900.png');
    expect(serious(await new AxeBuilder({ page }).include('#dr-results section[data-sec="build_plan"]').analyze())).toEqual([]);
  });

  test('73 search filters operations; the Raw toggle still shows the file; a legacy v1 plan still renders its steps', async ({ page, request }) => {
    const part = 'Bq' + uniq();
    irBuild(part, { F001: 'built', F002: 'built', F003: 'built', F004: 'built' });
    await openPart(page, request, part);
    const sec = await openSection(page, 'build_plan');
    await sec.getByLabel('Search build_plan').fill('recess');
    await expect(sec.locator('ol.ops > li')).toHaveCount(1);
    await expect(sec).toContainText('1 of 4 operations');
    await sec.getByLabel('Search build_plan').fill('');
    await sec.getByRole('button', { name: 'Raw' }).click();
    await expect(sec.locator('pre, .rawtxt').first()).toContainText('"features"');
    // legacy shape
    const legacy = 'Bl' + uniq();
    const out = path.join(STAGE2_OUT, legacy); fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, `${legacy}_build_plan.json`), JSON.stringify({ part: legacy, units: 'mm', steps: [{ seq: 1, type: 'extrude', description: 'Base block', status: 'generated' }, { seq: 2, type: 'hole', description: 'Drill', status: 'skipped' }] }));
    await openPart(page, request, legacy);
    const sec2 = await openSection(page, 'build_plan');
    await expect(sec2.locator('ol.ops > li')).toHaveCount(2);
    await expect(sec2.locator('summary .badge-c.ok')).toHaveText('generated');
    await expect(sec2.locator('summary .badge-c.err')).toHaveText('skipped');
  });

  test('74 the Projects run list now counts plan.json as a build plan (the Plan badge was off for every IR build)', async ({ page, request }) => {
    const part = 'Bz' + uniq();
    irBuild(part, { F001: 'built' });
    await openPart(page, request, part);
    const runs = (await (await request.get('/api/run-history')).json()).runs as any[];
    const mine = runs.find((r) => r.part === part);
    expect(mine, 'the part appears in run history').toBeTruthy();
    expect(mine.present.build_plan).toBe(true);
  });
});

test.describe('v4: colour coding throughout', () => {
  test('75 results navigation dots and section headers carry each section\'s health tone', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const ok = 'Cg' + uniq(), bad = 'Cr' + uniq();
    irBuild(ok, { F001: 'built', F002: 'built', F003: 'built', F004: 'built' });
    irBuild(bad, { F001: 'built', F002: 'skipped: no selection', F003: 'failed', F004: 'failed' });
    await openPart(page, request, ok);
    let sec = await openSection(page, 'build_plan');
    await expect(sec).toHaveAttribute('data-tone', 'green');
    await expect(sec.locator('.rsec-status')).toHaveText('all built');
    await expect(sec.locator('.rsec-status')).toHaveClass(/band-green/);
    await expect(page.locator('#dr-results .res-link[data-sec="build_plan"]')).toHaveAttribute('data-tone', 'green');
    await expect(page.locator('#dr-results .res-link[data-sec="build_plan"] .res-dot')).toHaveCSS('background-color', 'rgb(79, 191, 88)');
    await openPart(page, request, bad);
    sec = await openSection(page, 'build_plan');
    await expect(sec).toHaveAttribute('data-tone', 'orange');
    await expect(sec.locator('.rsec-status')).toContainText('not built');
    await expect(page.locator('#dr-results .res-link[data-sec="build_plan"]')).toHaveAttribute('data-tone', 'orange');
    await expect(page.locator('#dr-results .res-link[data-sec="build_plan"] .res-dot')).toHaveCSS('background-color', 'rgb(232, 120, 43)');
    await expect(sec.locator('details.op[data-status="failed"]').first()).toBeVisible();                       // failed operations are tinted red
    await shot(page, 'results-tones-1440x900.png');
  });

  test('76 the Files table colours each deliverable type, and the Scoring tab colours rows, items and issue codes', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = 'Cs' + uniq();
    execFileSync(process.env.PYTHON || 'python', [path.resolve(__dirname, '../helpers/make_scored_part.py'), STAGE2_OUT, part, 'badhole'], { encoding: 'utf-8', env: { ...process.env, PYTHONUTF8: '1' } });
    await openPart(page, request, part);
    const files = await openSection(page, 'files');
    await expect(files.locator('.ft-dot').first()).toBeVisible();
    const colours = await files.locator('tr', { hasText: 'x_ir.STL' }).locator('.ft-dot').evaluate((e: HTMLElement) => getComputedStyle(e).backgroundColor);
    const sld = await files.locator('tr', { hasText: 'x_ir.SLDPRT' }).locator('.ft-dot').evaluate((e: HTMLElement) => getComputedStyle(e).backgroundColor);
    expect(colours).not.toBe(sld);                                                                              // STL and SLDPRT have different colours
    await page.goto('/#/scoring');
    await page.getByRole('tab', { name: 'Part results' }).click();
    const row = page.locator('.sc-tbl tr', { hasText: part });
    await row.getByRole('button', { name: 'Evaluate' }).click();
    await expect(row.locator('.sc-score-n')).toBeVisible({ timeout: 60_000 });
    const band = await row.getAttribute('data-band');
    expect(['amber', 'orange', 'red']).toContain(band);
    expect(await row.locator('td').first().evaluate((e: HTMLElement) => getComputedStyle(e).boxShadow)).not.toBe('none');   // coloured band accent on the row
    await row.getByRole('button', { name: 'Details' }).click();
    const det = page.locator('.sc-detail');
    await expect(det.locator('.sc-cat-k').first()).toBeVisible();
    const keys = await det.locator('.sc-cat-k').evaluateAll((els) => els.map((e) => getComputedStyle(e).backgroundColor));
    expect(new Set(keys).size).toBe(6);                                                                         // six categories, six colours
    await det.locator('.sc-det', { hasText: 'Hole and bore accuracy' }).evaluate((e: HTMLDetailsElement) => { e.open = true; });      // categories scoring under 90 open by themselves
    await expect(det.locator('.sc-items tbody tr.row-red, .sc-items tbody tr.row-orange, .sc-items tbody tr.row-amber').first()).toBeVisible();
    const code = det.locator('.sc-iss .sc-code', { hasText: 'HOLE_DIAMETER' }).first();
    await expect(code).toBeVisible();
    expect(await code.evaluate((e: HTMLElement) => getComputedStyle(e).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)');
    await expect(det.locator('.sc-hole-t.thru').first()).toBeVisible();
    await shot(page, 'scoring-colour-detail-1440x900.png');
    await page.getByRole('button', { name: 'All parts' }).click();
    await page.getByRole('tab', { name: 'Scoring methodology' }).click();
    await expect(page.locator('.sc-wbar .sc-wbar-s')).toHaveCount(6);
    const wcol = await page.locator('.sc-wbar .sc-wbar-s').evaluateAll((els) => els.map((e) => getComputedStyle(e).backgroundColor));
    expect(new Set(wcol).size).toBe(6);
    await shot(page, 'scoring-colour-methodology-1440x900.png');
    expect(serious(await new AxeBuilder({ page }).include('#page-scoring').analyze())).toEqual([]);
  });
});
