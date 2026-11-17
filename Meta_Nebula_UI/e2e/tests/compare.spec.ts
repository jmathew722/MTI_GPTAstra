import { test } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

// Opt-in: CAL=1. Builds docs/screenshots/compare-1672x941.png (reference left, running app right).
test.skip(!process.env.CAL, 'compare image is opt-in (CAL=1)');
const SHOTS = path.resolve(__dirname, '../../docs/screenshots');
const REF = path.resolve(__dirname, '../../design/reference/mcagent-workspace-approved.png');
const ACTUAL = process.env.CAL_ACTUAL || path.join(SHOTS, 'calibrated-demo-1672x941.png');
const b64 = (p: string) => fs.readFileSync(p).toString('base64');

test('compare image', async ({ page }) => {
  await page.setViewportSize({ width: 3364, height: 981 });
  await page.setContent(`<body style="margin:0;background:#000;color:#ddd;font:600 18px sans-serif"><div style="display:flex;gap:20px">
    <div><div style="height:40px;line-height:40px;padding-left:8px">Reference (approved screenshot, 1672x941)</div><img src="data:image/png;base64,${b64(REF)}" width="1672" height="941"></div>
    <div><div style="height:40px;line-height:40px;padding-left:8px">Actual (running app, Demo run, 1672x941)</div><img src="data:image/png;base64,${b64(ACTUAL)}" width="1672" height="941"></div></div></body>`);
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SHOTS, 'compare-1672x941.png') });
});
