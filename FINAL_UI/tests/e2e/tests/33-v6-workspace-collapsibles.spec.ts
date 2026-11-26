import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import { auditLayout, summarise, Finding } from '../helpers/layout-audit';

// v6 workspace: "Material Selection" and "Runtime & cost" accordions, and the Pipeline Results drawer (starts closed, expands to the
// workspace bottom). Asserts COMPUTED boxes. Zoom is emulated through CDP (CSS viewport = size / zoom, deviceScaleFactor = zoom),
// which is what real browser zoom does to layout. Never starts a pipeline run: runs are simulated by dispatching store events.
const VERIFY = path.resolve(__dirname, '../../../docs/verification/v6');
const SIZES: Array<[number, number]> = [[1280, 720], [1366, 768], [1920, 1080], [2560, 1440]];
const ZOOMS = [0.8, 1, 1.25, 1.5];
const fmt = (fs_: Finding[]) => fs_.map((f) => `${f.kind} ${f.selector}: ${f.detail}`);
const shot = async (page: Page, name: string) => { fs.mkdirSync(VERIFY, { recursive: true }); await page.screenshot({ path: path.join(VERIFY, name) }); };

interface Opts { rail?: boolean; zoom?: number; part?: boolean; storedOpen?: boolean; route?: (page: Page) => Promise<void> }
async function boot(page: Page, request: any, w: number, h: number, o: Opts = {}) {
  const sc = await (await request.get('/api/scoring')).json();
  const p = (sc.parts || []).find((x: any) => x.has_output && x.session);
  const zoom = o.zoom || 1;
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: Math.round(w / zoom), height: Math.round(h / zoom), deviceScaleFactor: zoom, mobile: false });
  if (o.route) await o.route(page);
  await page.goto('/#/home'); await page.waitForFunction(() => !!(window as any).McA);
  await page.evaluate(([s, usePart, stored]: any) => {
    const P = (window as any).McA.persist;
    if (usePart && s) { P.set(P.KEYS.selected, { session: s.session, part: s.part }); P.set(P.KEYS.session, s.session); } else { P.remove(P.KEYS.selected); }
    // a stale stored OPEN drawer must never win
    localStorage.setItem('mca.ui.drawer', JSON.stringify({ open: !!stored, height: 320, section: 'overview', size: 'remembered', heights: {} }));
  }, [p, o.part !== false, o.storedOpen !== false]);
  await page.goto('/#/workspace'); await page.reload(); await page.waitForFunction(() => !!(window as any).McA);
  await expect(page.locator('#page-workspace')).toBeVisible(); await page.waitForTimeout(900);
  const tog = page.locator('#sb-toggle');
  if (o.rail !== undefined && await tog.isVisible().catch(() => false)) {
    if (((await tog.getAttribute('aria-expanded')) === 'true') === !!o.rail) { await tog.click(); await page.waitForTimeout(250); }
  }
}
const drOpen = async (page: Page, on: boolean) => {
  if (((await page.locator('#dr-toggle').getAttribute('aria-expanded')) === 'true') !== on) await page.locator('#dr-toggle').evaluate((e: HTMLElement) => e.click());
  await page.waitForTimeout(350);
};
const acc = (key: 'mat' | 'rt') => key === 'mat' ? { btn: '#mat-acc-btn', body: '#mat-acc-body' } : { btn: '#rt-acc-btn', body: '#run-estimate' };
async function accSet(page: Page, key: 'mat' | 'rt', on: boolean) {
  const a = acc(key), b = page.locator(a.btn);
  await b.scrollIntoViewIfNeeded();
  if (((await b.getAttribute('aria-expanded')) === 'true') !== on) await b.click();
  await expect(b).toHaveAttribute('aria-expanded', String(on));
}

/** Computed geometry. wsBottom = bottom of the workspace content box (page bottom minus its padding). */
async function geo(page: Page) {
  return page.evaluate(() => {
    const rect = (s: string) => { const e = document.querySelector(s) as HTMLElement | null; return e ? e.getBoundingClientRect() : null; };
    const main = document.getElementById('main') as HTMLElement, pgEl = document.getElementById('page-workspace') as HTMLElement;
    const d = rect('#drawer')!, pg = pgEl.getBoundingClientRect(), cv = rect('#canvas')!, head = rect('#drawer .dr-head')!, body = rect('#dr-body');
    const padB = parseFloat(getComputedStyle(pgEl).paddingBottom) || 0;
    const mb = main.getBoundingClientRect();
    return { vh: innerHeight, vw: innerWidth, drawerH: d.height, drawerTop: d.top, drawerBottom: d.bottom, wsBottom: pg.bottom - padB, mainBottom: mb.bottom,
      canvasH: cv.height, headTop: head.top, headBottom: head.bottom, bodyH: body ? body.height : 0, bodyHidden: (document.getElementById('dr-body') as HTMLElement).hidden,
      mainScroll: main.scrollHeight - main.clientHeight, hOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      expanded: document.getElementById('dr-toggle')!.getAttribute('aria-expanded'),
      bodyScrollable: body ? (document.getElementById('dr-body') as HTMLElement).scrollHeight - (document.getElementById('dr-body') as HTMLElement).clientHeight : 0 };
  });
}
const flatRoute = (matBody: any) => async (page: Page) => {
  await page.route('**/api/parts/*/*/material', (r) => (r.request().method() === 'GET' ? r.fulfill({ json: matBody }) : r.continue()));
};

test.describe('v6: workspace accordions and results drawer', () => {
  test('100 initial mount: drawer closed (stale stored open ignored), both accordions collapsed, no overflow', async ({ page, request }) => {
    test.setTimeout(240_000);
    for (const [w, h] of SIZES.slice(0, 3)) for (const rail of [false, true]) {
      await boot(page, request, w, h, { rail, storedOpen: true });
      const tag = `${w}x${h}${rail ? ' rail' : ''}`;
      const g = await geo(page);
      expect(g.expanded, `${tag} drawer closed on mount`).toBe('false');
      expect(g.bodyHidden, `${tag} drawer body hidden`).toBe(true);
      expect(g.hOverflow, `${tag} horizontal overflow`).toBeLessThanOrEqual(1);
      expect(g.mainScroll, `${tag} #main scroll`).toBeLessThanOrEqual(1);
      expect(Math.abs(g.drawerBottom - g.wsBottom), `${tag} closed header sits on the workspace bottom`).toBeLessThanOrEqual(4);
      for (const k of ['mat', 'rt'] as const) {
        const a = acc(k);
        await expect(page.locator(a.btn), `${tag} ${k}`).toHaveAttribute('aria-expanded', 'false');
        await expect(page.locator(a.body), `${tag} ${k} body hidden`).toBeHidden();
      }
      if (w === 1366 && !rail) await shot(page, 'after-closed-1366x768.png');
      if (w === 1920) await shot(page, `after-closed-1920x1080${rail ? '-rail' : ''}.png`);
    }
    // a fresh page load with a stored OPEN state: still closed, and after a reload too
    await page.reload(); await page.waitForTimeout(800);
    expect((await geo(page)).expanded).toBe('false');
  });

  test('101 accordion semantics: button, aria-expanded/controls, click + Enter + Space, visible focus, no clipping', async ({ page, request }) => {
    await boot(page, request, 1366, 768);
    for (const k of ['mat', 'rt'] as const) {
      const a = acc(k), b = page.locator(a.btn);
      expect(await b.evaluate((e) => e.tagName)).toBe('BUTTON');
      const controls = await b.getAttribute('aria-controls');
      expect('#' + controls).toBe(a.body);
      await b.scrollIntoViewIfNeeded(); await b.focus();
      const ring = await b.evaluate((e) => { const cs = getComputedStyle(e); return { w: parseFloat(cs.outlineWidth), st: cs.outlineStyle }; });
      expect(ring.st).not.toBe('none'); expect(ring.w).toBeGreaterThanOrEqual(2);       // visible focus ring (:focus-visible after keyboard focus)
      await page.keyboard.press('Enter'); await expect(b).toHaveAttribute('aria-expanded', 'true');
      await expect(page.locator(a.body)).toBeVisible();
      await page.keyboard.press('Space'); await expect(b).toHaveAttribute('aria-expanded', 'false');
      await expect(page.locator(a.body)).toBeHidden();
      await b.click(); await expect(b).toHaveAttribute('aria-expanded', 'true');
      const clip = await page.evaluate(([bodySel]: any) => {
        const body = document.querySelector(bodySel) as HTMLElement, insp = document.getElementById('inspector') as HTMLElement;
        const r = body.getBoundingClientRect(), ir = insp.getBoundingClientRect();
        return { inside: r.left >= ir.left - 1 && r.right <= ir.right + 1, overflowX: insp.scrollWidth - insp.clientWidth, bodyOverflow: body.scrollWidth - body.clientWidth };
      }, [a.body]);
      expect(clip.inside, `${k} body inside the inspector`).toBe(true);
      expect(clip.overflowX, `${k} inspector horizontal scroll`).toBeLessThanOrEqual(1);
      expect(clip.bodyOverflow, `${k} body horizontal overflow`).toBeLessThanOrEqual(1);
      await b.click(); await expect(b).toHaveAttribute('aria-expanded', 'false');
    }
  });

  test('102 material: expanded body keeps every control; collapsing never resets the selection; warnings stay in the summary', async ({ page, request }) => {
    const verified = { evaluated: true, resolution: { status: 'assigned_verified', chosen: { label: 'Steel 1018' }, selection_source: 'drawing' }, costing: { available: false, reason: 'x' } };
    await boot(page, request, 1366, 768, { route: flatRoute(verified) });
    const sum = page.locator('#mat-acc-sum');
    await expect(sum).toHaveText('Steel 1018', { timeout: 10_000 });
    await expect(page.locator('#mat-acc-warn')).toBeHidden();
    await accSet(page, 'mat', true);
    for (const id of ['mat-lib-lbl', 'mat-lib-line', 'mat-lib-view', 'mat-lib-refresh', 'mat-lib-clear', 'mat-lib-why', 'mat-part']) await expect(page.locator('#' + id), id).toBeVisible();
    await expect(page.locator('#mat-lib-path-box summary')).toBeVisible();
    // material cost row in Runtime & cost is separate from OpenAI cost
    await accSet(page, 'rt', true);
    await expect(page.locator('#rt-material')).toHaveText(/N\/A|estimate unavailable|\$/);
    // collapse / expand repeatedly: the same selection comes back each time
    for (let i = 0; i < 4; i++) {
      await accSet(page, 'mat', false); await expect(sum).toHaveText('Steel 1018');
      await accSet(page, 'mat', true); await expect(page.locator('#mat-part')).toContainText('Steel 1018');
    }
    // a blocking status stays visible in the collapsed summary
    await accSet(page, 'mat', false);
    await page.evaluate(() => {
      const McA = (window as any).McA, sl = McA.store.get().parts.selected;
      McA.materials.load({ kind: 'part', session: sl.session, part: sl.part }, true);
    });
    await page.unroute('**/api/parts/*/*/material');
    await page.route('**/api/parts/*/*/material', (r) => r.fulfill({ json: { evaluated: true, resolution: { status: 'unmatched', label: 'Unobtainium 9', chosen: null, selection_source: 'drawing' }, costing: null } }));
    await page.evaluate(() => { const McA = (window as any).McA, sl = McA.store.get().parts.selected; McA.materials.load({ kind: 'part', session: sl.session, part: sl.part }, true); });
    await expect(page.locator('#mat-acc-warn')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('#mat-acc-warn')).toContainText('Not in catalog');
    await expect(page.locator('#mat-acc-body')).toBeHidden();
    await expect(sum).toHaveAttribute('data-tone', 'amber');
    await shot(page, 'after-material-warning-collapsed-1366x768.png');
    // material API failure: still visible, not hidden by the collapse
    await page.unroute('**/api/parts/*/*/material');
    await page.route('**/api/parts/*/*/material', (r) => r.fulfill({ status: 500, json: { detail: 'catalog unreadable' } }));
    await page.evaluate(() => { const McA = (window as any).McA, sl = McA.store.get().parts.selected; McA.materials.load({ kind: 'part', session: sl.session, part: sl.part }, true); });
    await expect(page.locator('#mat-acc-warn')).toContainText('catalog unreadable', { timeout: 10_000 });
    await expect(sum).toHaveText('Unavailable');
  });

  test('103 empty workspace (no part): honest summaries, N/A values, no crash', async ({ page, request }) => {
    await boot(page, request, 1366, 768, { part: false });
    await expect(page.locator('#mat-acc-sum')).toHaveText('No material specified');
    await expect(page.locator('#rt-acc-sum')).toHaveText(/^(Idle|Estimate unavailable)$/);
    await accSet(page, 'rt', true);
    await expect(page.locator('#rt-material')).toHaveText('N/A');
    await expect(page.locator('#rt-live')).toBeHidden();
    await shot(page, 'after-empty-runtime-expanded-1366x768.png');
  });

  test('104 runtime: live values keep updating while collapsed; expanded rows aligned; no negatives; cancel stays reachable', async ({ page, request }) => {
    test.setTimeout(90_000);
    await boot(page, request, 1366, 768);
    const sum = page.locator('#rt-acc-sum');
    const sim = (kind: string) => page.evaluate((k) => {
      const McA = (window as any).McA, sl = McA.store.get().parts.selected, st = McA.store;
      if (k === 'start') { st.dispatch('run/queued', { kind: 'part', session: sl.session, part: sl.part }); st.dispatch('run/started', { id: 'v6sim', startedAt: Date.now() - 5000 }); }
      if (k === 'fail') st.dispatch('run/finalized', { id: 'v6sim', exit: 1, summary: null, payload: null });
    }, kind);
    await sim('start');
    await expect(sum).toHaveText(/^Running · \d+s$/);
    const secs = async () => parseInt(((await sum.textContent()) || '').replace(/\D+(\d+)s$/, '$1'), 10);
    const a = await secs(); await page.waitForTimeout(2300); const b = await secs();
    expect(b, 'header elapsed advances while collapsed').toBeGreaterThanOrEqual(a + 2);
    expect(await page.locator('#rt-acc-btn').getAttribute('aria-expanded')).toBe('false');
    // the live rows are filled even though the body is hidden
    const hiddenVals = await page.evaluate(() => ({ el: document.getElementById('rt-elapsed')!.textContent, status: document.getElementById('rt-status')!.textContent }));
    expect(hiddenVals.status).toBe('Run in progress'); expect(hiddenVals.el).toMatch(/\d/);
    const cancelBefore = await page.locator('#cancel-btn').isVisible();
    await accSet(page, 'rt', true);
    await expect(page.locator('#rt-live')).toBeVisible();
    for (const id of ['rt-elapsed', 'rt-left', 'rt-sofar']) await expect(page.locator('#' + id)).not.toHaveText('');
    await expect(page.locator('#rt-left')).not.toHaveText(/^-|\s-\d/);
    const e1 = await page.locator('#rt-elapsed').textContent(); await page.waitForTimeout(2200); const e2 = await page.locator('#rt-elapsed').textContent();
    expect(e2).not.toBe(e1);
    // no duplicated text: the one-line live string is not shown next to the rows
    await expect(page.locator('#est-live')).toBeHidden();
    // aligned rows: labels share a left edge, values share a right edge
    const al = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll('#run-estimate .rt-row:not([hidden])')).filter((r) => (r as HTMLElement).offsetParent) as HTMLElement[];
      const ks = rows.map((r) => Math.round(r.querySelector('.k')!.getBoundingClientRect().left)), vs = rows.map((r) => Math.round(r.querySelector('.v')!.getBoundingClientRect().right));
      return { n: rows.length, kSpread: Math.max(...ks) - Math.min(...ks), vSpread: Math.max(...vs) - Math.min(...vs), ho: document.getElementById('inspector')!.scrollWidth - document.getElementById('inspector')!.clientWidth };
    });
    expect(al.n).toBeGreaterThanOrEqual(6); expect(al.kSpread).toBeLessThanOrEqual(2); expect(al.vSpread).toBeLessThanOrEqual(2); expect(al.ho).toBeLessThanOrEqual(1);
    await shot(page, 'after-runtime-running-expanded-1366x768.png');
    // collapsing does not hide the cancel control nor stop the clock
    await accSet(page, 'rt', false);
    expect(await page.locator('#cancel-btn').isVisible()).toBe(cancelBefore);
    await page.waitForTimeout(1200); expect(await secs()).toBeGreaterThan(b);
    // a failed run: the error state is in the collapsed header; the drawer does NOT open by itself
    await sim('fail');
    await expect(sum).toHaveText(/^Failed/); await expect(sum).toHaveAttribute('data-tone', 'err');
    await page.waitForTimeout(600);
    expect((await geo(page)).expanded, 'drawer never auto-expands when a run ends').toBe('false');
    await accSet(page, 'rt', true);
    await expect(page.locator('#rt-status')).toHaveText('Failed');
    await expect(page.locator('#rt-live')).toBeHidden();
  });

  test('105 runtime: estimate failure is visible in the collapsed header; estimate rows say N/A, never $0', async ({ page, request }) => {
    await boot(page, request, 1366, 768, { route: async (p) => { await p.route('**/api/estimate**', (r) => r.fulfill({ status: 500, json: { detail: 'estimate service down' } })); } });
    await expect(page.locator('#rt-acc-sum')).toHaveText('Estimate unavailable', { timeout: 10_000 });
    await expect(page.locator('#rt-acc-sum')).toHaveAttribute('data-tone', 'warn');
    await accSet(page, 'rt', true);
    await expect(page.locator('#est-detail')).toContainText('estimate service down');
    await expect(page.locator('#run-estimate')).not.toContainText('$0.00');
  });

  test('106 drawer fills the workspace to its bottom edge: sizes x zoom x sidebar, header reachable, body scrolls inside', async ({ page, request }) => {
    test.setTimeout(600_000);
    const bad: string[] = [];
    for (const [w, h] of SIZES) for (const zoom of ZOOMS) for (const rail of [false, true]) {
      await boot(page, request, w, h, { rail, zoom });
      const tag = `${w}x${h} z${zoom}${rail ? ' rail' : ''}`;
      const closed = await geo(page);
      if (closed.expanded !== 'false') bad.push(`${tag}: not closed on mount`);
      await drOpen(page, true);
      const g = await geo(page);
      if (g.expanded !== 'true') { bad.push(`${tag}: did not open`); continue; }
      if (g.vw >= 800) {
        if (Math.abs(g.drawerBottom - g.wsBottom) > 4) bad.push(`${tag}: drawer bottom ${Math.round(g.drawerBottom)} vs workspace bottom ${Math.round(g.wsBottom)}`);
        if (g.mainScroll > 1) bad.push(`${tag}: #main scrolls ${g.mainScroll}`);
        if (g.headTop < 0 || g.headBottom > g.vh + 1) bad.push(`${tag}: drawer header not within the viewport (${Math.round(g.headTop)}..${Math.round(g.headBottom)} of ${g.vh})`);
        if (g.bodyH < 90) bad.push(`${tag}: body only ${Math.round(g.bodyH)}px`);
        // Below ~540 CSS px of height (150% zoom on a 720/768 screen) header + tracker leave less than the drawer's 160px minimum:
        // the viewers are then hidden by design (same as Maximize) and the drawer header's Fit/Maximize/close stay reachable.
        if (g.vh >= 540 && g.canvasH < 100) bad.push(`${tag}: viewers squeezed to ${Math.round(g.canvasH)}px`);
        if (g.drawerH < 160) bad.push(`${tag}: expanded drawer below its minimum (${Math.round(g.drawerH)}px)`);
        if (g.vh >= 700 && g.drawerH < 300) bad.push(`${tag}: expanded drawer is a strip (${Math.round(g.drawerH)}px of ${g.vh})`);
      }
      if (g.hOverflow > 1) bad.push(`${tag}: horizontal overflow ${g.hOverflow}`);
      const btns = await page.evaluate(() => ['dr-toggle', 'dr-fit', 'dr-max', 'dr-open-page'].map((id) => { const e = document.getElementById(id); if (!e) return id + ' missing'; const r = e.getBoundingClientRect(); const vis = r.width > 0 && r.height > 0; return vis && r.bottom <= innerHeight + 1 ? '' : id + ' not reachable'; }).filter(Boolean));
      btns.forEach((b: string) => { if (!(/dr-open-page/.test(b))) bad.push(`${tag}: ${b}`); });   // Open full page is hidden by design below 1600/800px breakpoints
      if (zoom === 1 && !rail && (w === 1366 || w === 1920)) await shot(page, `after-open-${w}x${h}.png`);
      if (zoom === 1.5 && !rail && w === 1366) await shot(page, 'after-open-1366x768-zoom150.png');
    }
    expect(bad).toEqual([]);
  });

  test('107 repeated open/close, resize, navigation and run transitions never accumulate an offset; closing returns space to the viewers', async ({ page, request }) => {
    test.setTimeout(240_000);
    await boot(page, request, 1366, 768);
    const base = await geo(page);
    const seen: number[] = [];
    for (let i = 0; i < 6; i++) {
      await drOpen(page, true); const o = await geo(page); seen.push(Math.round(o.drawerH));
      expect(Math.abs(o.drawerBottom - o.wsBottom)).toBeLessThanOrEqual(4);
      expect(o.canvasH).toBeLessThan(base.canvasH);
      await drOpen(page, false); const c = await geo(page);
      expect(Math.abs(c.canvasH - base.canvasH), `viewers get their space back (cycle ${i})`).toBeLessThanOrEqual(1);
      expect(Math.abs(c.drawerH - base.drawerH)).toBeLessThanOrEqual(1);
      expect(c.mainScroll).toBeLessThanOrEqual(1);
    }
    expect(Math.max(...seen) - Math.min(...seen), 'open height is stable').toBeLessThanOrEqual(1);
    // resize the window while open and closed
    await drOpen(page, true);
    for (const [w, h] of [[1100, 700], [1600, 900], [1366, 768]] as Array<[number, number]>) {
      await page.setViewportSize({ width: w, height: h }); await page.waitForTimeout(400);
      const g = await geo(page); expect(Math.abs(g.drawerBottom - g.wsBottom), `${w}x${h}`).toBeLessThanOrEqual(4); expect(g.mainScroll).toBeLessThanOrEqual(1);
    }
    // navigate away and back
    await page.goto('/#/projects'); await page.waitForTimeout(400); await page.goto('/#/workspace'); await page.waitForTimeout(700);
    const nav = await geo(page); expect(Math.abs(nav.drawerBottom - nav.wsBottom)).toBeLessThanOrEqual(4); expect(nav.mainScroll).toBeLessThanOrEqual(1);
    // simulated run transitions with the drawer open
    await page.evaluate(() => {
      const McA = (window as any).McA, sl = McA.store.get().parts.selected, st = McA.store;
      st.dispatch('run/queued', { kind: 'part', session: sl.session, part: sl.part }); st.dispatch('run/started', { id: 'v6t', startedAt: Date.now() });
    });
    await page.waitForTimeout(500); let t = await geo(page); expect(Math.abs(t.drawerBottom - t.wsBottom)).toBeLessThanOrEqual(4);
    await page.evaluate(() => (window as any).McA.store.dispatch('run/finalized', { id: 'v6t', exit: 1, summary: null, payload: null }));
    await page.waitForTimeout(500); t = await geo(page); expect(Math.abs(t.drawerBottom - t.wsBottom)).toBeLessThanOrEqual(4); expect(t.expanded).toBe('true');
    expect(Math.abs(t.drawerH - seen[0]) < 400).toBe(true);
    await drOpen(page, false);
  });

  test('108 Fit, Maximize/Restore, results navigation, resize handle (pointer + keyboard) and Open full page still work', async ({ page, request }) => {
    test.setTimeout(120_000);
    await boot(page, request, 1920, 1080); await drOpen(page, true);
    const g0 = await geo(page);
    await page.locator('#dr-max').click(); await page.waitForTimeout(350);
    let g = await geo(page);
    expect(await page.locator('#page-workspace').getAttribute('data-dr-max')).toBe('true');
    expect(Math.abs(g.drawerBottom - g.wsBottom)).toBeLessThanOrEqual(4); expect(g.drawerH).toBeGreaterThan(g0.drawerH);
    await expect(page.locator('#dr-max')).toContainText('Restore');
    await page.locator('#dr-max').click(); await page.waitForTimeout(350);
    g = await geo(page); expect(Math.abs(g.drawerH - g0.drawerH)).toBeLessThanOrEqual(2);
    await page.locator('#dr-fit').click(); await page.waitForTimeout(350);
    g = await geo(page); expect(Math.abs(g.drawerBottom - g.wsBottom)).toBeLessThanOrEqual(4); await page.locator('#dr-fit').click(); await page.waitForTimeout(300);
    // keyboard resize
    const before = (await geo(page)).drawerH;
    await page.locator('#dr-resize').focus(); await page.keyboard.press('ArrowDown'); await page.keyboard.press('ArrowDown'); await page.waitForTimeout(250);
    const after = (await geo(page)).drawerH; expect(after).toBeLessThan(before);
    await page.keyboard.press('ArrowUp'); await page.keyboard.press('ArrowUp'); await page.keyboard.press('ArrowUp'); await page.waitForTimeout(250);
    const up = await geo(page); expect(up.drawerH).toBeGreaterThan(after); expect(Math.abs(up.drawerBottom - up.wsBottom)).toBeLessThanOrEqual(4);
    // pointer drag
    const hb = await page.locator('#dr-resize').boundingBox();
    await page.mouse.move(hb!.x + hb!.width / 2, hb!.y + 5); await page.mouse.down(); await page.mouse.move(hb!.x + hb!.width / 2, hb!.y - 90, { steps: 6 }); await page.mouse.up(); await page.waitForTimeout(250);
    const dr = await geo(page); expect(dr.drawerH).toBeGreaterThan(up.drawerH + 40); expect(dr.mainScroll).toBeLessThanOrEqual(1);
    // results navigation
    const links = page.locator('#dr-results .dr-secs .res-link'); const n = await links.count(); expect(n).toBeGreaterThan(5);
    for (let i = 0; i < Math.min(n, 6); i++) { await links.nth(i).click(); await page.waitForTimeout(150); const q = await geo(page); expect(q.mainScroll).toBeLessThanOrEqual(1); expect(q.hOverflow).toBeLessThanOrEqual(1); }
    const full = page.locator('#dr-open-page');
    if (await full.isVisible()) { await full.click(); await expect(page).toHaveURL(/#\/results/); }
    expect(summarise(fmt(await (async () => { await page.goto('/#/workspace'); await page.waitForTimeout(500); return auditLayout(page); })()))).toEqual([]);
  });

  test('109 3D -> 2D page is unaffected (no workspace accordions, no script errors)', async ({ page, request }) => {
    const errs: string[] = []; page.on('pageerror', (e) => errs.push(e.message));
    await boot(page, request, 1440, 900);
    await page.goto('/#/reverse'); await page.waitForTimeout(800);
    await expect(page.locator('#page-reverse')).toBeVisible();
    await expect(page.locator('#mat-acc-btn')).toBeHidden(); await expect(page.locator('#rt-acc-btn')).toBeHidden();
    expect(errs).toEqual([]);
    await shot(page, 'after-reverse-1440x900.png');
  });

  test('110 accent audit with both accordions expanded and the drawer open', async ({ page, request }) => {
    for (const [w, h] of [[1440, 900], [1280, 720]] as Array<[number, number]>) {
      await boot(page, request, w, h); await accSet(page, 'mat', true); await accSet(page, 'rt', true); await drOpen(page, true);
      expect(summarise(fmt(await auditLayout(page)))).toEqual([]);
    }
  });
});
