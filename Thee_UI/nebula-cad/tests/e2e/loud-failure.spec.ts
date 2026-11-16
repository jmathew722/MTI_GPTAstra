import { expect, test } from "@playwright/test";

/**
 * The showcase of why the tool exists, end to end:
 * upload flow -> mismatch -> loud banner -> blocked export -> override with reason -> rubric cap -> audit entry.
 */
test("loud failure: 10 holes on the drawing, 8 extracted", async ({ page }) => {
  // 1. upload flow, using the bundled synthetic flange drawing
  await page.goto("/automation");
  await page.getByRole("button", { name: /Flange_Adapter/ }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByLabel("Project name").fill("E2E_Flange");
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Estimate based on assumptions")).toBeVisible();
  await page.getByRole("button", { name: /Run 1 part/ }).click();
  await expect(page.getByText("Simulated run").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Re-run" })).toBeVisible({ timeout: 30_000 }); // shown once the run is no longer live
  await page.getByRole("link", { name: /Open project/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "E2E_Flange" })).toBeVisible();

  // 2. mismatch and the loud banner
  const banner = page.getByRole("alert").filter({ hasText: "The model does not match the drawing." });
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("Drawing calls out 10 bolt holes. Extraction found 8. Model has 8.");
  await expect(page.getByRole("table", { name: /Count checks/ })).toContainText("MISMATCH");

  // 3. export is blocked
  await page.getByRole("button", { name: "Export blocked" }).click();
  const dialog = page.getByRole("dialog", { name: "Export center" });
  await expect(dialog.getByText("Model deliverables are blocked")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Download STL mesh" })).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "Download PDF report" })).toBeDisabled();
  await dialog.getByRole("button", { name: "Open validation" }).click();

  // 4. the rubric is capped
  const tabs = page.getByRole("tablist", { name: "Workspace tabs" });
  await tabs.getByRole("tab", { name: /Rubric/ }).click();
  await expect(page.getByText("Capped at Needs rework")).toBeVisible();
  await expect(page.getByRole("button", { name: /Sign off as/ })).toBeDisabled(); // reviewer criteria not scored yet

  // 5. override the failing check with a recorded reason
  await tabs.getByRole("tab", { name: /Validation/ }).click();
  await expect(page.getByText("Export is blocked.")).toBeVisible();
  await page.getByRole("button", { name: "Override with reason" }).first().click();
  const od = page.getByRole("dialog", { name: "Override a critical check" });
  await expect(od.getByRole("button", { name: "Record override" })).toBeDisabled(); // a reason is required
  await od.getByRole("textbox").fill("Customer deviation 114 accepts the 8-hole pattern.");
  await od.getByRole("button", { name: "Record override" }).click();
  await expect(page.getByText("Export is allowed by override.")).toBeVisible();
  await expect(page.getByText(/Customer deviation 114/).first()).toBeVisible();
  // the check itself still reads Failed: an override is not a pass
  await expect(page.locator("#workspace-panel li").filter({ hasText: "Feature counts match the drawing" }).getByText("Failed", { exact: true })).toBeVisible();

  // 6. export now allowed, and the cap is lifted only through that override
  await page.getByRole("button", { name: "Export", exact: true }).first().click();
  await expect(page.getByRole("dialog", { name: "Export center" }).getByRole("button", { name: "Download STL mesh" })).toBeEnabled();
  await page.keyboard.press("Escape");
  await tabs.getByRole("tab", { name: /Rubric/ }).click();
  await expect(page.getByText("Hard-fail cap overridden")).toBeVisible();

  // 7. audit entry
  await page.getByRole("radio", { name: "Audit" }).click();
  const audit = page.getByRole("list", { name: /Audit trail/ });
  await expect(audit).toContainText("override check");
  await expect(audit).toContainText("Customer deviation 114 accepts the 8-hole pattern.");
});

test("clean project: passes, export allowed, can be signed off", async ({ page }) => {
  await page.goto("/projects/bp-1042");
  await expect(page.getByText("The model does not match the drawing.")).toHaveCount(0);
  await page.getByRole("tablist", { name: "Workspace tabs" }).getByRole("tab", { name: /Rubric/ }).click();
  await expect(page.getByText("Capped at Needs rework")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Sign off as/ })).toBeEnabled();
});

test("a user's own upload is never given a fabricated extraction", async ({ page }) => {
  await page.goto("/automation");
  await page.getByLabel("Drawing files").setInputFiles({ name: "my_part.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF\n") });
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText(/they are not processed/)).toBeVisible();
  await page.getByRole("button", { name: /Run 1 part/ }).click();
  await page.getByRole("link", { name: /Open project/ }).click();
  await expect(page.getByText("No extraction for this project")).toBeVisible();
  await page.getByRole("tablist", { name: "Workspace tabs" }).getByRole("tab", { name: /Validation/ }).click();
  await expect(page.getByText("No checks have run")).toBeVisible();
});

test("upload validation rejects unsupported files", async ({ page }) => {
  await page.goto("/automation");
  await page.getByLabel("Drawing files").setInputFiles({ name: "malware.exe", mimeType: "application/octet-stream", buffer: Buffer.from("x") });
  await expect(page.getByRole("alert").filter({ hasText: "unsupported type" })).toBeVisible();
});

test("approving an item raises no console error, and a project with no model says Static preview", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" && !/GL Driver|THREE\.Clock|WebGL/.test(m.text())) errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/projects/fl-2210");
  await page.getByRole("button", { name: "Approve" }).first().click();
  await page.getByRole("button", { name: /Zoom in/ }).click();
  await page.waitForTimeout(800);
  expect(errors).toEqual([]);

  await page.goto("/automation");
  await page.getByLabel("Drawing files").setInputFiles({ name: "nomodel.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF\n") });
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: /Run 1 part/ }).click();
  await page.getByRole("link", { name: /Open project/ }).click();
  await expect(page.getByText("Static preview")).toBeVisible();
});
