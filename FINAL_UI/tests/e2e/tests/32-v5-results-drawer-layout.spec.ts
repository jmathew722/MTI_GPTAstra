import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import { auditLayout, summarise, Finding } from '../helpers/layout-audit';

// Workspace "Pipeline Results" drawer layout. Regression for: expanded drawer looked like a shallow strip over a large empty area.
// Real cause: absolutely positioned .sr-only spans inside the drawer nav escaped the nav's scroll box and made #main scroll ~390px
// of dead space under the drawer. Asserts COMPUTED boxes, not screenshots.
const VERIFY = path.resolve(__dirname, '../../../docs/verification/v5/drawer');
const SIZES: Array<[number, number]> = [[1920, 1080], [1440, 900], [1280, 720], [1152, 720], [960, 600], [720, 450]];
const fmt = (fs_: Finding[]) => fs_.map((f) => `${f.kind} ${f.selector}: ${f.detail}`);
const shot = async (page: Page, name: string) => { fs.mkdirSync(VERIFY, { recursive: true }); await page.screenshot({ path: path.join(VERIFY, name) }); };

async function boot(page: Page, request: any, w: number, h: number, opts: { rail?: boolean; stored?: any; part?: boolean } = {}) {
  const sc = await (await request.get('/api/scoring')).json();
  const p = (sc.parts || []).find((x: any) => x.has_output && x.session);
  await page.setViewportSize({ width: w, height: h });
  await page.goto('/#/home'); await page.waitForFunction(() => !!(window as any).McA);
  await page.evaluate(([s, stored, usePart]: any) => {
    const P = (window as any).McA.persist;
    if (usePart && s) P.set(P.KEYS.session, s);
    localStorage.setItem('mca.ui.drawer', JSON.stringify(stored || { open: false, height: 320, section: 'overview', size: 'remembered', heights: {} }));
  }, [p && p.session, opts.stored, opts.part !== false]);
  await page.goto('/#/workspace'); await page.reload(); await page.waitForFunction(() => !!(window as any).McA);
  await expect(page.locator('#page-workspace')).toBeVisible(); await page.waitForTimeout(900);
  const tog = page.locator('#sb-toggle');
  if (opts.rail !== undefined && await tog.isVisible().catch(() => false)) {
    if (((await tog.getAttribute('aria-expanded')) === 'true') === !!opts.rail) { await tog.click(); await page.waitForTimeout(250); }
  }
}
const open = async (page: Page) => { if ((await page.locator('#dr-toggle').getAttribute('aria-expanded')) !== 'true') await page.locator('#dr-toggle').evaluate((e: HTMLElement) => e.click()); await page.waitForTimeout(350); };
const close = async (page: Page) => { if ((await page.locator('#dr-toggle').getAttribute('aria-expanded')) === 'true') await page.locator('#dr-toggle').evaluate((e: HTMLElement) => e.click()); await page.waitForTimeout(350); };

/** Computed geometry. gapToMain = distance from the drawer bottom to the visible bottom of the scroll area. */
async function geo(page: Page) {
  return page.evaluate(() => {
    const r = (s: string) => { const e = document.querySelector(s) as HTMLElement | null; return e ? e.getBoundingClientRect() : null; };
    const main = document.getElementById('main') as HTMLElement, d = r('#drawer')!, body = r('#dr-body'), pg = r('#page-workspace')!;
    const mb = main.getBoundingClientRect();
    return { vh: innerHeight, mainScroll: main.scrollHeight - main.clientHeight, gapToMain: Math.round(mb.bottom - d.bottom), drawerH: Math.round(d.height),
      bodyH: body ? Math.round(body.height) : 0, bodyHidden: (document.getElementById('dr-body') as HTMLElement).hidden, pageH: Math.round(pg.height),
      hOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      wsMain: Math.round((r('#ws-main') || { height: 0 }).height), expanded: document.getElementById('dr-toggle')!.getAttribute('aria-expanded') };
  });
}

test.describe('v5: Pipeline Results drawer layout', () => {
  test('92 expanded drawer fills the workspace: no dead scroll area, no gap below, at six sizes, sidebar open and collapsed', async ({ page, request }) => {
    test.setTimeout(240_000);
    for (const [w, h] of SIZES) for (const rail of [false, true]) {
      await boot(page, request, w, h, { rail }); await open(page);
      const g = await geo(page);
      const tag = `${w}x${h}${rail ? ' rail' : ''}`;
      if (w >= 800) {
        expect(g.mainScroll, `${tag} #main must not scroll on the desktop workspace`).toBeLessThanOrEqual(1);
        expect(Math.abs(g.gapToMain), `${tag} drawer bottom meets the workspace bottom`).toBeLessThanOrEqual(24);
        expect(g.bodyH, `${tag} body height`).toBeGreaterThanOrEqual(Math.min(160, g.drawerH * 0.5));
      } else {
        expect(g.bodyH, `${tag} flow body`).toBeGreaterThan(120);
      }
      expect(g.hOverflow, `${tag} horizontal overflow`).toBeLessThanOrEqual(1);
      expect(g.expanded).toBe('true');
    }
  });

  test('93 collapse keeps only the header, re-expand restores a useful height (never the collapsed one), repeatedly', async ({ page, request }) => {
    await boot(page, request, 1440, 900);
    await open(page); const first = await geo(page);
    for (let i = 0; i < 4; i++) {
      await close(page); const c = await geo(page);
      expect(c.bodyHidden).toBe(true); expect(c.drawerH).toBeLessThan(100); expect(c.expanded).toBe('false');
      expect(c.mainScroll).toBeLessThanOrEqual(1);
      await open(page); const e = await geo(page);
      expect(e.drawerH).toBe(first.drawerH); expect(e.bodyH).toBeGreaterThan(150); expect(e.mainScroll).toBeLessThanOrEqual(1);
    }
    await shot(page, 'after-expanded-1440x900.png');
  });

  test('94 stale persisted state (collapsed-header height, tiny, junk, huge) never produces a strip or overflow', async ({ page, request }) => {
    for (const stored of [{ open: true, height: 62, size: 'remembered', heights: { wide: 62 } }, { open: true, height: 5, heights: { wide: 20, medium: 'x' } },
      { open: true, height: 99999, size: 'remembered', heights: { wide: 99999 } }, { open: true, height: 'abc', size: 'zzz', heights: null }]) {
      await boot(page, request, 1440, 900, { stored });
      await open(page);   // junk records are rejected by McA.persist (defaults: closed); valid-but-stale ones restore open
      await expect(page.locator('#dr-body')).toBeVisible();
      const g = await geo(page);
      expect(g.drawerH).toBeGreaterThanOrEqual(160); expect(g.drawerH).toBeLessThanOrEqual(g.pageH);
      expect(g.mainScroll).toBeLessThanOrEqual(1); expect(g.bodyH).toBeGreaterThan(100);
    }
  });

  test('95 Fit, Maximize, restore, drag-resize and keyboard resize keep the layout bounded', async ({ page, request }) => {
    await boot(page, request, 1440, 900); await open(page);
    const base = await geo(page);
    await page.click('#dr-max'); await page.waitForTimeout(350);
    let g = await geo(page);
    expect(g.drawerH).toBeGreaterThan(base.drawerH); expect(g.mainScroll).toBeLessThanOrEqual(1);
    expect(await page.locator('#dr-max span').textContent()).toBe('Restore');
    expect(await page.locator('#page-workspace').getAttribute('data-dr-max')).toBe('true');
    await shot(page, 'after-maximized-1440x900.png');
    await page.click('#dr-max'); await page.waitForTimeout(350);
    g = await geo(page); expect(g.drawerH).toBe(base.drawerH); expect(g.wsMain).toBeGreaterThan(150);
    await page.click('#dr-fit'); await page.waitForTimeout(450);
    g = await geo(page); expect(g.drawerH).toBeGreaterThanOrEqual(160); expect(g.mainScroll).toBeLessThanOrEqual(1);
    await page.click('#dr-fit'); await page.waitForTimeout(350);
    const drag = async (dy: number) => {
      const hb = (await page.locator('#dr-resize').boundingBox())!;
      const x = hb.x + hb.width / 2, y = hb.y + hb.height / 2;
      await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x, y + dy, { steps: 6 }); await page.mouse.up(); await page.waitForTimeout(300);
      return geo(page);
    };
    g = await drag(-100); expect(g.drawerH).toBeGreaterThan(base.drawerH + 60);
    g = await drag(-2000); expect(g.drawerH).toBeLessThanOrEqual(g.pageH); expect(g.mainScroll).toBeLessThanOrEqual(1);
    g = await drag(3000); expect(g.drawerH).toBeGreaterThanOrEqual(160); expect(g.mainScroll).toBeLessThanOrEqual(1);
    await page.locator('#dr-resize').focus(); await page.keyboard.press('ArrowUp'); await page.waitForTimeout(250);
    const g2 = await geo(page); expect(g2.drawerH).toBeGreaterThanOrEqual(g.drawerH);
    await page.reload(); await page.waitForTimeout(1000);
    const g3 = await geo(page); expect(g3.expanded).toBe('true'); expect(g3.mainScroll).toBeLessThanOrEqual(1);
  });

  test('96 navigation and content scroll independently; every section keeps the layout bounded; Open full page works', async ({ page, request }) => {
    test.setTimeout(120_000);
    await boot(page, request, 1280, 720); await open(page);
    const links = page.locator('#dr-results .dr-secs .res-link'); const n = await links.count();
    expect(n).toBeGreaterThan(5);
    const ov = await page.evaluate(() => getComputedStyle(document.querySelector('#dr-results .dr-secs') as HTMLElement).overflowY);
    expect(ov).toBe('auto');
    const bad: string[] = [];
    for (let i = 0; i < n; i++) {
      await links.nth(i).click(); await page.waitForTimeout(250);
      const g = await geo(page);
      if (g.mainScroll > 1) bad.push(`section ${i}: #main scroll ${g.mainScroll}`);
      if (g.hOverflow > 1) bad.push(`section ${i}: h-overflow ${g.hOverflow}`);
      const pane = await page.evaluate(() => { const p = document.querySelector('#dr-results .dr-pane') as HTMLElement; return p.scrollWidth - p.clientWidth; });
      if (pane > 2) bad.push(`section ${i}: pane h-overflow ${pane}`);
    }
    expect(bad).toEqual([]);
    const full = page.locator('#dr-open-page');
    if (await full.isVisible()) { await full.click(); await expect(page).toHaveURL(/#\/results/); }
  });

  test('97 Tools mode (narrow), project switch and reload keep the drawer bounded; accent audit is clean', async ({ page, request }) => {
    await boot(page, request, 1100, 800); await open(page);
    await page.click('#dr-mode-tools'); await page.waitForTimeout(350);
    let g = await geo(page); expect(g.mainScroll).toBeLessThanOrEqual(1); expect(g.hOverflow).toBeLessThanOrEqual(1);
    await page.click('#dr-mode-results');
    await page.goto('/#/projects'); await page.waitForTimeout(500); await page.goto('/#/workspace'); await page.waitForTimeout(700);
    g = await geo(page); expect(g.expanded).toBe('true'); expect(g.mainScroll).toBeLessThanOrEqual(1);
    for (const [w, h] of [[1440, 900], [1280, 720]] as Array<[number, number]>) {
      await boot(page, request, w, h); await open(page);
      expect(summarise(fmt(await auditLayout(page)))).toEqual([]);
    }
  });

  test('98 no-part (empty) workspace: drawer expands bounded', async ({ page, request }) => {
    await boot(page, request, 1440, 900, { part: false }); await open(page);
    const g = await geo(page); expect(g.mainScroll).toBeLessThanOrEqual(1); expect(g.bodyH).toBeGreaterThan(150);
  });
});
