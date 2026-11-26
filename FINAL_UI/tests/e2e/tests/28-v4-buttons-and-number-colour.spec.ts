import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import * as fs from 'fs';
import * as path from 'path';
import { STAGE2_OUT, uniq } from '../helpers/stage3';

test.skip(!STAGE2_OUT, 'STAGE2_OUT not set: start the server with MCAGENT_FINAL_OUTPUTS=$STAGE2_OUT and export STAGE2_OUT');

const VERIFY = path.resolve(__dirname, '../../../docs/verification/v4');
const serious = (res: any) => res.violations.filter((v: any) => v.impact === 'serious' || v.impact === 'critical');
const shot = async (page: any, name: string) => { fs.mkdirSync(VERIFY, { recursive: true }); await page.screenshot({ path: path.join(VERIFY, name) }); };
const GRADE_RGB = ['rgb(217, 87, 99)', 'rgb(217, 139, 85)', 'rgb(214, 175, 107)', 'rgb(181, 199, 107)', 'rgb(141, 212, 154)', 'rgb(76, 183, 130)'];
const NEUTRAL = 'rgb(146, 148, 158)';
const WHITE_TEXT = 'rgb(242, 242, 244)';

function row(part: string, score: number | null, state = 'scored') {
  return { part, session: '', has_output: true, has_part: true, run_id: 'run_x', last_activity: 1795123302, state, score, reason: state === 'incomplete' ? 'no_mesh' : undefined, counts: { critical: part === 'P6' ? 1 : 0, high: 0 },
    categories: {}, evaluated_at: '2026-11-25T10:00:00+00:00', fingerprint: 'emf-test', coverage: 1, caps: [], top_issue: 'A mocked issue message' };
}
async function mockScoring(page: any, rows: any[]) {
  const scored = rows.filter((r) => r.state === 'scored' && r.score !== null);
  await page.route('**/api/scoring', (route: any) => route.fulfill({ json: { version: 'emf-test', rubric: 'Extraction-to-Model Fidelity', bands: [], parts: rows,
    summary: { parts: rows.length, scored: scored.length, average: scored.reduce((a: number, r: any) => a + r.score, 0) / Math.max(1, scored.length), distribution: {}, incomplete: rows.filter((r) => r.state === 'incomplete').length,
      no_model: 0, scoring_failed: 0, pending: 0, parts_with_critical: 1 } } }));
}
async function boot(page: any, request: any) {
  const session = (await (await request.post('/api/session')).json()).session as string;
  await page.goto('/#/home');
  await page.waitForFunction(() => !!(window as any).McA);
  await page.evaluate((sid: string) => (window as any).McA.persist.set((window as any).McA.persist.KEYS.session, sid), session);
  return session;
}
const colour = (loc: any) => loc.evaluate((e: HTMLElement) => getComputedStyle(e).color);

test.describe('v4: numbers and buttons', () => {
  test('84 every number on the Scoring overview takes a grade colour, and so do the worked-example scores and the credit curve', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockScoring(page, [row('P1', 100), row('P2', 95), row('P3', 85), row('P4', 65), row('P5', 45), row('P6', 10), row('P7', null, 'incomplete')]);
    await boot(page, request);
    await page.goto('/#/scoring'); await page.reload();
    const stats = page.locator('.sc-stat .sc-stat-v');
    await expect(stats).toHaveCount(5, { timeout: 15_000 });
    for (let i = 0; i < 4; i++) {
      const c = await colour(stats.nth(i));
      expect(c, `overview number ${i}`).not.toBe(WHITE_TEXT);                                        // never plain white
      expect([...GRADE_RGB, NEUTRAL], `overview number ${i}`).toContain(c);
    }
    await expect(page.locator('.sc-attn li .sc-score-n').first()).toBeVisible();
    for (const c of await page.locator('.sc-attn li .sc-score-n').evaluateAll((els) => els.map((e) => getComputedStyle(e).color))) expect(GRADE_RGB).toContain(c);
    await shot(page, 'overview-numbers-1440x900.png');
    await page.getByRole('tab', { name: 'Worked example' }).click();
    const scores = page.locator('.sc-example .sc-ex-s');
    await expect(scores).toHaveCount(6, { timeout: 15_000 });
    for (const c of await scores.evaluateAll((els) => els.map((e) => getComputedStyle(e).color))) expect(GRADE_RGB).toContain(c);
    for (const c of await page.locator('.sc-example .cr').evaluateAll((els) => els.map((e) => getComputedStyle(e).color))) expect(GRADE_RGB).toContain(c);
    await shot(page, 'example-numbers-1440x900.png');
    await page.getByRole('tab', { name: 'Scoring methodology' }).click();
    const curve = page.locator('.sc-method .cr-curve');
    await expect(curve).toHaveCount(6, { timeout: 15_000 });
    for (const c of await curve.evaluateAll((els) => els.map((e) => getComputedStyle(e).color))) expect(GRADE_RGB).toContain(c);
    expect(serious(await new AxeBuilder({ page }).include('#page-scoring').analyze())).toEqual([]);
  });

  test('85 the part results table: coloured fidelity scores and larger Details / Re-evaluate buttons that stand out', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockScoring(page, [row('P1', 93.4), row('P2', 43.6), row('P3', 70.3)]);
    await boot(page, request);
    await page.goto('/#/scoring'); await page.reload();
    await page.getByRole('tab', { name: 'Part results' }).click();
    const tr = page.locator('.sc-tbl tr', { has: page.locator('strong', { hasText: /^P1$/ }) });
    await expect(tr.locator('.sc-score-n')).toHaveText('93.4');
    expect(GRADE_RGB).toContain(await colour(tr.locator('.sc-score-n')));
    const details = tr.getByRole('button', { name: 'Details' }), evalBtn = tr.getByRole('button', { name: 'Re-evaluate' });
    for (const b of [details, evalBtn]) {
      const box = (await b.boundingBox())!;
      expect(box.height, 'larger than the old 30px small button').toBeGreaterThanOrEqual(38);
      const bg = await b.evaluate((e: HTMLElement) => getComputedStyle(e).backgroundColor);
      expect(bg).not.toBe('rgba(0, 0, 0, 0)');
    }
    // Details is violet, Re-evaluate is champagne gold: same families as Save part and Run Pipeline
    expect(await colour(details)).not.toBe(await colour(evalBtn));
    const bd = await details.evaluate((e: HTMLElement) => getComputedStyle(e).borderTopColor), be = await evalBtn.evaluate((e: HTMLElement) => getComputedStyle(e).borderTopColor);
    expect(bd).not.toBe(be);                                                                              // two different tinted borders (violet and gold), not the plain grey outline
    for (const b of [bd, be]) expect(b).not.toMatch(/rgba?\(4[0-9], 5[0-9], 6[0-9]\)|rgb\(68, 71, 82\)/);
    expect(bd).toMatch(/srgb 0\.6/);                                                                      // the violet family (#9B8AFB at 60%)
    expect(be).toMatch(/srgb 0\.8/);                                                                      // the gold family (#D6AF6B at 65%)
    await details.hover();
    await expect(details).toHaveCSS('transform', /matrix/);                                              // a small lift on hover
    await shot(page, 'results-buttons-1440x900.png');
    expect(serious(await new AxeBuilder({ page }).include('#page-scoring').analyze())).toEqual([]);
  });

  test('86 Projects: Open is solid violet like Save part, Results is gold-tinted, both larger; Details and Evaluate-all match', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = 'Bt' + uniq();
    const session = await boot(page, request);
    await request.post('/api/parts', { multipart: { session, part, original: { name: 'd.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 x') } } });
    const out = path.join(STAGE2_OUT, part); fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, `${part}_extraction.json`), JSON.stringify({ units: 'inch', features: [], dimensions: [], hole_callouts: [] }));
    await page.goto('/#/projects'); await page.reload();
    const card = page.locator('#proj-body .pcard', { has: page.locator('.pcard-n', { hasText: new RegExp('^' + part + '$') }) });
    const open = card.getByRole('button', { name: 'Open', exact: true }), results = card.getByRole('button', { name: 'Results', exact: true });
    await expect(open).toBeVisible({ timeout: 15_000 });
    await expect(results).toBeVisible();
    expect((await open.boundingBox())!.height).toBeGreaterThanOrEqual(38);
    expect((await results.boundingBox())!.height).toBeGreaterThanOrEqual(38);
    expect(await open.evaluate((e: HTMLElement) => getComputedStyle(e).backgroundColor)).toBe('rgb(155, 138, 251)');          // the theme violet
    const rb = await results.evaluate((e: HTMLElement) => getComputedStyle(e).backgroundColor);
    expect(rb).not.toBe('rgba(0, 0, 0, 0)');
    expect(await colour(results)).toMatch(/rgb\(2[0-9]{2}, 1[0-9]{2}, 1[0-9]{2}\)/);                                            // gold text
    await shot(page, 'projects-buttons-1440x900.png');
    await page.goto('/#/scoring');
    const all = page.locator('#sc-eval-all');
    expect((await all.boundingBox())!.height).toBeGreaterThanOrEqual(38);
    await page.goto('/#/projects');
    expect(serious(await new AxeBuilder({ page }).include('#page-projects').analyze())).toEqual([]);
  });

  test('87 the app always loads the latest scripts and styles: versioned URLs, revalidated, never a stale cached copy', async ({ page, request }) => {
    await boot(page, request);
    const html = await (await request.get('/')).text();
    const urls = html.match(/(?:src|href)="\/static\/[^"]+"/g) || [];
    expect(urls.length).toBeGreaterThan(20);
    expect(urls.every((u) => u.includes('?v='))).toBe(true);
    const css = await request.get('/static/css/pages.css');
    expect(css.headers()['cache-control']).toBe('no-cache');
    const loaded = await page.evaluate(() => Array.from(document.querySelectorAll('link[rel=stylesheet], script[src]')).map((e: any) => e.href || e.src).filter((u) => u.includes('/static/')));
    expect(loaded.length).toBeGreaterThan(20);
    expect(loaded.every((u: string) => /\?v=[0-9a-f]{10}$/.test(u))).toBe(true);
  });
});
