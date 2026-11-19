import { execFileSync } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { APIRequestContext, expect, Page } from '@playwright/test';
import { STAGE2_OUT } from './stage2';

export { STAGE2_OUT };
export const uniq = () => 'ZZS3' + Date.now().toString(36).toUpperCase() + Math.floor(Math.random() * 1e3);

export interface Fixture {
  pdf: string; png: string; sha256: string; png_size: [number, number]; blue_blocks: number[][];
  expected_px: { tap: number[]; edge: number[] }; summary: any; run_dir: string; alt_pdf?: string;
}

/** Builds the drawing and runs the REAL pipeline stage (write_flags). No overlay position is passed in anywhere. */
export function buildFixture(part: string, rotation = 0, variant: 'main' | 'ambiguous' = 'main', alt = false, markup: 'none' | 'main' | 'clean' | 'fail' = 'none'): Fixture {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'flagfx-'));
  const args = [path.resolve(__dirname, 'make_flags_fixture.py'), '--out', STAGE2_OUT, '--part', part, '--rotation', String(rotation),
    '--variant', variant, '--workdir', work, '--markup', markup].concat(alt ? ['--alt'] : []);
  const out = execFileSync(process.env.PYTHON || 'python', args, { encoding: 'utf-8', env: { ...process.env, PYTHONUTF8: '1' } });
  return JSON.parse(out.trim().split('\n').pop()!);
}

export async function seedFlagsPart(page: Page, request: APIRequestContext, part: string, fx: Fixture): Promise<string> {
  const session = (await (await request.post('/api/session')).json()).session as string;
  const up = await request.post('/api/parts', { multipart: {
    session, part,
    source: { name: 'drawing.png', mimeType: 'image/png', buffer: fs.readFileSync(fx.png) },
    original: { name: 'drawing.pdf', mimeType: 'application/pdf', buffer: fs.readFileSync(fx.pdf) } } });
  expect(up.ok()).toBeTruthy();
  await page.goto('/#/home');
  await page.waitForFunction(() => !!(window as any).McA);
  await page.evaluate(([sid, p]) => {
    const McA = (window as any).McA;
    McA.persist.set(McA.persist.KEYS.session, sid);
    McA.persist.set(McA.persist.KEYS.selected, { session: sid, part: p });
  }, [session, part]);
  await page.evaluate(() => { location.hash = '#/workspace'; });
  await page.reload();
  await expect(page.locator('#ws-part')).toHaveText(part, { timeout: 15_000 });
  await expect(page.locator('#ov-img')).toBeVisible({ timeout: 15_000 });
  return session;
}

/** Where the drawing content and every flag box really are on screen (after any pan/zoom/resize). */
export async function geometry(page: Page) {
  return page.evaluate(() => {
    const img = document.getElementById('ov-img') as HTMLImageElement;
    const r = img.getBoundingClientRect(), nw = img.naturalWidth, nh = img.naturalHeight;
    const s = Math.min(r.width / nw, r.height / nh), cw = nw * s, ch = nh * s;
    const content = { left: r.left + (r.width - cw) / 2, top: r.top + (r.height - ch) / 2, w: cw, h: ch, nw, nh };
    const boxes = Array.from(document.querySelectorAll('.flag-box')).map((b) => {
      const q = b.getBoundingClientRect();
      return { id: b.getAttribute('data-finding')!, left: q.left, top: q.top, right: q.right, bottom: q.bottom, sev: b.getAttribute('data-sev') };
    });
    return { content, boxes };
  });
}

export function toScreen(g: Awaited<ReturnType<typeof geometry>>, px: number[]) {
  const c = g.content;
  return { left: c.left + (px[0] / c.nw) * c.w, top: c.top + (px[1] / c.nh) * c.h, right: c.left + (px[2] / c.nw) * c.w, bottom: c.top + (px[3] / c.nh) * c.h };
}

/** A flag box that encloses the callout (independent oracle) with a small tolerance, and is not a page-sized wash. */
export function enclosing(g: Awaited<ReturnType<typeof geometry>>, exp: { left: number; top: number; right: number; bottom: number }, tol = 5) {
  return g.boxes.filter((b) => b.left <= exp.left + tol && b.top <= exp.top + tol && b.right >= exp.right - tol && b.bottom >= exp.bottom - tol &&
    (b.right - b.left) * (b.bottom - b.top) < 4 * (exp.right - exp.left) * (exp.bottom - exp.top) + 400);
}
