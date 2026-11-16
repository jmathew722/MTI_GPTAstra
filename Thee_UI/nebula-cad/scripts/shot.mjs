// Quick screenshot helper: node scripts/shot.mjs <path> <out.png> [width] [height] [fullPage]
import { chromium } from "@playwright/test";
const [, , route = "/dashboard", out = "shot.png", w = "1440", h = "900", full = "0", wait = "1800"] = process.argv;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: Number(w), height: Number(h) } });
const errors = [];
page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errors.push(`[${m.type()}] ${m.text()}`); });
page.on("pageerror", (e) => errors.push(`[pageerror] ${e.message}`));
await page.goto(`http://localhost:3000${route}`, { waitUntil: "networkidle" });
await page.waitForTimeout(Number(wait));
await page.screenshot({ path: out, fullPage: full === "1" });
if (errors.length) console.log(errors.slice(0, 12).join("\n"));
await browser.close();
