import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const ROUTES: [string, RegExp][] = [
  ["/dashboard", /From Drawings to/],
  ["/projects", /Projects/],
  ["/projects/fl-2210", /Flange_Adapter/],
  ["/projects/bp-1042", /Bearing_Plate/],
  ["/automation", /New run/],
  ["/models", /Models/],
  ["/pipelines", /Pipelines/],
  ["/viewer/fl-2210", /Flange_Adapter/],
  ["/library", /Library/],
  ["/docs", /Docs/],
  ["/settings", /Settings/],
  ["/welcome", /From drawings to/],
];

/** Chromium's software GL prints driver chatter that is not an application problem. */
const IGNORE = /GL Driver Message|THREE\.Clock|WebGL context was lost|Download the React DevTools/;

function watch(page: Page) {
  const problems: string[] = [];
  page.on("console", (m) => {
    if ((m.type() === "error" || m.type() === "warning") && !IGNORE.test(m.text())) problems.push(`[${m.type()}] ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`[pageerror] ${e.message}`));
  return problems;
}

for (const [route, heading] of ROUTES) {
  test(`smoke ${route}: renders, no console errors, no horizontal overflow`, async ({ page }) => {
    const problems = watch(page);
    await page.goto(route);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1500);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    expect(problems).toEqual([]);
  });

  test(`axe ${route}: no serious or critical violations`, async ({ page }) => {
    // audit the settled page: entrance animations fade text in, which axe would read as low contrast
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(route);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(3500); // let the staggered entrance (opacity) finish before measuring contrast
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.help} (${v.nodes.length}) e.g. ${v.nodes[0]?.target.join(" ")} ${v.nodes[0]?.failureSummary ?? ""}`)).toEqual([]);
  });
}

test("navigation: top tabs and sidebar are exactly as specified", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByRole("navigation", { name: "Primary" }).getByRole("link")).toHaveText(["Dashboard", "Projects", "Automation", "Models", "Pipelines", "Docs"]);
  await expect(page.getByRole("navigation", { name: "Workspace" }).first().getByRole("link")).toHaveText(["Dashboard", "Projects", "Automation", "CAD Viewer", "Pipelines", "Library", "Settings"]);
  await expect(page.getByRole("tablist", { name: "Workspace tabs" }).getByRole("tab")).toHaveText([/Parameters/, /Features/, /Validation/, /Cost/, /Logs/, /Rubric/]);
});

test("workspace tabs: all six switch and are keyboard operable", async ({ page }) => {
  await page.goto("/projects/bp-1042");
  const tabs = page.getByRole("tablist", { name: "Workspace tabs" });
  const panel = page.locator("#workspace-panel");
  await tabs.getByRole("tab", { name: /Features/ }).click();
  await expect(panel.getByText("Extracted vs modeled")).toBeVisible();
  await tabs.getByRole("tab", { name: /Validation/ }).click();
  await expect(panel.getByText("Export is allowed.")).toBeVisible();
  await tabs.getByRole("tab", { name: /Cost/ }).click();
  await expect(panel.getByText("Pipeline run cost (AI and compute)")).toBeVisible();
  await expect(panel.getByText("Part manufacturing estimate")).toBeVisible();
  await expect(panel.getByText("Automation ROI")).toBeVisible();
  await tabs.getByRole("tab", { name: /Logs/ }).click();
  await expect(panel.getByRole("log")).toBeVisible();
  await tabs.getByRole("tab", { name: /Rubric/ }).click();
  await expect(panel.getByText("Total score")).toBeVisible();
  await tabs.getByRole("tab", { name: /Rubric/ }).press("Home");
  await expect(tabs.getByRole("tab", { name: /Parameters/ })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: /Features/ })).toHaveAttribute("aria-selected", "true");
});

test("parameters: out-of-range is kept and warned, not clamped; invalid is not saved", async ({ page }) => {
  await page.goto("/projects/bp-1042");
  const input = page.getByLabel("Thickness value in mm");
  await input.fill("40");
  await input.blur();
  await expect(page.getByText(/Outside 5\.000.25\.000\. Kept as entered\./)).toBeVisible();
  await expect(input).toHaveValue("40");
  await input.fill("abc");
  await input.blur();
  await expect(page.getByText("Not a number. Not saved.")).toBeVisible();
  await page.getByRole("button", { name: "Reset Thickness to the extracted value" }).click();
  await expect(input).toHaveValue("10");
});

test("command palette opens with the keyboard and jumps to a project", async ({ page }) => {
  await page.goto("/dashboard");
  await page.waitForLoadState("networkidle");
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByPlaceholder(/Jump to a project/).fill("bearing");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/projects\/bp-1042/);
});
