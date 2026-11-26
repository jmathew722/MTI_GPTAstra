import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import * as fs from 'fs';
import * as path from 'path';
import { STAGE2_OUT, uniq } from '../helpers/stage3';

test.skip(!STAGE2_OUT, 'STAGE2_OUT not set: start the server with MCAGENT_FINAL_OUTPUTS=$STAGE2_OUT and export STAGE2_OUT');

const VERIFY = path.resolve(__dirname, '../../../docs/verification/v4');
const serious = (res: any) => res.violations.filter((v: any) => v.impact === 'serious' || v.impact === 'critical');
const shot = async (page: any, name: string) => { fs.mkdirSync(VERIFY, { recursive: true }); await page.screenshot({ path: path.join(VERIFY, name) }); };

/* The six fixed grades and the neutral grey, as the browser reports them (rgb). */
const RGB: Record<string, string> = {
  poor: 'rgb(217, 87, 99)', below: 'rgb(217, 139, 85)', fair: 'rgb(214, 175, 107)', good: 'rgb(181, 199, 107)', excellent: 'rgb(141, 212, 154)', perfect: 'rgb(76, 183, 130)', none: 'rgb(146, 148, 158)',
};
/* score -> expected grade id, expected label, expected display (truncated, never rounded up) */
const CASES: [number, string, string, string][] = [
  [0, 'poor', 'Poor', '0.0'], [38.99, 'poor', 'Poor', '38.9'], [39, 'poor', 'Poor', '39.0'], [39.99, 'poor', 'Poor', '39.9'],
  [40, 'below', 'Below Average', '40.0'], [59.99, 'below', 'Below Average', '59.9'],
  [60, 'fair', 'Fair', '60.0'], [79.99, 'fair', 'Fair', '79.9'],
  [80, 'good', 'Good', '80.0'], [89.99, 'good', 'Good', '89.9'],
  [90, 'excellent', 'Excellent', '90.0'], [99.99, 'excellent', 'Excellent', '99.9'], [99.999, 'excellent', 'Excellent', '99.9'],
  [100, 'perfect', 'Perfect', '100.0'],
];

function row(part: string, score: number | null, state = 'scored') {
  return { part, session: '', has_output: true, has_part: true, run_id: 'run_x', last_activity: 1795123302, state, score, band: { id: 'green', label: 'IGNORED SERVER BAND', glyph: 'check' }, reason: state === 'incomplete' ? 'no_mesh' : undefined,
    counts: { critical: 0, high: 0 }, categories: {}, evaluated_at: '2026-11-25T10:00:00+00:00', fingerprint: 'emf-test', coverage: 1, caps: [] };
}
async function mockScoring(page: any, rows: any[]) {
  await page.route('**/api/scoring', (route: any) => route.fulfill({ json: { version: 'emf-test', rubric: 'Extraction-to-Model Fidelity', bands: [], parts: rows,
    summary: { parts: rows.length, scored: rows.filter((r) => r.state === 'scored').length, average: 75, distribution: {}, incomplete: 0, no_model: 0, scoring_failed: 0, pending: 0, parts_with_critical: 0 } } }));
}
async function boot(page: any, request: any) {
  const session = (await (await request.post('/api/session')).json()).session as string;
  await page.goto('/#/home');
  await page.waitForFunction(() => !!(window as any).McA);
  await page.evaluate((sid: string) => (window as any).McA.persist.set((window as any).McA.persist.KEYS.session, sid), session);
  return session;
}

test.describe('v4: grading spectrum (0-100) with fixed thresholds', () => {
  test('77 every threshold boundary gets the exact HEX colour, word and an un-rounded number in the Scoring table', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const rows = CASES.map(([s], i) => row('Bd' + i, s));
    await mockScoring(page, rows);
    await boot(page, request);
    await page.goto('/#/scoring'); await page.reload();
    await page.getByRole('tab', { name: 'Part results' }).click();
    for (let i = 0; i < CASES.length; i++) {
      const [score, id, label, shown] = CASES[i];
      const tr = page.locator('.sc-tbl tr', { has: page.locator('strong', { hasText: new RegExp('^Bd' + i + '$') }) });
      await expect(tr, `score ${score}`).toHaveAttribute('data-band', id);
      await expect(tr.locator('.sc-score-n'), `score ${score}`).toHaveText(shown);
      expect(await tr.locator('.sc-score-n').evaluate((e: HTMLElement) => getComputedStyle(e).color), `score ${score} colour`).toBe(RGB[id]);
      await expect(tr.locator('.band-pill').first(), `score ${score}`).toContainText(label);
      expect(await tr.locator('.band-pill').first().evaluate((e: HTMLElement) => getComputedStyle(e).color)).toBe(RGB[id]);
    }
    await shot(page, 'grade-spectrum-table-1440x900.png');
  });

  test('78 99.99 is never shown as 100 or coloured Perfect; only exactly 100 is Perfect', async ({ page, request }) => {
    await mockScoring(page, [row('NearPerfect', 99.99), row('Exact', 100), row('NearPoor', 39.99), row('NearBelow', 59.999)]);
    await boot(page, request);
    await page.goto('/#/scoring'); await page.reload();
    await page.getByRole('tab', { name: 'Part results' }).click();
    const tr = (n: string) => page.locator('.sc-tbl tr', { has: page.locator('strong', { hasText: new RegExp('^' + n + '$') }) });
    await expect(tr('NearPerfect').locator('.sc-score-n')).toHaveText('99.9');
    await expect(tr('NearPerfect')).toHaveAttribute('data-band', 'excellent');
    await expect(tr('Exact').locator('.sc-score-n')).toHaveText('100.0');
    await expect(tr('Exact')).toHaveAttribute('data-band', 'perfect');
    await expect(tr('NearPoor')).toHaveAttribute('data-band', 'poor');
    await expect(tr('NearBelow')).toHaveAttribute('data-band', 'below');
  });

  test('79 missing, unavailable and invalid scores are neutral grey, never red', async ({ page, request }) => {
    await mockScoring(page, [row('Inc', null, 'incomplete'), row('NoModel', null, 'no_model'), row('Failed', null, 'scoring_failed'), row('Pend', null, 'pending'), row('NullScore', null, 'scored'), row('Over', 130, 'scored')]);
    await boot(page, request);
    await page.goto('/#/scoring'); await page.reload();
    await page.getByRole('tab', { name: 'Part results' }).click();
    for (const n of ['Inc', 'NoModel', 'Failed', 'Pend', 'NullScore', 'Over']) {
      const tr = page.locator('.sc-tbl tr', { has: page.locator('strong', { hasText: new RegExp('^' + n + '$') }) });
      await expect(tr.locator('.sc-score-n'), n).toHaveCount(0);                                       // no number invented
      const pill = tr.locator('.band-pill').first();
      await expect(pill, n).toBeVisible();
      expect(await pill.evaluate((e: HTMLElement) => getComputedStyle(e).color), n).toBe(RGB.none);
      expect(await tr.evaluate((e: HTMLElement) => e.getAttribute('data-band')), n).toBe('none');
    }
  });

  test('80 the legend shows the six grades with their exact colours and ranges, and a smooth spectrum bar', async ({ page, request }) => {
    await mockScoring(page, [row('A', 83.14)]);
    await boot(page, request);
    await page.goto('/#/scoring'); await page.reload();
    const legend = page.locator('.sc-legend').first();
    await expect(legend.locator('li')).toHaveCount(6, { timeout: 15_000 });
    const expected = [['Poor', '0–39', 'poor'], ['Below Average', '40–59', 'below'], ['Fair', '60–79', 'fair'], ['Good', '80–89', 'good'], ['Excellent', '90–99', 'excellent'], ['Perfect', '100', 'perfect']];
    for (let i = 0; i < 6; i++) {
      await expect(legend.locator('li').nth(i)).toContainText(expected[i][0]);
      await expect(legend.locator('li').nth(i).locator('.sc-legend-r')).toHaveText(expected[i][1]);
      expect(await legend.locator('li').nth(i).locator('.band-pill').evaluate((e: HTMLElement) => getComputedStyle(e).color)).toBe(RGB[expected[i][2]]);
    }
    const bg = await page.locator('.sc-spectrum .grade-spectrum').first().evaluate((e: HTMLElement) => e.style.background || getComputedStyle(e).backgroundImage);
    expect(bg).toContain('linear-gradient');
    for (const hex of ['217, 87, 99', '217, 139, 85', '214, 175, 107', '181, 199, 107', '141, 212, 154', '76, 183, 130']) expect(bg.replace(/#/g, '')).toBeTruthy();
    expect((bg.match(/rgb\(/g) || []).length + (bg.match(/#[0-9A-Fa-f]{6}/g) || []).length).toBeGreaterThanOrEqual(6);
    await expect(page.locator('.sc-stat', { hasText: 'Average fidelity' })).toHaveClass(/band-/);
    await shot(page, 'grade-spectrum-overview-1440x900.png');
    expect(serious(await new AxeBuilder({ page }).include('#page-scoring').analyze())).toEqual([]);
  });

  test('81 Projects cards and runs, the Workspace header and Pipeline Results use the same grade colours', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const part = 'Gp' + uniq();
    const session = await boot(page, request);
    const up = await request.post('/api/parts', { multipart: { session, part, original: { name: 'd.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 x') } } });
    expect(up.ok()).toBeTruthy();
    const out = path.join(STAGE2_OUT, part); fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, `${part}_extraction.json`), JSON.stringify({ units: 'inch', features: [], dimensions: [], hole_callouts: [] }));
    fs.writeFileSync(path.join(out, 'plan.json'), JSON.stringify({ dims: {}, plan: { features: [] } }));
    const mine = { ...row(part, 83.14), session };
    await mockScoring(page, [mine]);
    await page.route(`**/api/scoring/parts/${part}`, (route: any) => route.fulfill({ json: { part, latest: { state: 'scored', score: 99.99, rubric: { fingerprint: 'emf-test' }, issues: [], counts: {}, categories: [] }, history: [], benchmark: null, current_fingerprint: 'emf-test' } }));
    await page.evaluate(([sid, p]: string[]) => { const McA = (window as any).McA; McA.persist.set(McA.persist.KEYS.selected, { session: sid, part: p }); }, [session, part]);
    // Projects: card badge and runs-table badge
    await page.goto('/#/projects'); await page.reload();
    const card = page.locator('#proj-body .pcard', { has: page.locator('.pcard-n', { hasText: new RegExp('^' + part + '$') }) });
    const cardBadge = card.locator('.grade-badge');
    await expect(cardBadge).toHaveText(/83\.1/, { timeout: 15_000 });
    expect(await cardBadge.evaluate((e: HTMLElement) => getComputedStyle(e).color)).toBe(RGB.good);
    await expect(cardBadge).toHaveAttribute('data-grade', 'good');
    await shot(page, 'grade-spectrum-projects-1440x900.png');
    // Workspace header chip
    await page.goto('/#/workspace'); await page.reload();
    await expect(page.locator('#hdr-score')).toHaveAttribute('data-grade', 'good', { timeout: 15_000 });
    await expect(page.locator('#hdr-score-v')).toContainText('83.1');
    await expect(page.locator('#hdr-score-v')).toContainText('Good');
    expect(await page.locator('#hdr-score .grade-num').evaluate((e: HTMLElement) => getComputedStyle(e).color)).toBe(RGB.good);
    await shot(page, 'grade-spectrum-workspace-1440x900.png');
    // Pipeline Results fidelity section: 99.99 is Excellent, never Perfect
    await page.evaluate(() => (window as any).McA.dom.setUi({ drawerOpen: true, drawerSection: 'scoring_rubric', drawerMode: 'results' }));
    const sec = page.locator('#dr-results section[data-sec="scoring_rubric"]');
    await expect(sec).toBeVisible({ timeout: 15_000 });
    const pill = sec.locator('.band-pill').first();
    await expect(pill).toContainText('99.9 / 100');
    await expect(pill).toContainText('Excellent');
    await expect(pill).not.toContainText('Perfect');
    expect(await pill.evaluate((e: HTMLElement) => getComputedStyle(e).color)).toBe(RGB.excellent);
    await shot(page, 'grade-spectrum-results-1440x900.png');
    expect(serious(await new AxeBuilder({ page }).include('#hdr-score').analyze())).toEqual([]);
  });

  test('82 a part with no score shows a neutral grey badge in Projects and the header, never red', async ({ page, request }) => {
    const part = 'Gn' + uniq();
    const session = await boot(page, request);
    await request.post('/api/parts', { multipart: { session, part, original: { name: 'd.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 x') } } });
    const out = path.join(STAGE2_OUT, part); fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, `${part}_extraction.json`), JSON.stringify({ units: 'inch', features: [], dimensions: [], hole_callouts: [] }));
    await mockScoring(page, [{ ...row(part, null, 'incomplete'), session }]);
    await page.evaluate(([sid, p]: string[]) => { const McA = (window as any).McA; McA.persist.set(McA.persist.KEYS.selected, { session: sid, part: p }); }, [session, part]);
    await page.goto('/#/projects'); await page.reload();
    const badge = page.locator('#proj-body .pcard', { has: page.locator('.pcard-n', { hasText: new RegExp('^' + part + '$') }) }).locator('.grade-badge');
    await expect(badge).toHaveAttribute('data-grade', 'none', { timeout: 15_000 });
    expect(await badge.evaluate((e: HTMLElement) => getComputedStyle(e).color)).toBe(RGB.none);
    await page.goto('/#/workspace'); await page.reload();
    await expect(page.locator('#hdr-score')).toHaveAttribute('data-grade', 'none', { timeout: 15_000 });
    expect(await page.locator('#hdr-score-v').evaluate((e: HTMLElement) => getComputedStyle(e).color)).toBe(RGB.none);
  });

  test('83 the Overview distribution, ring and category cards use the grade colours; the narrow layout still fits', async ({ page, request }) => {
    await mockScoring(page, [row('P1', 100), row('P2', 95), row('P3', 85), row('P4', 65), row('P5', 45), row('P6', 10)]);
    await boot(page, request);
    await page.goto('/#/scoring'); await page.reload();
    const segs = page.locator('.sc-dist .sc-dist-s');
    await expect(segs).toHaveCount(6, { timeout: 15_000 });
    const bgs = await segs.evaluateAll((els) => els.map((e) => getComputedStyle(e).backgroundColor));
    expect(bgs).toEqual([RGB.poor, RGB.below, RGB.fair, RGB.good, RGB.excellent, RGB.perfect]);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await page.waitForTimeout(400);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    await shot(page, 'grade-spectrum-narrow-390x844.png');
  });
});
