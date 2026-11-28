"""Hole Wizard acceptance matrix generator and live runner (Stage 4, task 4.13).

``--plan`` (no SolidWorks): one row per registry variant (all 81), each built from an exemplar intent and taken through
selection -> catalog resolution -> reference geometry. Writes ``docs/solidworks/hole-wizard/matrix-results.json``.

``--live``: additionally runs each non-legacy variant in a CHILD process with a watchdog (``InitializeHole`` can block
forever, error log E037): new part, block, create through the typed adapter, read the definition back, compare removed
volume to the analytic reference, save, close, reopen, read back again. The first variant is a PREFLIGHT: if it is
refused, null or blocked, the rest are recorded ``blocked_by_preflight`` instead of being hammered.

A variant is ``verified`` only when creation, definition readback, geometry, save/reopen AND the drawing-callout round
trip all passed. The callout round trip needs a drawing document and the Hole Callout API and is NOT implemented here,
so this tool can never set ``verified``: the best it can report is ``implemented_not_live_verified`` plus the live
columns it did pass. That is deliberate (see docs/solidworks/hole-wizard/support-status.md).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.ir.solidworks import hole_catalog as cat  # noqa: E402
from pipeline.ir.solidworks import hole_intent as hi  # noqa: E402
from pipeline.ir.solidworks.hole_capabilities import VARIANTS, Variant  # noqa: E402

RESULTS = ROOT.parent / "docs" / "hole-wizard" / "matrix-results.json"
LIVE_COLUMNS = ("created", "readback", "geometry", "reopen", "callout_roundtrip")
PLATE = (100.0, 60.0, 20.0)   # mm


# Layout-compatible SYNTHETIC stand-in for the confidential MTI table (values are illustrative, not MTI's). The matrix tests
# the resolution mechanics, not MTI's numbers; the real table is read by pipeline.mti_standards when present.
SYNTHETIC_STANDARD = {
    "inch": {"columns": ["size", "nominal", "preferred", "tap_drill", "clearance_normal", "cbore_d", "cbore_depth"],
             "rows": [["1/4", 0.25, True, 0.201, 0.266, 0.44, 0.30], ["5/16", 0.3125, True, 0.257, 0.330, 0.53, 0.37]]},
    "metric": {"columns": ["size", "nominal", "preferred", "tap_drill", "clearance_normal", "clearance_loose", "cbore_d", "cbore_depth"],
               "rows": [["M6", 6, True, 5.0, 6.4, 7.0, 11, 6.5], ["M8", 8, True, 6.8, 8.4, 10, 15, 8.6]]},
}


def use_synthetic_standard(directory) -> str:
    """Write the synthetic table under ``directory`` and point MTI_STANDARD_PATH at it (returns the path)."""
    p = Path(directory) / "synthetic_standard.local.json"
    p.write_text(json.dumps(SYNTHETIC_STANDARD), encoding="utf-8")
    os.environ["MTI_STANDARD_PATH"] = str(p)
    return str(p)


def exemplar(v: Variant) -> hi.HoleIntent:
    """A canonical, complete intent for a variant (mm, except pipe taps which use inch sizes)."""
    pipe = v.family == "pipe_tap"
    i = hi.HoleIntent(family=v.family, units="inch" if pipe else "mm", end=v.end, source="matrix")
    if v.end == "blind":
        i.depth = 12.0
    if v.family in ("hole", "counterbore", "countersink", "slot", "counterbore_slot", "countersink_slot"):
        i.diameter = 6.4
    if v.family in ("counterbore", "counterbore_slot"):
        i.cbore_diameter, i.cbore_depth = 11.0, 6.5
    if v.family in ("countersink", "countersink_slot"):
        i.csink_diameter, i.csink_angle = 12.4, 82.0
        if v.head_clearance is False:
            i.head_clearance = False
    for side in v.treatments:
        i.treatments[side] = {"diameter": 12.4, "angle": 90.0}
    if v.family in ("slot", "counterbore_slot", "countersink_slot"):
        i.slot_width, i.slot_length = 6.4, 20.0
    if v.family == "straight_tap":
        i.thread = {"designation": "M6x1", "system": "metric", "size": "M6", "pitch": 1.0, "class": "6H"}
        i.thread_mode = v.thread
        if v.end == "blind":
            i.thread_depth, i.drill_depth = 10.0, 12.0
    if pipe:
        i.thread = {"designation": "1/4-18", "size": "1/4-18", "standard": "NPT"}
        i.thread_mode = "plain"
        i.diameter = None
        if v.end == "blind":
            i.depth = 0.5          # inch (the exemplar is in inch for pipe taps)
    return i


def plan_row(v: Variant, table=None) -> dict:
    """The no-SolidWorks half of one matrix row."""
    row = {"value": v.value, "name": v.name, "family": v.family, "legacy": v.legacy}
    if v.legacy:
        row.update(selection="HW_LEGACY_POLICY", resolution=None, reference="n/a", status="not_implemented",
                   note="legacy hole types are chosen only by an explicit policy, never from drawing text")
        return row
    sel = hi.select_variant(exemplar(v))
    row["selection"] = "ok" if sel.ok and sel.variant.value == v.value else (sel.code or "wrong_variant")
    if row["selection"] != "ok":
        row.update(resolution=None, reference="n/a", status="not_implemented", note=sel.reason)
        return row
    res = cat.resolve(exemplar(v), v, table)
    row["resolution"] = "ok" if res.ok else res.code
    row["resolution_detail"] = res.reason or ("; ".join(res.warnings))
    try:
        from pipeline.ir.solidworks import hole_reference as ref
        vol = ref.analytic_volume(exemplar(v), PLATE[2], tap_drill=5.0)
        row["reference"] = "ok"
        row["reference_volume_mm3"] = round(vol, 6)
    except ref.ReferenceUnsupported as e:
        row["reference"] = "unsupported"
        row["reference_detail"] = str(e)
    row["status"] = "implemented_not_live_verified" if res.ok else "not_implemented"
    if not res.ok:
        row["note"] = res.reason
    return row


def live_columns_blank() -> dict:
    return {c: "not_run" for c in LIVE_COLUMNS}


def build_plan() -> dict:
    rows = [plan_row(v) for v in VARIANTS.values()]
    for r in rows:
        r["live"] = live_columns_blank()
    return {"generated_by": "tools/run_hole_wizard_matrix.py --plan", "total": len(rows), "rows": rows}


# ---- live ---------------------------------------------------------------------------------------------------------------
def _live_child(value: int) -> dict:
    """Runs in a child process. Returns the live columns for one variant."""
    import tempfile

    import win32com.client as w
    from pipeline.ir.solidworks import hole_adapter as ad
    from pipeline.ir.solidworks import hole_reference as ref
    from pipeline.solidworks_builder import connect_to_solidworks, create_new_part, typed

    v = VARIANTS[value]
    intent = exemplar(v)
    res = cat.resolve(intent, v, snapshot=cat.discover(w.GetActiveObject("SldWorks.Application")))
    out = live_columns_blank()
    if not res.ok:
        out["error"] = {"code": res.code, "detail": res.reason}
        return out
    app = connect_to_solidworks()
    doc = create_new_part(app, None)
    try:
        sm, fm = doc.SketchManager, doc.FeatureManager
        from pipeline.solidworks_builder import _total_volume, select_ref_plane
        select_ref_plane(doc, "Top Plane")
        sm.InsertSketch(True)
        sm.CreateCenterRectangle(0, 0, 0, PLATE[0] / 2000, PLATE[1] / 2000, 0)
        # extrude on the still-active sketch (error log E005/E006); same argument list as the repo's builder
        fm.FeatureExtrusion3(True, False, False, 0, 0, PLATE[2] / 1000, 0.01, False, False, False, False, 0.0, 0.0,
                             False, False, False, False, True, True, True, 0, 0.0, False)
        vol0 = _total_volume(doc)
        adapter = ad.HoleWizardAdapter(doc, fm, typed=typed)
        top = PLATE[2] / 1000

        def select_face():
            doc.ClearSelection2(True)
            return doc.Extension.SelectByRay(0, top + 1e-3, 0, 0, -1, 0, 1e-5, 2, False, 0, 0)
        o = adapter.create(intent, res, 0.001 if intent.units == "mm" else 0.0254, select_face)
        out["created"] = "ok" if o.ok else "failed"
        out["readback"] = "ok" if o.ok else "failed"
        if not o.ok:
            out["error"] = {"code": o.code, "detail": o.detail}
            out["mismatches"] = o.mismatches
            out["properties_set"] = o.properties_set
            return out
        vol1 = _total_volume(doc)
        k = 0.001 if intent.units == "mm" else 0.0254
        drill = None
        if v.family in ("straight_tap", "pipe_tap"):      # the tap drill comes from the catalog row, read back
            rb = adapter.read_back(o.feature, ["TapDrillDiameter", "ThruTapDrillDiameter"])
            drill = (rb.get("TapDrillDiameter") or rb.get("ThruTapDrillDiameter") or 0) / k or None
        want = ref.analytic_volume(intent, PLATE[2] * 0.001 / k, tap_drill=drill) * k ** 3
        if v.family == "pipe_tap":
            # a Hole Wizard pipe tap cuts a TAPERED bore; the reference models a straight tap-drill cylinder only, so the volume
            # cannot be a pass criterion. Recorded, never counted as verified.
            out["geometry"] = "not_modelled"
            out["geometry_detail"] = {"removed_m3": vol0 - vol1, "straight_reference_m3": want,
                                      "reason": "tapered bore: no independent reference geometry yet"}
        else:
            out["geometry"] = "ok" if abs((vol0 - vol1) - want) <= 1e-3 * want + 1e-12 else "failed"
            out["geometry_detail"] = {"removed_m3": vol0 - vol1, "reference_m3": want}
        path = os.path.join(tempfile.mkdtemp(prefix="hw_matrix_"), f"hw_{value}.SLDPRT")
        doc.SaveAs3(path, 0, 2)
        title = doc.GetTitle
        app.CloseDoc(title)
        import pythoncom
        from win32com.client import VARIANT
        err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        reopened = app.OpenDoc6(path, 1, 1, "", err, warn)
        out["reopen"] = "ok" if reopened is not None else "failed"
        if reopened is not None and out["geometry"] in ("ok", "not_modelled"):
            from pipeline.ir.solidworks import hole_callout_roundtrip as rt
            tap_in = drill * k / 0.0254 if drill else None
            rtres = rt.round_trip(app, None, path, intent, typed, tap_drill_in=tap_in)
            out["callout_roundtrip"] = rtres["status"]
            out["callout"] = {k2: rtres.get(k2) for k2 in ("parsed", "mismatches", "detail")}
        return out
    except ref.ReferenceUnsupported as e:
        out["error"] = {"code": "HW_REFERENCE_UNSUPPORTED", "detail": str(e)}
        return out
    except Exception as e:   # a Python error in the checker is its own code: it must not look like a dead COM server
        import traceback
        out["error"] = {"code": "HW_CHECK_ERROR", "detail": f"{type(e).__name__}: {e}"[:200], "trace": traceback.format_exc()[-400:]}
        return out
    finally:
        try:
            app.CloseAllDocuments(True)
        except Exception:
            pass


def run_child(value: int, timeout: float) -> dict:
    cmd = [sys.executable, str(Path(__file__)), "--child", str(value)]
    env = {**os.environ, "PYTHONUTF8": "1"}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        cols = live_columns_blank()
        cols["error"] = {"code": "HW_DIALOG_BLOCKED", "detail": f"no return after {timeout:g}s; process killed"}
        return cols
    for line in reversed(p.stdout.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    cols = live_columns_blank()
    cols["error"] = {"code": "HW_COM_ERROR", "detail": (p.stderr or p.stdout)[-200:]}
    return cols


def preflight_gate() -> dict:
    """Run the SOLIDWORKS 2025 environment gate against the running session (read-only). A failure here means NO child process
    is started: nothing that could open the modal database dialog is called."""
    try:
        import win32com.client as w
        app = w.GetActiveObject("SldWorks.Application")
    except Exception as e:      # noqa: BLE001
        return {"status": "failed", "code": "SW_NOT_RUNNING", "message": f"no running SOLIDWORKS session: {type(e).__name__}", "retryable": True}
    from pipeline.ir.solidworks import sw_preflight as pf
    res, extras = pf.run_live_preflight(app)
    return {**res.to_dict(), **{k: extras[k] for k in ("expected_version_source", "configured_root_is")}}


def run_live(plan: dict, timeout: float, preflight: dict | None = None) -> dict:
    pre = preflight if preflight is not None else preflight_gate()
    plan["preflight"] = pre
    blocked = None
    if pre.get("status") != "ready":
        blocked = {"code": pre.get("code"), "detail": pre.get("message"), "preflight_variant": None, "source": "environment_preflight"}
    for row in plan["rows"]:
        if row["legacy"] or row.get("resolution") != "ok" or row["reference"] != "ok":
            row["live"]["created"] = "not_attempted"
            continue
        if blocked:
            row["live"].update({c: "blocked_by_preflight" for c in LIVE_COLUMNS})
            row["live"]["error"] = blocked
            continue
        row["live"] = run_child(row["value"], timeout)
        err = row["live"].get("error")
        if err and err["code"] == "HW_DIALOG_BLOCKED" and not row.get("legacy"):   # a hang or a dead COM server stops the run; a per-variant refusal does not
            blocked = {**err, "preflight_variant": row["name"]}       # the first refusal blocks the rest
        passed = [c for c in LIVE_COLUMNS if row["live"].get(c) == "ok"]
        row["live_passed"] = passed
        live = row["live"]
        failed = bool(live.get("error")) or "failed" in (live.get("geometry"), live.get("reopen"), live.get("callout_roundtrip"))
        if failed:
            row["status"] = "failed_verification"
            e = live.get("error") or {}
            mm = live.get("mismatches") or []
            row["note"] = (f"{e.get('code', 'live check failed')}: {e.get('detail', '')} " +
                           (", ".join(f"{m['property']} wanted {m['wanted']} got {m['got']}" for m in mm[:4]) if mm else "")).strip()
    plan["live_preflight"] = blocked or {"code": None}
    return plan


def finalize(plan: dict) -> dict:
    from pipeline.ir.solidworks.hole_status import map_status, reason_for
    for r in plan["rows"]:
        live = r.get("live", {})
        if all(live.get(c) == "ok" for c in LIVE_COLUMNS):
            r["status"] = "verified"        # unreachable while callout_roundtrip is not implemented
    counts: dict = {}
    counts25: dict = {}
    pre = plan.get("preflight") or {}
    for r in plan["rows"]:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        r["status_2025"] = map_status(r["status"])
        r["status_reason"] = reason_for(r, pre if pre.get("status") == "failed" else None)
        if pre.get("status") == "failed" and r["status"] == "implemented_not_live_verified":
            r["environment_reason"] = pre.get("code")
        counts25[r["status_2025"]] = counts25.get(r["status_2025"], 0) + 1
    plan["status_counts"] = counts
    plan["status_2025_counts"] = counts25
    return plan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", action="store_true", help="no SolidWorks: selection, resolution and reference for all 81")
    ap.add_argument("--live", action="store_true", help="also create each variant in the running SolidWorks")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--child", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--out", default=str(RESULTS))
    a = ap.parse_args(argv)
    if a.child is not None:
        import tempfile
        use_synthetic_standard(tempfile.mkdtemp(prefix="hw_synth_"))
        print(json.dumps(_live_child(a.child)))
        return 0
    import tempfile
    use_synthetic_standard(tempfile.mkdtemp(prefix="hw_synth_"))
    plan = build_plan()
    if a.live:
        plan = run_live(plan, a.timeout)
        plan["ran_at_epoch"] = int(time.time())
    plan = finalize(plan)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(plan, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(plan["status_counts"]), json.dumps(plan["status_2025_counts"]), "preflight:", plan.get("live_preflight"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
