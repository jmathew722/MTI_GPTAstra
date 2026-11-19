import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { execFileSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { buildFixture, seedFlagsPart, STAGE2_OUT, uniq } from '../helpers/stage3';

test.skip(!STAGE2_OUT, 'STAGE2_OUT not set: start the server with MCAGENT_FINAL_OUTPUTS=$STAGE2_OUT and export STAGE2_OUT');

const EVID = path.resolve(__dirname, '../../../../docs/test-reports/recording-evidence');
const serious = (res: any) => res.violations.filter((v: any) => v.impact === 'serious' || v.impact === 'critical');

/** A part with a drawing, plus a recording written by the REAL recorder (synthetic frames, WebM). */
function seedRecording(part: string, kind: 'ready' | 'partial' | 'failed' | 'skipped' | 'none') {
  const fx = buildFixture(part, 0, 'main', false, 'none');
  let manifest: any = null;
  if (kind !== 'none') {
    const out = execFileSync(process.env.PYTHON || 'python', [path.resolve(__dirname, '../helpers/make_recording_fixture.py'),
      '--run-dir', fx.run_dir, '--part', part, '--kind', kind, '--sha', fx.sha256], { encoding: 'utf-8', env: { ...process.env, PYTHONUTF8: '1' } });
    manifest = JSON.parse(out.trim().split('\n').pop()!);
  }
  return { fx, manifest };
}
async function openRecording(page: any) {
  await page.evaluate(() => (window as any).McA.dom.setUi({ drawerOpen: true, drawerSection: 'recording', drawerMode: 'results' }));
  await expect(page.locator('#dr-results section[data-sec="recording"]')).toBeVisible({ timeout: 15_000 });
}

test.describe('Record Pipeline Run', () => {
  test('51 the checkbox sits under Force fresh extraction, is described, and ticking it sends record=true (and only then)', async ({ page, request }) => {
    const part = uniq(), { fx } = seedRecording(part, 'none');
    await seedFlagsPart(page, request, part, fx);
    await page.locator('#run-options summary').click();
    const force = page.getByLabel('Force fresh extraction'), rec = page.getByLabel('Record Pipeline Run');
    await expect(rec).toBeVisible();
    const yForce = (await force.boundingBox())!.y, yRec = (await rec.boundingBox())!.y;
    expect(yRec).toBeGreaterThan(yForce);                                                   // directly beneath it
    await expect(rec).toBeEnabled({ timeout: 10_000 });                                    // the capability check finished
    await expect(rec).not.toBeChecked();                                                    // off by default
    await expect(page.locator('#record-hint')).toContainText('only the SolidWorks window');
    expect(await rec.getAttribute('aria-describedby')).toBe('record-hint');

    const bodies: string[] = [];
    await page.route('**/api/run-part', async (route) => { bodies.push(route.request().postData() || ''); await route.fulfill({ json: { id: 'rid_fixture', part } }); });
    const letRun = () => page.evaluate(() => { const McA = (window as any).McA; McA.store.set({ server: Object.assign({}, McA.store.get().server, { live: true }) }); });
    await letRun();
    await page.locator('#run-btn').click();
    await expect.poll(() => bodies.length).toBe(1);
    expect(bodies[0]).not.toContain('name="record"');                                       // unticked: not sent

    await page.reload();
    await page.locator('#run-options summary').click();
    await expect(page.getByLabel('Record Pipeline Run')).toBeEnabled({ timeout: 10_000 });
    expect(await page.getByLabel('Record Pipeline Run').isChecked()).toBe(false);          // not remembered between sessions
    await page.getByLabel('Record Pipeline Run').check();
    await letRun();
    await page.locator('#run-btn').click();
    await expect.poll(() => bodies.length).toBe(2);
    expect(bodies[1]).toContain('name="record"');
    expect(bodies[1]).toContain('true');
  });

  test('52 when recording cannot work the box is disabled with the reason, never ticked', async ({ page, request }) => {
    const part = uniq(), { fx } = seedRecording(part, 'none');
    await page.route('**/api/recording/capability', (route) => route.fulfill({ json: { available: false, backend: null, encoder: null, reason: 'Recording needs Windows.' } }));
    await seedFlagsPart(page, request, part, fx);
    await page.locator('#run-options summary').click();
    const rec = page.getByLabel('Record Pipeline Run');
    await expect(rec).toBeDisabled();
    await expect(rec).not.toBeChecked();
    await expect(page.locator('#record-hint')).toHaveText('Not available: Recording needs Windows.');
  });

  test('53 a recorded run shows the video in Pipeline Results, with chapters that seek and a speed control', async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    fs.mkdirSync(EVID, { recursive: true });
    const part = uniq(), { fx, manifest } = seedRecording(part, 'ready');
    expect(manifest.status).toBe('ready');
    const session = await seedFlagsPart(page, request, part, fx);
    await openRecording(page);
    const sec = page.locator('#dr-results section[data-sec="recording"]');
    await expect(sec.locator('.rec-state')).toHaveAttribute('data-state', 'ready');
    const vid = sec.locator('video.rec-video');
    await expect(vid).toBeVisible();
    expect(await vid.getAttribute('src')).toContain(`/api/parts/${session}/${part}/recording.video`);
    await expect.poll(() => vid.evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThanOrEqual(1);   // the browser decoded it
    const dur = await vid.evaluate((v: HTMLVideoElement) => v.duration);
    expect(dur).toBeGreaterThan(3);
    const chapters = sec.locator('.rec-chap');
    await expect(chapters).toHaveCount(3);
    await expect(chapters.first()).toContainText('F001 prism: built');
    await chapters.nth(1).click();                                                          // jump to the second feature
    const ch2 = manifest.chapters[1].t;
    await expect.poll(() => vid.evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(ch2 - 0.6);
    await expect(chapters.nth(1)).toHaveAttribute('aria-current', 'true', { timeout: 5_000 });
    await vid.evaluate((v: HTMLVideoElement) => v.pause());
    await sec.getByRole('button', { name: '2x' }).click();
    await expect(sec.getByRole('button', { name: '2x' })).toHaveAttribute('aria-pressed', 'true');
    expect(await vid.evaluate((v: HTMLVideoElement) => v.playbackRate)).toBe(2);
    await expect(sec.getByRole('button', { name: 'Download the recording' })).toBeVisible();
    const vres = await request.get(`/api/parts/${session}/${part}/recording.video`, { headers: { Range: 'bytes=0-9' } });
    expect(vres.status()).toBe(206);                                                        // seekable
    expect((await request.get(`/api/parts/${session}/${part}/recording-poster.jpg`)).status()).toBe(200);
    expect(serious(await new AxeBuilder({ page }).include('#dr-results section[data-sec="recording"]').analyze())).toEqual([]);
    await page.screenshot({ path: path.join(EVID, 'recording-ready-1440x900.png') });
  });

  test('54 a partial recording is playable and says why it has gaps', async ({ page, request }) => {
    const part = uniq(), { fx, manifest } = seedRecording(part, 'partial');
    expect(manifest.status).toBe('partial');
    await seedFlagsPart(page, request, part, fx);
    await openRecording(page);
    const sec = page.locator('#dr-results section[data-sec="recording"]');
    await expect(sec.locator('.rec-state')).toHaveAttribute('data-state', 'partial');
    await expect(sec.locator('.rec-state')).toContainText('another window covered SolidWorks');
    await expect(sec.locator('video.rec-video')).toBeVisible();
  });

  test('55 failed, skipped and not-recorded runs say exactly why and show no player', async ({ page, request }) => {
    for (const [kind, text] of [['failed', 'SolidWorks window was not found'], ['skipped', 'never reached the SolidWorks build']] as const) {
      const part = uniq(), { fx } = seedRecording(part, kind);
      await seedFlagsPart(page, request, part, fx);
      await openRecording(page);
      const sec = page.locator('#dr-results section[data-sec="recording"]');
      await expect(sec.locator('.rec-state')).toHaveAttribute('data-state', kind);
      await expect(sec.locator('.rec-state')).toContainText(text);
      await expect(sec.locator('video')).toHaveCount(0);
    }
    const part = uniq(), { fx } = seedRecording(part, 'none');
    await seedFlagsPart(page, request, part, fx);
    await openRecording(page);
    const sec = page.locator('#dr-results section[data-sec="recording"]');
    await expect(sec).toContainText('Not recorded');
    await expect(sec).toContainText('Record pipeline run');
    await expect(sec.locator('video')).toHaveCount(0);
  });
});
