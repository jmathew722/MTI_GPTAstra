import { test, expect } from '@playwright/test';
import { spawn, spawnSync } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { boot, startDemo, uniq, watchConsole } from '../helpers/app';
import { drawingPng, pngFile } from '../helpers/fixtures';

const ROOT = path.resolve(__dirname, '../../..');

test.describe('Home (minimal layout)', () => {
  test('20 centered column, concise copy, one h1, no long text or old links', async ({ page }) => {
    const bad = watchConsole(page);
    for (const vp of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(vp);
      await page.goto('/#/home');
      await page.waitForFunction(() => !!(window as any).McA && (window as any).McA.store.get().session.id);
      const wrap = await page.locator('.home-wrap').boundingBox();
      expect(wrap!.width).toBeLessThanOrEqual(641);
      const main = await page.locator('#main').boundingBox();
      const mainCx = main!.x + main!.width / 2;
      expect(Math.abs(wrap!.x + wrap!.width / 2 - mainCx)).toBeLessThan(3);
      for (const sel of ['.home-tile', '#page-home h1', '.home-sub', '#home-drop', '#home-create', '.home-secondary']) {
        const b = (await page.locator(sel).first().boundingBox())!;
        expect(Math.abs(b.x + b.width / 2 - (wrap!.x + wrap!.width / 2)), sel + ' @' + vp.width).toBeLessThan(3);
      }
      // 390: nothing overflows horizontally.
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page, '#/home');
    await expect(page.locator('#page-home h1')).toHaveCount(1);
    await expect(page.locator('#page-home h1')).toHaveText('What would you like to create?');
    await expect(page.locator('.home-sub')).toHaveText('Turn your engineering drawings into 3D models.');
    await expect(page.locator('.dz-main')).toHaveText('Upload a drawing');
    await expect(page.locator('.dz-formats')).toHaveText('PDF, PNG, JPG, DWG, DXF');
    await expect(page.locator('#home-create')).toHaveAttribute('aria-disabled', 'true');
    await expect(page.locator('#home-create-reason')).toBeVisible();
    for (const t of ['Upload parts', 'Upload folder', 'Run demo']) await expect(page.locator('.home-secondary')).toContainText(t);
    await expect(page.locator('#home-demo .badge-c')).toHaveText('Demo');
    await expect(page.locator('#page-home')).not.toContainText(/No runs yet|Recent projects|Open sample|Nothing runs until/);
    const len = await page.locator('#page-home').evaluate((n) => (n as HTMLElement).innerText.length);
    expect(len).toBeLessThan(420);
    expect(bad, bad.join('\n')).toEqual([]);
  });

  test('21 dropzone is keyboard reachable and the create button stays disabled without a file', async ({ page }) => {
    await boot(page, '#/home');
    await page.locator('#home-file').focus();
    await expect(page.locator('#home-drop')).toBeVisible();
    await page.locator('#home-create').click({ force: true });
    await expect(page).toHaveURL(/#\/home/);
  });

  test('22 Upload parts: each file becomes its own part, remove works, nothing is run', async ({ page }) => {
    const bad = watchConsole(page);
    await boot(page, '#/home');
    const a = uniq('pa'), b = uniq('pb'), c = uniq('pc');
    await page.setInputFiles('#home-parts', [pngFile(`${a}.png`, 1), pngFile(`${b}.png`, 2), pngFile(`${c}.png`, 3)]);
    await expect(page.locator('#home-staged li')).toHaveCount(3);
    await expect(page.locator('#home-create-label')).toHaveText('Create 3 3D models');
    await page.locator(`#home-staged li button[aria-label="Remove ${c}"]`).click();
    await expect(page.locator('#home-staged li')).toHaveCount(2);
    await expect(page.locator('#home-create-label')).toHaveText('Create 2 3D models');
    let runPosts = 0;
    page.on('request', (r) => { if (r.method() === 'POST' && /\/api\/(run|demo|parts\/[^/]+\/[^/]+\/run)/.test(r.url())) runPosts++; });
    await page.click('#home-create');
    await expect(page).toHaveURL(/#\/projects/);
    await expect(page.locator('#proj-body .pcard-n', { hasText: a })).toBeVisible({ timeout: 20_000 });
    await expect(page.locator('#proj-body .pcard-n', { hasText: b })).toBeVisible();
    await expect(page.locator('#proj-body .pcard-n', { hasText: c })).toHaveCount(0);
    expect(runPosts).toBe(0);
    expect(bad, bad.join('\n')).toEqual([]);
  });

  test('23 Upload folder: subfolders are parts, loose files one part each', async ({ page }) => {
    const bad = watchConsole(page);
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mca-home-'));
    const a = uniq('fa'), b = uniq('fb'), solo = uniq('solo');
    try {
      fs.mkdirSync(path.join(root, a)); fs.mkdirSync(path.join(root, b));
      fs.writeFileSync(path.join(root, a, 'front.png'), drawingPng(320, 240, 1));
      fs.writeFileSync(path.join(root, a, 'top.png'), drawingPng(320, 240, 2));
      fs.writeFileSync(path.join(root, b, 'front.png'), drawingPng(320, 240, 3));
      fs.writeFileSync(path.join(root, `${solo}.png`), drawingPng(320, 240, 4));
      await boot(page, '#/home');
      await page.setInputFiles('#home-folder', root);
      await expect(page.locator('#home-staged li')).toHaveCount(3);
      await expect(page.locator('#home-staged li', { hasText: a })).toContainText('2 views');
      await expect(page.locator('#home-staged li', { hasText: solo })).toContainText('1 page');   // v4: a loose file shows its type and page count
      await expect(page.locator('#home-create-label')).toHaveText('Create 3 3D models');
      await page.click('#home-create');
      await expect(page).toHaveURL(/#\/projects/);
      for (const n of [a, b, solo]) await expect(page.locator('#proj-body .pcard-n', { hasText: n })).toBeVisible({ timeout: 20_000 });
    } finally { fs.rmSync(root, { recursive: true, force: true }); }
    expect(bad, bad.join('\n')).toEqual([]);
  });

  test('24 Projects and Home Recent never show demo data', async ({ page }) => {
    await boot(page, '#/home');
    await startDemo(page);
    for (const hash of ['#/projects', '#/home']) {
      await page.evaluate((h) => { location.hash = h; }, hash);
      const page_ = hash === '#/projects' ? '#page-projects' : '#page-home';
      await expect(page.locator(page_)).not.toContainText(/115C|116C|117C/);
    }
  });
});

test.describe('Launcher', () => {
  const sh = path.join(ROOT, 'run.sh');
  test('25 invalid MCAGENT_REPO / --repo gives a clear error and exits non-zero', async () => {
    test.skip(process.platform === 'win32', 'run.sh is for macOS / Linux');
    const missing = spawnSync('bash', [sh, '--repo', path.join(os.tmpdir(), 'no-such-repo-xyz')], { encoding: 'utf8' });
    expect(missing.status).not.toBe(0);
    expect(missing.stderr).toMatch(/does not exist/);
    const empty = fs.mkdtempSync(path.join(os.tmpdir(), 'mca-norepo-'));
    try {
      const bad = spawnSync('bash', [sh], { encoding: 'utf8', env: { ...process.env, MCAGENT_REPO: empty } });
      expect(bad.status).not.toBe(0);
      expect(bad.stderr).toMatch(/not a pipeline repo/);
      expect(bad.stderr).toMatch(/main\.py/);
    } finally { fs.rmSync(empty, { recursive: true, force: true }); }
  });

  test('26 launcher starts the server with an explicit --repo path', async () => {
    test.skip(process.platform === 'win32' || !process.env.E2E_REPO || !process.env.MCAGENT_PYTHON,
      'set E2E_REPO and MCAGENT_PYTHON to run');
    const data = fs.mkdtempSync(path.join(os.tmpdir(), 'mca-data-'));
    const port = '8211';
    const child = spawn('bash', [sh, '--repo', process.env.E2E_REPO!], { env: { ...process.env, PORT: port, MCAGENT_DATA: data }, stdio: 'pipe' });
    try {
      let ok = false;
      for (let i = 0; i < 40 && !ok; i++) {
        await new Promise((r) => setTimeout(r, 500));
        try { ok = (await fetch(`http://127.0.0.1:${port}/api/status`)).ok; } catch { /* not up yet */ }
      }
      expect(ok).toBe(true);
      const html = await (await fetch(`http://127.0.0.1:${port}/`)).text();
      expect(html).toContain('What would you like to create?');
      expect(fs.existsSync(path.join(data, 'parts'))).toBe(true);   // data lives in MCAGENT_DATA, not the repo
    } finally {
      child.kill('SIGINT');
      await new Promise((r) => setTimeout(r, 500));
      fs.rmSync(data, { recursive: true, force: true });
    }
  });
});
