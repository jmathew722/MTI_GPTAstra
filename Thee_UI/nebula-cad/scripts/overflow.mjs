import { chromium } from "@playwright/test";
const [, , route = "/dashboard", w = "390", h = "844"] = process.argv;
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: +w, height: +h } });
await p.goto("http://localhost:3000" + route, { waitUntil: "networkidle" });
await p.waitForTimeout(2500);
const r = await p.evaluate(() => {
  const vw = document.documentElement.clientWidth;
  return [...document.querySelectorAll("body *")]
    .map((e) => ({ e, r: e.getBoundingClientRect() }))
    .filter(({ r }) => r.right > vw + 1 && r.width > 0)
    .slice(0, 12)
    .map(({ e, r }) => `${e.tagName}.${String(e.className).slice(0, 70)} right=${Math.round(r.right)} w=${Math.round(r.width)}`);
});
console.log(r.join("\n"));
await b.close();
