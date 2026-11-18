import * as fs from 'fs';
import * as path from 'path';
import { APIRequestContext, expect, Page } from '@playwright/test';
import { drawingPng } from './fixtures';

/** The server must be started with MCAGENT_FINAL_OUTPUTS=$STAGE2_OUT so its part output folder is a temp dir. */
export const STAGE2_OUT = process.env.STAGE2_OUT || '';
export const PART = 'ZZSTAGE2';
export const N_ROWS = 120;
/** Rows 3, 7, 11, ... use a model with no price in the backend table: they must stay "Unpriced", never $0.00. */
export const N_UNPRICED = N_ROWS / 4;
export const PRICED_COST = 0.0125;                       // per priced row
export const EXPECTED_PART_TOTAL = (N_ROWS - N_UNPRICED) * PRICED_COST;   // 1.125
export const LONG_MODEL = 'a-deliberately-very-long-model-identifier-with-no-price-0123456789-abcdefghijklmnopqrstuvwxyz';

export function writeFixtureOutputs(): void {
  const dir = path.join(STAGE2_OUT, PART);
  fs.mkdirSync(path.join(STAGE2_OUT, 'usage'), { recursive: true });
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'ir_report.json'), JSON.stringify({ part: PART, gate1: 'OK', planned: 3, sw_ok: null, error: '' }));
  const rows: any[] = [];
  for (let i = 0; i < N_ROWS; i++) {
    const attempt = i < N_ROWS / 2 ? 1 : 2;
    const unpriced = i % 4 === 3;
    rows.push({
      ts: `2026-11-18T0${attempt}:${String(i % 60).padStart(2, '0')}:00+00:00`, run_id: `run_fixture_${attempt}`, run_attempt: attempt,
      row_id: `row_${i}`, role: i % 2 ? 'planner' : 'extractor', provider: 'fixture', model: unpriced ? LONG_MODEL : 'fixture-priced',
      part: PART, arm: '', gate: null, attempt: 1 + (i % 3), input_tokens: 1000 + i, output_tokens: 100 + i,
      cache_read_tokens: 500, cache_write_tokens: 0, latency_ms: 10, cache_hit: false,
      cost_usd: unpriced ? null : PRICED_COST, priced: !unpriced, ok: true, note: '', extra: {},
    });
  }
  // another part's rows share the ledger, as in the real FINAL_OUTPUTs/usage/usage_ledger.jsonl
  rows.push({ ts: '2026-11-18T05:00:00+00:00', run_id: 'run_other', run_attempt: 1, row_id: 'row_other', role: 'planner', provider: 'fixture',
    model: 'fixture-priced', part: 'OTHERPART', input_tokens: 1, output_tokens: 1, cache_read_tokens: 0, cache_write_tokens: 0,
    cache_hit: false, cost_usd: 99, priced: true, ok: true, note: '', extra: {} });
  fs.writeFileSync(path.join(STAGE2_OUT, 'usage', 'usage_ledger.jsonl'), rows.map((r) => JSON.stringify(r)).join('\n') + '\n');
}

/** Create the part through the real API, then open the app with it selected. */
export async function seedPart(page: Page, request: APIRequestContext): Promise<string> {
  writeFixtureOutputs();
  const session = (await (await request.post('/api/session')).json()).session as string;
  const up = await request.post('/api/parts', {
    multipart: { session, part: PART, source: { name: 'drawing.png', mimeType: 'image/png', buffer: drawingPng(640, 480, 1) } },
  });
  expect(up.ok()).toBeTruthy();
  await page.goto('/#/home');
  await page.waitForFunction(() => !!(window as any).McA);
  await page.evaluate(([sid, part]) => {
    const McA = (window as any).McA;
    McA.persist.set(McA.persist.KEYS.session, sid);
    McA.persist.set(McA.persist.KEYS.selected, { session: sid, part });
  }, [session, PART]);
  await page.evaluate(() => { location.hash = '#/workspace'; });
  await page.reload();
  await expect(page.locator('#ws-part')).toHaveText(PART, { timeout: 15_000 });
  return session;
}

export async function openCostDrawer(page: Page): Promise<void> {
  await page.evaluate(() => (window as any).McA.dom.setUi({ drawerOpen: true, drawerSection: 'cost', drawerMode: 'results' }));
  await expect(page.locator('#dr-results .cost-cards').first()).toBeVisible({ timeout: 15_000 });
}
