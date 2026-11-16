// Captures every route at three viewports into ../docs/screenshots/<viewport>/.
// Usage: npm run shots [-- <baseURL>]   (the app must be running)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const base = process.argv[2] ?? "http://localhost:3000";
const out = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs/screenshots");
const ROUTES = [
  ["dashboard", "/dashboard"],
  ["projects", "/projects"],
  ["workstation-failing", "/projects/fl-2210"],
  ["workstation-clean", "/projects/bp-1042"],
  ["automation", "/automation"],
  ["models", "/models"],
  ["pipelines", "/pipelines"],
  ["viewer", "/viewer/fl-2210"],
  ["library", "/library"],
  ["docs", "/docs"],
  ["settings", "/settings"],
  ["welcome", "/welcome"],
];
const VIEWPORTS = [
  ["1440x900", 1440, 900],
  ["1024x768", 1024, 768],
  ["390x844", 390, 844],
];
const only = process.env.ONLY?.split(",");
const browser = await chromium.launch();
let problems = 0;
for (const [vp, width, height] of VIEWPORTS) {
  fs.mkdirSync(path.join(out, vp), { recursive: true });
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  for (const [name, route] of ROUTES) {
    if (only && !only.includes(name)) continue;
    const page = await ctx.newPage();
    const errors = [];
    page.on("console", (m) => {
      const t = m.text();
      if ((m.type() === "error" || m.type() === "warning") && !/GL Driver Message|THREE\.Clock|WebGL context was lost/.test(t)) errors.push(`[${m.type()}] ${t.slice(0, 220)}`);
    });
    page.on("pageerror", (e) => errors.push(`[pageerror] ${e.message}`));
    await page.goto(base + route, { waitUntil: "networkidle" });
    await page.waitForTimeout(/workstation|viewer|dashboard|welcome/.test(name) ? 3200 : 1200);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    await page.screenshot({ path: path.join(out, vp, `${name}.png`), fullPage: true });
    if (overflow > 1) errors.push(`[layout] horizontal overflow ${overflow}px`);
    if (errors.length) {
      problems += errors.length;
      console.log(`${vp} ${route}\n  ${[...new Set(errors)].join("\n  ")}`);
    }
    await page.close();
  }
  await ctx.close();
}
await browser.close();
console.log(problems ? `${problems} problem(s) logged.` : "No console errors, warnings or horizontal overflow.");
