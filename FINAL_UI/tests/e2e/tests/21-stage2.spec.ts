import { test, expect, Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import * as fs from 'fs';
import * as path from 'path';
import { N_ROWS, N_UNPRICED, EXPECTED_PART_TOTAL, PART, STAGE2_OUT, openCostDrawer, seedPart } from '../helpers/stage2';

// The server for this spec must be started with MCAGENT_FINAL_OUTPUTS=$STAGE2_OUT (an isolated temp folder).
test.skip(!STAGE2_OUT, 'STAGE2_OUT not set: start the server with MCAGENT_FINAL_OUTPUTS=$STAGE2_OUT and export STAGE2_OUT');

const EVID = path.resolve(__dirname, '../../../../docs/test-reports/stage2-evidence');
const VIEWPORTS = [
  { name: '1920x1080', w: 1920, h: 1080 },
  { name: '1440x900', w: 1440, h: 900 },
  { name: '1366x768', w: 1366, h: 768 },
  { name: '390x844', w: 390, h: 844 },
];
const serious = (res: any) => res.violations.filter((v: any) => v.impact === 'serious' || v.impact === 'critical');

async function lastRowVisible(page: Page, scope: string): Promise<{ inViewport: boolean; inDrawer: boolean }> {
  return page.evaluate((sel) => {
    const rows = Array.from(document.querySelectorAll(sel + ' .cost-attempt tbody tr'));
    const last = rows[rows.length - 1] as HTMLElement;
    last.scrollIntoView({ block: 'end' });
    const r = last.getBoundingClientRect();
    const d = document.querySelector('#drawer')!.getBoundingClientRect();
    return { inViewport: r.top >= 0 && r.bottom <= window.innerHeight + 1, inDrawer: r.top >= d.top - 1 && r.bottom <= d.bottom + 1 };
  }, scope);
}

test.describe('Stage 2: progress, cost key, full-height Results', () => {
  test('21 cost key matches the Results part total; unpriced rows stay visible; every row is listed', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seedPart(page, request);
    const chip = page.locator('#hdr-cost');
    await expect(page.locator('#hdr-cost-v')).toHaveText(/Est\. \$1\.1[23]/, { timeout: 15_000 });   // partial: some calls unpriced
    await expect(chip).toHaveAttribute('data-status', 'partial');
    await openCostDrawer(page);
    const partCard = page.locator('#dr-results .cost-card', { hasText: 'Selected part' });
    await expect(partCard).toContainText('$1.125');
    await expect(partCard).toContainText('Partial estimate');
    const money = (t: string) => t.match(/\$([0-9]+(?:\.[0-9]+)?)/)![1];
    const key = money(await page.locator('#hdr-cost-v').innerText());
    const card = money(await partCard.locator('.v').innerText());
    expect(Number(key)).toBeCloseTo(Number(card), 1);
    expect(Number(card)).toBeCloseTo(EXPECTED_PART_TOTAL, 6);
    // the other part's $99 row is not counted
    await expect(page.locator('#dr-results')).not.toContainText('$99');
    // every ledger row of this part is in the DOM (details are collapsed, not dropped) and unpriced is explicit
    expect(await page.locator('#dr-results .cost-attempt tbody tr').count()).toBe(N_ROWS);
    expect(await page.locator('#dr-results .cost-attempt tbody tr[data-pricing="unpriced"]').count()).toBe(N_UNPRICED);
    expect(await page.locator('#dr-results .cost-attempt tbody tr[data-pricing="unpriced"] td', { hasText: 'Unpriced' }).count()).toBeGreaterThanOrEqual(N_UNPRICED);
    // check the figures (cards and table cells), not the explanatory note, which says "never as $0.00"
    const figures = await page.locator('#dr-results .cost-card .v, #dr-results .cost-attempt td, #dr-results .cost-att-sum').allInnerTexts();
    expect(figures.filter((t) => /^\s*\$0\.00\s*$/.test(t)), 'no figure may read $0.00').toEqual([]);
    // attempts are grouped and each keeps its own total; the part total is their sum
    await expect(page.locator('#dr-results .cost-attempt')).toHaveCount(2);
  });

  for (const v of VIEWPORTS) {
    test(`22 drawer maximum fills the available height and the last cost row is reachable at ${v.name}`, async ({ page, request }) => {
      fs.mkdirSync(EVID, { recursive: true });
      await page.setViewportSize({ width: v.w, height: v.h });
      await seedPart(page, request);
      await openCostDrawer(page);
      // expand the last attempt too so its last row is rendered
      await page.evaluate(() => document.querySelectorAll('#dr-results .cost-attempt').forEach((d) => d.setAttribute('open', '')));
      const flow = v.w < 800;
      if (!flow) {
        await page.click('#dr-max');
        await expect(page.locator('#dr-max')).toHaveAttribute('aria-pressed', 'true');
      } else {
        await page.evaluate(() => (window as any).McA.dom.setUi({ drawerSize: 'max' }));
      }
      await page.waitForTimeout(200);
      const m = await page.evaluate(() => {
        const d = document.querySelector('#drawer')!.getBoundingClientRect();
        const head = document.querySelector('#drawer .dr-head')!.getBoundingClientRect();
        const trk = document.querySelector('.tracker')!.getBoundingClientRect();
        return { top: d.top, bottom: d.bottom, h: d.height, headTop: head.top, headBottom: head.bottom, trkBottom: trk.bottom, vh: window.innerHeight,
          bodyOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth };
      });
      if (!flow) {
        expect(m.h, `drawer ${m.h}px must beat the old 70% cap (${Math.round(v.h * 0.7)}px)`).toBeGreaterThan(Math.round(v.h * 0.7));
        expect(m.top).toBeGreaterThanOrEqual(m.trkBottom - 1);            // never covers the header/tracker
        expect(m.bottom).toBeLessThanOrEqual(m.vh + 1);                    // never clipped below the viewport
      }
      expect(m.headTop).toBeGreaterThanOrEqual(0);                        // drawer header stays visible
      expect(m.bodyOverflowX).toBeLessThanOrEqual(1);                     // no horizontal page scroll
      const vis = await lastRowVisible(page, '#dr-results');
      expect(vis.inViewport, 'last Results row reachable in the viewport').toBe(true);
      if (!flow) expect(vis.inDrawer, 'last Results row inside the drawer').toBe(true);
      await page.screenshot({ path: path.join(EVID, `drawer-max-${v.name}.png`) });
      // one intentional scroll owner: the pane scrolls, nothing inside it is a nested capped box
      const nested = await page.evaluate(() => Array.from(document.querySelectorAll('#dr-results .dr-pane *')).filter((e) => {
        const cs = getComputedStyle(e);
        return (cs.overflowY === 'auto' || cs.overflowY === 'scroll') && cs.maxHeight !== 'none' && !e.classList.contains('tbl-wrap');
      }).length);
      expect(nested).toBe(0);
    });
  }

  test('23 drawer states: fit, maximize/restore, keyboard, remembered height per viewport class', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seedPart(page, request);
    await openCostDrawer(page);
    const h = () => page.evaluate(() => document.querySelector('#drawer')!.getBoundingClientRect().height);
    const rz = page.locator('#dr-resize');
    await rz.focus();
    const h0 = Number(await rz.getAttribute('aria-valuenow'));
    await page.keyboard.press('ArrowUp');
    const h1 = Number(await rz.getAttribute('aria-valuenow'));
    expect(h1).toBeGreaterThan(h0);
    await page.click('#dr-fit');
    await expect(page.locator('#dr-fit')).toHaveAttribute('aria-pressed', 'true');
    const maxv = Number(await rz.getAttribute('aria-valuemax'));
    expect(await h()).toBeLessThanOrEqual(maxv + 1);
    await rz.focus();
    await page.keyboard.press('Enter');                                       // toggle maximum
    await expect(page.locator('#dr-max')).toHaveAttribute('aria-pressed', 'true');
    expect(await h()).toBeGreaterThanOrEqual(maxv - 1);
    await page.keyboard.press('Enter');                                       // restore
    await expect(page.locator('#dr-max')).toHaveAttribute('aria-pressed', 'false');
    await page.keyboard.press('Home');
    expect(Number(await rz.getAttribute('aria-valuenow'))).toBe(160);
    // a remembered height persists across reload for this viewport class, and is re-clamped on a shorter window
    await page.keyboard.press('Shift+ArrowUp'); await page.keyboard.press('Shift+ArrowUp');
    const kept = Number(await rz.getAttribute('aria-valuenow'));
    await page.waitForTimeout(400);
    await page.reload();
    await page.evaluate(() => { location.hash = '#/workspace'; });
    await expect(page.locator('#dr-resize')).toHaveAttribute('aria-valuenow', String(kept));
    await page.setViewportSize({ width: 1440, height: 520 });
    await page.waitForTimeout(300);
    const clamped = Number(await page.locator('#dr-resize').getAttribute('aria-valuenow'));
    const newMax = Number(await page.locator('#dr-resize').getAttribute('aria-valuemax'));
    expect(clamped).toBeLessThanOrEqual(newMax);
  });

  test('24 standalone Results page flows to its full content height with no artificial cutoff', async ({ page, request }) => {
    fs.mkdirSync(EVID, { recursive: true });
    for (const v of VIEWPORTS) {
      await page.setViewportSize({ width: v.w, height: v.h });
      await seedPart(page, request);
      await page.evaluate(() => { location.hash = '#/results'; });
      await page.evaluate(() => (window as any).McA.dom.setUi({ resultsSection: 'cost' }));
      await expect(page.locator('#res-root .cost-cards').first()).toBeVisible({ timeout: 15_000 });
      await page.evaluate(() => document.querySelectorAll('#res-root .cost-attempt').forEach((d) => d.setAttribute('open', '')));
      const m = await page.evaluate(() => {
        const main = document.querySelector('.main') as HTMLElement;
        const capped = Array.from(document.querySelectorAll('.page-results *')).filter((e) => {
          const cs = getComputedStyle(e);
          return cs.maxHeight !== 'none' && /vh|px/.test(cs.maxHeight) && (cs.overflowY === 'auto' || cs.overflowY === 'scroll') && !e.classList.contains('tbl-wrap') && !e.classList.contains('res-nav');
        }).length;
        return { scrolls: main.scrollHeight > main.clientHeight, capped };
      });
      expect(m.scrolls, `${v.name}: the page itself scrolls`).toBe(true);
      expect(m.capped, `${v.name}: no capped nested scroll boxes`).toBe(0);
      const vis = await page.evaluate(() => {
        const rows = Array.from(document.querySelectorAll('#res-root .cost-attempt tbody tr'));
        const last = rows[rows.length - 1] as HTMLElement; last.scrollIntoView({ block: 'end' });
        const r = last.getBoundingClientRect(); return r.top >= 0 && r.bottom <= window.innerHeight + 1;
      });
      expect(vis, `${v.name}: last row reachable`).toBe(true);
      await page.screenshot({ path: path.join(EVID, `results-page-${v.name}.png`) });
      await page.evaluate(() => { (document.querySelector('.main') as HTMLElement).scrollTop = 0; });
      await page.screenshot({ path: path.join(EVID, `results-page-top-${v.name}.png`) });
    }
  });

  test('25 tracker shows backend percent, operation and unit count; indeterminate has no number; failure keeps the last percent', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const session = await seedPart(page, request);
    const ev = (seq: number, kind: string, payload: any, run = 'run_ui', attempt = 1) => '[gptastra-event] ' + JSON.stringify({
      schema_version: 1, event_id: `e${seq}${run}`, run_id: run, attempt, part_id: PART, seq, occurred_at: '2026-11-18T00:00:00.000Z', kind, payload });
    const prog = (pct: number | null, extra: any = {}) => Object.assign({ phase: 'solidworks_generation', operation: 'create_feature', label: 'Creating feature 7 of 18',
      percent: pct, indeterminate: pct === null, completed_units: 6, total_units: 18, unit: 'features', terminal: null }, extra);
    const feed = (lines: string[]) => page.evaluate(([l]) => (window as any).McA.store.dispatch('run/lines', { id: 'r_ui', lines: l }), [lines]);
    await page.evaluate(([sid, part]) => {
      const S = (window as any).McA.store;
      S.dispatch('run/queued', { kind: 'part', session: sid, part });
      S.dispatch('run/started', { id: 'r_ui', startedAt: Date.now() });
    }, [session, PART]);
    // indeterminate first: no number, honest wording
    await feed([ev(1, 'run.started', {}), ev(2, 'progress.updated', prog(null, { phase: 'ingest', operation: 'ingest_drawing', total_units: null, completed_units: 0, label: '' }))]);
    await expect(page.locator('#trk-caption')).toContainText('Preparing the drawing');
    expect((await page.locator('.trk-pct-n').innerText()).trim()).toBe('');
    await expect(page.locator('#trk-pct')).toHaveAttribute('aria-valuetext', /not yet measurable/);
    expect(await page.locator('#trk-pct').getAttribute('aria-valuenow')).toBeNull();
    // exact backend value, operation and unit count
    await feed([ev(3, 'progress.updated', prog(61.2))]);
    await expect(page.locator('.trk-pct-n')).toHaveText('61.2%');
    await expect(page.locator('#trk-caption')).toHaveText('Creating feature 7 of 18 · 6 of 18 features');
    await expect(page.locator('#trk-pct')).toHaveAttribute('aria-valuenow', '61.2');
    fs.mkdirSync(EVID, { recursive: true });
    await page.screenshot({ path: path.join(EVID, 'tracker-structured-61.2.png'), clip: { x: 260, y: 0, width: 1180, height: 175 } });
    // regressions and stale runs change nothing
    await feed([ev(4, 'progress.updated', prog(20)), ev(9, 'progress.updated', prog(99), 'run_old')]);
    await expect(page.locator('.trk-pct-n')).toHaveText('61.2%');
    // restrained announcements: one per phase change, none per percent
    const live = await page.evaluate(() => document.querySelector('[aria-live]') ? 1 : 0);
    expect(live).toBe(1);
    // failure stops at the last truthful percentage (not 100, not removed)
    await feed([ev(5, 'run.failed', { reason: 'boom' })]);
    await page.evaluate(() => (window as any).McA.store.dispatch('run/finalized', { id: 'r_ui', exit: 1, cancelled: false, summary: null, payload: null }));
    await expect(page.locator('.trk-pct-n')).toHaveText('61.2%');
    // reduced motion: the indeterminate ring does not animate
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.evaluate(([sid, part]) => {
      const S = (window as any).McA.store;
      S.dispatch('run/queued', { kind: 'part', session: sid, part });
      S.dispatch('run/started', { id: 'r_ui2', startedAt: Date.now() });
    }, [session, PART]);
    await page.evaluate(([l]) => (window as any).McA.store.dispatch('run/lines', { id: 'r_ui2', lines: l }), [[
      ev(1, 'run.started', {}, 'run_ui2', 2),
      ev(2, 'progress.updated', prog(null, { phase: 'ingest', operation: 'ingest_drawing', total_units: null, completed_units: 0, label: '' }), 'run_ui2', 2)]]);
    await expect(page.locator('#trk-pct svg')).toHaveClass(/ring-ind/);
    expect(await page.locator('#trk-pct svg').evaluate((e) => getComputedStyle(e).animationName)).toBe('none');
    await page.screenshot({ path: path.join(fs.mkdirSync(EVID, { recursive: true }) || EVID, 'tracker-reduced-motion.png') });
  });

  test('26 key cost chip, tracker, drawer controls and cost tables have no serious or critical axe violations', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seedPart(page, request);
    await openCostDrawer(page);
    const res = await new AxeBuilder({ page }).include('#hdr-cost').include('.tracker').include('#drawer').withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
    const bad = serious(res);
    fs.mkdirSync(EVID, { recursive: true });
    fs.writeFileSync(path.join(EVID, 'axe-stage2.json'), JSON.stringify({ checked: ['#hdr-cost', '.tracker', '#drawer'], serious_or_critical: bad.map((v: any) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })), all: res.violations.map((v: any) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })) }, null, 2));
    expect(bad, JSON.stringify(bad.map((v: any) => v.id + ': ' + v.help))).toEqual([]);
  });
});
