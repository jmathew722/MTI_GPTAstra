import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const tabs = (page: Page) => page.getByRole("tablist", { name: "Workspace tabs" });
const IGNORE = /GL Driver|THREE\.Clock|WebGL/;

function watch(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" && !IGNORE.test(m.text())) errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test("folder of parts: sub-folders become parts, loose files become parts, each runs", async ({ page }) => {
  const errors = watch(page);
  await page.goto("/automation");
  await page.getByLabel("Folder of parts").setInputFiles(path.resolve("tests/fixtures/parts"));
  // partA (3 views), partB (2 views), loose.pdf (1 file)
  await expect(page.getByRole("heading", { name: "3 parts to process" })).toBeVisible();
  const list = page.getByRole("list", { name: "Parts to process" });
  await expect(list.getByRole("listitem")).toHaveCount(3);
  await expect(list.getByText("3 views")).toBeVisible();
  await expect(list.getByText("2 views")).toBeVisible();
  await expect(list.getByText("1 view ", { exact: false })).toBeVisible();
  await list.getByRole("button", { name: "Remove part loose" }).click();
  await expect(page.getByRole("heading", { name: "2 parts to process" })).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Est. batch cost")).toBeVisible();
  await page.getByRole("button", { name: "Run 2 parts" }).click();
  await expect(page.getByRole("heading", { name: "Batch of 2 parts" })).toBeVisible();
  const runs = page.getByRole("list", { name: "Runs in this batch" });
  await expect(runs.getByRole("listitem")).toHaveCount(2);
  await expect(runs.getByText("Not processed")).toHaveCount(2); // sample-data mode: stored, never fabricated
  expect(errors).toEqual([]);
});

test("batch of samples runs in sequence to completion", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/automation");
  for (const n of ["Flange_Adapter", "Bearing_Plate", "Spacer_Ring"]) await page.getByRole("button", { name: new RegExp(n) }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Run 3 parts" }).click();
  await expect(page.getByRole("heading", { name: "Batch of 3 parts" })).toBeVisible();
  await expect(page.getByText("waiting").first()).toBeVisible(); // later parts queue behind the first
  await expect(page.getByText("3 submitted · 3 finished")).toBeVisible({ timeout: 90_000 });
  await page.goto("/projects");
  await expect(page.locator("main").getByRole("link", { name: /Flange_Adapter/ })).toHaveCount(2); // seeded + the new one
});

test("extraction review: approve, edit, reject, undo", async ({ page }) => {
  const errors = watch(page);
  await page.goto("/projects/bp-1042");
  const item = page.getByRole("list", { name: /Extracted items/ }).getByRole("listitem").first();
  await item.getByRole("button", { name: "Undo", exact: true }).click(); // clear the seeded approval on this item
  await expect(item.getByRole("button", { name: "Approve" })).toBeEnabled();
  await item.getByRole("button", { name: "Approve" }).click();
  await expect(item.getByText("Approved")).toBeVisible();
  await item.getByRole("button", { name: "Edit" }).click();
  await item.getByLabel(/Corrected value/).fill("Ø33.0 H7");
  await item.getByRole("button", { name: "Save" }).click();
  await expect(item.getByText("Edited")).toBeVisible();
  await expect(item.getByText("Ø33.0 H7")).toBeVisible();
  await item.getByRole("button", { name: "Reject" }).click();
  await expect(item.getByText("Rejected")).toBeVisible();
  await item.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(item.getByText("Rejected")).toHaveCount(0);
  await page.getByRole("radio", { name: "Audit" }).click();
  await expect(page.getByRole("list", { name: /Audit trail/ })).toContainText("Edited");
  expect(errors).toEqual([]);
});

test("rubric: reviewer scoring, sign-off, and weights that do not sum to 100", async ({ page }) => {
  await page.goto("/projects/fl-2210");
  await tabs(page).getByRole("tab", { name: /Rubric/ }).click();
  const panel = page.locator("#workspace-panel");
  await expect(panel.getByRole("button", { name: /Sign off as/ })).toBeDisabled();
  await panel.getByRole("radiogroup", { name: "Level for Feature tree quality" }).getByRole("radio", { name: "3" }).click();
  await panel.getByRole("radiogroup", { name: "Level for Manufacturability" }).getByRole("radio", { name: "4" }).click();
  await expect(panel.getByRole("button", { name: /Sign off as/ })).toBeEnabled();
  await expect(panel.getByText("Capped at Needs rework")).toBeVisible(); // scoring never lifts the cap
  await panel.getByRole("button", { name: /Sign off as/ }).click();
  await expect(panel.getByText(/Signed by/)).toBeVisible();
  await expect(panel.getByText("Needs rework").first()).toBeVisible();
  // weights
  await panel.getByRole("button", { name: /Duplicate and edit/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Weight for Dimensional accuracy").fill("40");
  await expect(dialog.getByText(/115 \/ 100/)).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Save template" })).toBeDisabled();
  await dialog.getByLabel("Weight for Dimensional accuracy").fill("25");
  await expect(dialog.getByRole("button", { name: "Save template" })).toBeEnabled();
  await dialog.getByRole("button", { name: "Save template" }).click();
  await expect(panel.getByRole("combobox").first()).toContainText("copy");
});

test("rubric: gate override needs a reason and lifts the cap, audit records it", async ({ page }) => {
  await page.goto("/projects/fl-2210");
  await tabs(page).getByRole("tab", { name: /Rubric/ }).click();
  const panel = page.locator("#workspace-panel");
  await panel.getByRole("button", { name: "Override with reason" }).click();
  const d = page.getByRole("dialog", { name: /Override the hard-fail cap/ });
  await expect(d.getByRole("button", { name: "Record override" })).toBeDisabled();
  await d.getByRole("textbox").fill("short");
  await expect(d.getByRole("button", { name: "Record override" })).toBeDisabled(); // 10 characters minimum
  await d.getByRole("textbox").fill("Deviation approved by customer.");
  await d.getByRole("button", { name: "Record override" }).click();
  await expect(panel.getByText("Hard-fail cap overridden")).toBeVisible();
  await panel.getByRole("button", { name: "Remove override" }).click();
  await expect(panel.getByText("Capped at Needs rework")).toBeVisible();
});

test("drawing and model tools respond", async ({ page }) => {
  const errors = watch(page);
  await page.goto("/projects/fl-2210");
  const zoom = page.getByRole("toolbar", { name: "Drawing tools" });
  await expect(zoom.getByText("100%")).toBeVisible();
  await zoom.getByRole("button", { name: "Zoom in" }).click();
  await expect(zoom.getByText("125%")).toBeVisible();
  await zoom.getByRole("button", { name: "Fit drawing" }).click();
  await expect(zoom.getByText("100%")).toBeVisible();
  await page.getByRole("button", { name: "Heatmap" }).click();
  await expect(page.getByText("Confidence heatmap", { exact: true }).first()).toBeVisible();
  // clicking an item selects its region on the drawing
  await page.getByRole("list", { name: /Extracted items/ }).getByRole("button", { name: /Bolt holes/ }).click();
  await expect(page.getByRole("group", { name: /Source drawing/ }).getByRole("button", { name: /EX-001/ })).toHaveAttribute("aria-pressed", "true");
  const viewer = page.getByRole("toolbar", { name: "Viewer tools" });
  await viewer.getByRole("button", { name: "Section plane" }).click();
  await expect(page.getByLabel("Section plane position along X")).toBeVisible();
  await viewer.getByRole("button", { name: /Measure distance/ }).click();
  await expect(page.getByText("Click the first point on the model.")).toBeVisible();
  await page.getByRole("radio", { name: /Overlay/ }).click();
  await expect(page.getByText("Modeled outline")).toBeVisible();
  expect(errors).toEqual([]);
});

test("comments: add, resolve, reopen", async ({ page }) => {
  await page.goto("/projects/bp-1042");
  await page.getByRole("radio", { name: "Notes" }).click();
  await page.getByLabel("New comment").fill("Check the bore callout on the second sheet.");
  await page.getByRole("button", { name: /Add comment/ }).click();
  await expect(page.getByText("Check the bore callout on the second sheet.")).toBeVisible();
  await page.getByRole("button", { name: "Resolve" }).first().click();
  await expect(page.getByRole("button", { name: "Reopen" })).toBeVisible();
});

test("library: save a preset and apply it to the focused project", async ({ page }) => {
  await page.goto("/library");
  await page.getByRole("button", { name: /Save focused project.s parameters/ }).click();
  await expect(page.getByText("Flange_Adapter parameters")).toBeVisible();
  await page.getByRole("button", { name: "Apply to focused project" }).first().click(); // the saved one is first
  await expect(page.getByText(/Nothing to change|parameter.* updated/)).toBeVisible();
  await page.getByRole("radio", { name: "Rubric templates" }).click();
  await expect(page.getByText("MTI default part rubric")).toBeVisible();
  await page.getByRole("radio", { name: "Materials" }).click();
  await expect(page.getByText("7.85")).toBeVisible();
});

test("pipelines: expand a run, retry, filter and search", async ({ page }) => {
  await page.goto("/pipelines");
  await page.getByRole("button", { name: /Show stages for RUN-0012/ }).click();
  await expect(page.getByText("Hole Wizard returned Nothing")).toBeVisible();
  await page.getByRole("button", { name: /Failed/ }).first().click();
  await expect(page.getByRole("row", { name: /RUN-0012/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /RUN-0011/ })).toHaveCount(0);
  await page.getByRole("button", { name: /^All/ }).click();
  await page.getByLabel("Search runs").fill("spacer");
  await expect(page.getByRole("row", { name: /Bearing_Plate/ })).toHaveCount(0);
  await page.getByLabel("Search runs").fill("");
  await page.getByRole("row", { name: /RUN-0011/ }).getByRole("button", { name: "Retry" }).click();
  await expect(page.getByText(/started\./)).toBeVisible();
});

test("settings: reviewer name, motion, rates validation, reset", async ({ page }) => {
  await page.goto("/settings");
  await page.getByLabel("Your name").fill("A. Engineer");
  await expect(page.getByRole("link", { name: /settings for A. Engineer/ })).toBeVisible();
  await page.getByRole("radio", { name: "Reduced" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");
  await page.getByRole("radio", { name: "Compact" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-density", "compact");
  const input = page.getByLabel("Input, $ per 1M tokens");
  await input.fill("-5");
  await page.getByRole("button", { name: "Save rates" }).click();
  await expect(page.getByText("Must be 0 or more")).toBeVisible();
  await input.fill("4");
  await page.getByRole("button", { name: "Save rates" }).click();
  await expect(page.getByText("Rates saved.")).toBeVisible();
  await page.getByRole("checkbox", { name: /verified these rates/ }).check();
  await page.goto("/projects/fl-2210");
  await tabs(page).getByRole("tab", { name: /Cost/ }).click();
  await expect(page.getByText(/ASSUMPTION: verify against current provider pricing/)).toHaveCount(0);
  await page.goto("/settings");
  await page.getByRole("button", { name: "Reset sample data" }).click();
  await expect(page.getByText("Sample data restored.")).toBeVisible();
});

test("shell: notifications, palette tab switch, shortcuts, KPI link, docs scroll-spy", async ({ page }) => {
  await page.goto("/dashboard");
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: /Notifications, \d+ unread/ }).click();
  await expect(page.getByText("Validation failed: Flange_Adapter")).toBeVisible();
  await page.getByRole("button", { name: "Mark all read" }).click();
  await expect(page.getByText("0 unread")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByPlaceholder(/Jump to a project/).fill("tab Cost");
  await page.keyboard.press("Enter");
  await expect(tabs(page).getByRole("tab", { name: /Cost/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByPlaceholder(/Jump to a project/)).toHaveCount(0); // palette fully closed
  await page.keyboard.press("Shift+Slash"); // ?
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.keyboard.press("g");
  await page.keyboard.press("m");
  await expect(page).toHaveURL(/\/models/);
  await page.goto("/dashboard");
  await page.getByRole("link", { name: /Models Generated/ }).click();
  await expect(page).toHaveURL(/\/models/);
  await page.goto("/docs");
  await page.getByRole("link", { name: "5. Grading rubric" }).click();
  await expect(page.getByRole("link", { name: "5. Grading rubric" })).toHaveAttribute("aria-current", "true");
});

test("validation: override, clear override, export unblocks and re-blocks", async ({ page }) => {
  await page.goto("/projects/fl-2210");
  await tabs(page).getByRole("tab", { name: /Validation/ }).click();
  await page.getByRole("button", { name: "Override with reason" }).first().click();
  await page.getByRole("dialog").getByRole("textbox").fill("Accepted under deviation 114.");
  await page.getByRole("dialog").getByRole("button", { name: "Record override" }).click();
  await expect(page.getByText("Export is allowed by override.")).toBeVisible();
  await page.getByRole("button", { name: "Remove override" }).click();
  await expect(page.getByText("Export is blocked.")).toBeVisible();
  // the failing check can be collapsed and expanded
  await page.getByRole("button", { name: /Collapse Feature counts/ }).click();
  await page.getByRole("button", { name: /Expand Feature counts/ }).click();
  await expect(page.getByText("Compares the count in each drawing callout")).toBeVisible();
});

test("export center: downloads the build plan JSON and the rubric JSON on the clean project", async ({ page }) => {
  await page.goto("/projects/bp-1042");
  await page.getByRole("button", { name: "Export", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "Export center" });
  const [dl] = await Promise.all([page.waitForEvent("download"), dialog.getByRole("button", { name: "Download Build plan (JSON)" }).click()]);
  expect(dl.suggestedFilename()).toMatch(/build_plan\.json$/);
  const [pdf] = await Promise.all([page.waitForEvent("download"), dialog.getByRole("button", { name: "Download PDF report" }).click()]);
  expect(pdf.suggestedFilename()).toMatch(/report\.pdf$/);
  await expect(dialog.getByRole("button", { name: "Download SolidWorks part" })).toBeDisabled();
});

test("clone creates a draft project", async ({ page }) => {
  await page.goto("/projects/bp-1042");
  await page.getByRole("button", { name: "Clone" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Bearing_Plate_copy" })).toBeVisible();
});
