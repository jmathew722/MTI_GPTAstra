import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import { auditLayout, summarise, Finding } from '../helpers/layout-audit';

// Layout audit: no coloured accent (left border / inset bar) may sit closer than 8px to the content it decorates, no text may be
// clipped by its box, and no page may scroll sideways. Crawls every page, every Results section, the Scoring tabs and detail,
// the Workspace with the Results drawer, at six window sizes (these also stand in for 125%..300% browser zoom) and with the
// sidebar expanded and collapsed. Uses whatever real parts the server holds; skips when it holds none.
const VERIFY = path.resolve(__dirname, '../../../docs/verification/v4/layout');
const SIZES: Array<[number, number]> = [[1920, 1080], [1440, 900], [1366, 768], [1100, 800], [800, 900], [390, 844]];
const shot = async (page: any, name: string) => { fs.mkdirSync(VERIFY, { recursive: true }); await page.screenshot({ path: path.join(VERIFY, name) }); };

async function target(request: any) {
  const sc = await (await request.get('/api/scoring')).json();
  return (sc.parts || []).find((x: any) => x.has_output && x.session) || null;
}
async function boot(page: any, p: any, w: number, h: number, collapsed: boolean) {
  await page.setViewportSize({ width: w, height: h });
  await page.goto('/#/home'); await page.waitForFunction(() => !!(window as any).McA);
  await page.evaluate((s: string) => (window as any).McA.persist.set((window as any).McA.persist.KEYS.session, s), p.session);
  const tog = page.locator('#sb-toggle');
  if (await tog.isVisible().catch(() => false)) {
    const open = (await tog.getAttribute('aria-expanded')) === 'true';
    if (open === collapsed) { await tog.click(); await page.waitForTimeout(250); }
  }
}
const fmt = (fs_: Finding[]) => fs_.map((f) => `${f.kind} ${f.selector}: ${f.detail} ${JSON.stringify(f.text || '')}`);
const dedupe = (fs_: Finding[]) => Array.from(new Map(fs_.map((f) => [f.kind + f.selector + f.detail, f])).values());

test.describe('v4: layout audit', () => {
  test('88 no accent line, border or status bar overlaps text on any page, at any window size or sidebar state', async ({ page, request }) => {
    test.setTimeout(300_000);
    const p = await target(request);
    test.skip(!p, 'the server holds no part with output');
    const bad: string[] = [];
    for (const [w, h] of SIZES) {
      for (const collapsed of [false, true]) {
        if (collapsed && w < 1100) continue;                      // the sidebar is a drawer below 1100px
        await boot(page, p, w, h, collapsed);
        for (const r of ['home', 'projects', 'scoring', 'recent', 'help', 'settings']) {
          await page.goto('/#/' + r); await page.reload(); await page.waitForTimeout(700);
          for (const f of dedupe(await auditLayout(page))) bad.push(`[${w}x${h}${collapsed ? ' rail' : ''}] ${r}: ${fmt([f])[0]}`);
        }
      }
    }
    expect(summarise(bad)).toEqual([]);
  });

  test('89 Pipeline Results: every section, Engineering Flags included, keeps its accent clear of the text', async ({ page, request }) => {
    test.setTimeout(300_000);
    const p = await target(request);
    test.skip(!p, 'the server holds no part with output');
    const bad: string[] = [];
    for (const [w, h] of SIZES) {
      await boot(page, p, w, h, false);
      await page.goto(`/#/results?run=${p.session}|${p.part}`); await page.reload(); await page.waitForTimeout(1200);
      const links = page.locator('#res-root .res-link');
      const n = await links.count();
      expect(n).toBeGreaterThan(5);
      for (let i = 0; i < n; i++) {
        await links.nth(i).click().catch(() => {}); await page.waitForTimeout(250);
        const label = ((await links.nth(i).textContent()) || '').trim().slice(0, 24);
        for (const f of dedupe(await auditLayout(page))) bad.push(`[${w}x${h}] ${label}: ${fmt([f])[0]}`);
        if (w === 1440 && /Flags/i.test(label)) await shot(page, 'results-engineering-flags-1440x900.png');
        if (w === 390 && /Flags/i.test(label)) await shot(page, 'results-engineering-flags-390x844.png');
      }
      if (w === 1440) await shot(page, 'results-1440x900.png');
    }
    expect(summarise(bad)).toEqual([]);
  });

  test('90 Scoring tabs and the detail view, and the Workspace with its Results drawer, are clear of overlaps', async ({ page, request }) => {
    test.setTimeout(300_000);
    const p = await target(request);
    test.skip(!p, 'the server holds no part with output');
    const bad: string[] = [];
    for (const [w, h] of SIZES) {
      await boot(page, p, w, h, false);
      await page.goto('/#/scoring'); await page.reload(); await page.waitForTimeout(900);
      const tabs = page.locator('.sc-tab'); const nt = await tabs.count();
      for (let i = 0; i < nt; i++) {
        await tabs.nth(i).click(); await page.waitForTimeout(300);
        const label = ((await tabs.nth(i).textContent()) || '').trim();
        for (const f of dedupe(await auditLayout(page))) bad.push(`[${w}x${h}] scoring/${label}: ${fmt([f])[0]}`);
        if (w === 1440 && /Part results/i.test(label)) await shot(page, 'scoring-part-results-1440x900.png');
      }
      await page.getByRole('tab', { name: 'Part results' }).click().catch(() => {});
      const det = page.getByRole('button', { name: 'Details' }).first();
      if (await det.count()) {
        await det.click(); await page.waitForTimeout(700);
        for (const f of dedupe(await auditLayout(page))) bad.push(`[${w}x${h}] scoring/detail: ${fmt([f])[0]}`);
        if (w === 1440) await shot(page, 'scoring-detail-1440x900.png');
      }
      await page.evaluate(([s, pt]: string[]) => (window as any).McA.openPart(s, pt), [p.session, p.part]);
      await page.waitForTimeout(1500);
      for (const f of dedupe(await auditLayout(page))) bad.push(`[${w}x${h}] workspace: ${fmt([f])[0]}`);
      const tog = page.locator('#dr-toggle');
      if (await tog.isVisible().catch(() => false)) {
        await tog.click(); await page.waitForTimeout(900);
        for (const f of dedupe(await auditLayout(page))) bad.push(`[${w}x${h}] workspace drawer: ${fmt([f])[0]}`);
        if (w === 1440) await shot(page, 'workspace-drawer-1440x900.png');
      }
    }
    expect(summarise(bad)).toEqual([]);
  });
});
