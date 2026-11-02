"""Live, narrated demo: a 2D drawing becomes a verified SolidWorks part.

Walks an audience through the Feature-IR pipeline one step at a time, pausing for
the presenter between steps, while SolidWorks builds the part on screen:

    1 the drawing  ->  2 what GPT-6 Astra read  ->  3 the build plan (numbers traced to
    drawing dimensions)  ->  4 Gate 1 checks  ->  5 CadQuery reference  ->  6 SolidWorks,
    feature by feature, each verified  ->  7 summary: questions it refused to guess, cost.

Modes:
    python demo.py                      # REPLAY (default): saved Astra extraction + plan. Free, no network.
    python demo.py --live               # Astra plans the part fresh in front of the room (~$0.2-0.5)
    python demo.py --part A040911E      # pick a dev part (default SB11033)
    python demo.py --part 2N2664 --from <output dir>   # an MTI audit part: ends by scoring the
                                        # result against MTI's own SolidWorks model
    python demo.py --no-pause --pace 0  # unattended rehearsal

Windows + SolidWorks for step 6 (use --no-solidworks to stop after the reference).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

ROOT = Path(__file__).resolve().parent
console = Console()
STEPS = 7   # 8 when MTI's own model is there to compare against


def quiet() -> None:
    """Keep the audience's screen to the narration: pipeline logs show errors only
    (e.g. image-prep 'nearly blank' warnings are routine on scanned sheets)."""
    for name in ("pipeline", ""):
        lg = logging.getLogger(name)
        lg.setLevel(logging.ERROR)
        for h in lg.handlers:
            h.setLevel(logging.ERROR)


def pause(args, msg="press Enter to continue"):
    if not args.no_pause:
        console.input(f"[dim]  >> {msg}[/dim]")


def step(n: int, title: str, blurb: str) -> None:
    console.print()
    console.print(Panel(f"[bold]{title}[/bold]\n[dim]{blurb}[/dim]", title=f"Step {n} of {STEPS}",
                        title_align="left", border_style="cyan"))


def summarize(f) -> str:
    """One readable line per plan feature, showing the expressions (the traceability)."""
    k = f.kind
    if k == "revolve":
        st = ", ".join(f"({s.z}, {s.r})" for s in f.outer[:4]) + (" ..." if len(f.outer) > 4 else "")
        return f"turned profile, {len(f.outer)} stations (z, r): {st}"
    if k == "prism":
        p = f.profile
        size = {"rect": lambda: f"{p.w} x {p.h}", "circle": lambda: f"dia {p.d}",
                "slot": lambda: f"slot {p.length} x {p.width}", "polygon": lambda: f"{len(p.points)}-gon"}[p.shape]()
        return f"{f.op} {p.shape} {size} at ({getattr(p, 'u', '-')}, {getattr(p, 'v', '-')}), depth {f.depth}"
    if k == "hole":
        s = f.spec
        extra = f", c'bore {s.cbore_d} x {s.cbore_depth}" if s.cbore_d else (f", depth {s.depth}" if s.depth else "")
        return f"{s.type} hole dia {s.d} at ({f.u}, {f.v}){extra}" + (f"  [{s.thread}]" if s.thread else "")
    if k == "pattern":
        return f"{f.mode} pattern of {f.seed} x {f.count}" + (f", pitch {f.pitch}" if f.mode != "circular" else "")
    if k == "edge_op":
        return f"{f.operation} {f.size} on {len(f.edges)} edge set(s)"
    return k


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--part", default="SB11033")
    ap.add_argument("--live", action="store_true", help="plan with GPT-6 Astra now (paid, budget-guarded)")
    ap.add_argument("--no-pause", action="store_true")
    ap.add_argument("--pace", type=float, default=1.5, help="seconds between SolidWorks features")
    ap.add_argument("--no-solidworks", action="store_true")
    ap.add_argument("--from", dest="src", type=Path, default=ROOT / "output",
                    help="MTI audit part folders (<dir>/<part>/source, plan.json, ground_truth.step)")
    args = ap.parse_args()

    from pipeline import budget
    from pipeline.ir.compile_cadquery import emit_script, run_script
    from pipeline.ir.from_v1 import dims_of, reference_ids
    from pipeline.ir.model import BuildPlan
    from pipeline.ir_pipeline import PartSpec, dev_parts, get_extraction, images_for
    from pipeline.schema import DrawingData
    from run_models import resolve_unknowns
    from pipeline.ir.compile_solidworks import compile_solidworks
    from pipeline.ir_pipeline import connect_sw

    quiet()   # after the imports: each module's logger setup resets the level

    global STEPS
    spec = next((s for s in dev_parts() if s.part == args.part), None)
    saved = ROOT / "output" / "ir_runs" / args.part
    if spec is None:   # an MTI audit part: drawing in <src>/<part>/source, saved run next to it
        saved = args.src / args.part
        pdfs = sorted(p for p in (saved / "source").glob("*") if p.suffix.lower() == ".pdf")
        if not pdfs or not (saved / "plan.json").exists():
            console.print(f"[red]Unknown part {args.part}: no dev part, and no {saved}/source/*.pdf with a "
                          f"saved plan.json. Dev parts: {[s.part for s in dev_parts()]}[/red]")
            return 2
        spec = PartSpec(args.part, pdfs[0])
    gt = saved / "ground_truth.step"   # MTI's own model, exported by mti_groundtruth.py
    STEPS = 8 if gt.exists() else 7
    out = ROOT / "output" / "demo" / spec.part
    out.mkdir(parents=True, exist_ok=True)
    t0, spent0 = time.time(), budget.spent_usd()

    console.print(Panel.fit(
        f"[bold]2D drawing -> verified SolidWorks part[/bold]\n"
        f"Part [bold cyan]{spec.part}[/bold cyan] · model GPT-6 Astra · mode "
        f"{'[bold yellow]LIVE[/bold yellow] (plans now)' if args.live else '[bold green]REPLAY[/bold green] (saved plan, free)'}",
        border_style="bold blue"))
    pause(args)

    # 1 -------------------------------------------------------------------------
    step(1, "The drawing", "A scanned engineering drawing: the only input. Full sheet first, then view crops.")
    images = images_for(spec)
    src = spec.views if spec.views.is_file() else spec.views / f"{spec.part}.png"
    console.print(f"  {len(images)} image(s): " + ", ".join(label for label, _, _ in images))
    console.print(f"  [dim]{src}[/dim]")
    if not args.no_pause:   # rehearsals stay quiet; in the meeting, show the drawing
        try:
            os.startfile(str(src))   # noqa: S606 - opens the drawing in the default viewer
        except Exception:
            pass
    pause(args)

    # 2 -------------------------------------------------------------------------
    step(2, "What GPT-6 Astra read", "Every dimension gets an ID (D001...). The plan may only use these IDs.")
    raw, how = get_extraction(spec, images, out, [saved, ROOT / "output" / "astra_2026-10-04", ROOT / "output" / "ir_runs"])
    resolve_unknowns(raw, spec.part)
    m = DrawingData.model_validate(raw)
    dims, refs = dims_of(m), reference_ids(m)
    t = Table(show_header=True, header_style="bold", box=None)
    for c in ("ID", "value", "what it is"):
        t.add_column(c)
    for d in m.dimensions[:18]:
        unit = "deg" if d.type.value == "angular" else d.unit.value
        t.add_row(d.id, f"{d.value:g} {unit}", (d.applies_to or "").replace("_", " ")[:60])
    console.print(t)
    if len(m.dimensions) > 18:
        console.print(f"  [dim]... {len(m.dimensions) - 18} more[/dim]")
    console.print(f"  [dim]{how}[/dim]")
    pause(args)

    # 3 -------------------------------------------------------------------------
    step(3, "The build plan", "Every coordinate is an expression over drawing dimensions, e.g. 'D001 / 2'. "
                              "Nothing is a free number unless the plan says why.")
    if args.live:
        from pipeline.planner import OpenAIPlanner
        from pipeline.token_tracker import scope
        with console.status("[bold yellow]GPT-6 Astra is planning the part from the drawing...[/bold yellow]"), \
                scope(part=spec.part):
            pr = OpenAIPlanner().plan(m, [(label, b64) for label, _, b64 in images], dims, refs)
        if pr.plan is None:
            console.print(f"[red]No plan ({pr.error}). Falling back to the saved plan.[/red]")
            plan = BuildPlan.model_validate(json.loads((saved / "plan.json").read_text(encoding="utf-8"))["plan"])
        else:
            plan = pr.plan
            (out / "plan.json").write_text(json.dumps({"dims": dims, "plan": plan.model_dump(mode="json")}, indent=2),
                                           encoding="utf-8")
    else:
        plan = BuildPlan.model_validate(json.loads((saved / "plan.json").read_text(encoding="utf-8"))["plan"])
    from pipeline.ir.defaults import apply_defaults, nominal_fractions
    plan, defaults = apply_defaults(plan, dims)   # documented answers to vague callouts
    dims, fractions = nominal_fractions(plan, dims, raw)
    defaults += fractions
    t = Table(show_header=True, header_style="bold", box=None)
    for c in ("ID", "feature", "status"):
        t.add_column(c)
    for f in plan.features:
        color = {"planned": "green", "unresolved": "yellow", "unsupported": "dim"}[f.status]
        t.add_row(f.id, summarize(f)[:95], f"[{color}]{f.status}[/{color}]")
    console.print(t)
    pause(args)

    # 4 -------------------------------------------------------------------------
    step(4, "Gate 1: deterministic checks", "Unknown dimensions, invented numbers, broken references: rejected "
                                            "before anything is built. Ambiguity becomes a question, not a guess.")
    findings = plan.check(dims, refs)
    hard = [f for f in findings if f.severity == "error" and f.code != "unresolved"]
    console.print("  [bold green]PASS[/bold green] - every number traces to the drawing" if not hard
                  else f"  [bold red]REJECT[/bold red] - {[f.message for f in hard]}")
    questions = [f for f in plan.features if f.status == "unresolved"]
    for f in questions:
        console.print(f"  [yellow]? question for an engineer[/yellow] {f.id}: {f.rationale}")
    for d in defaults:
        console.print(f"  [magenta]= default rule[/magenta] {d}")
    flagged = [f for f in plan.features if f.status == "planned" and f.justification]
    for f in flagged[:3]:
        console.print(f"  [cyan]i flagged for review[/cyan] {f.id}: {f.justification[:110]}")
    if hard:
        return 7
    pause(args)

    # 5 -------------------------------------------------------------------------
    step(5, "Reference model (CadQuery)", "An independent, deterministic build of the plan: the yardstick "
                                          "SolidWorks is checked against. Also exported as STEP.")
    with console.status("building the reference..."):
        cq = run_script(emit_script(plan, dims, strict=False), out)
    fm = cq.feature_map
    bb = fm["bbox"]
    console.print(f"  volume {fm['volume']:.4f} {plan.frame.units}^3 · size "
                  f"{bb[3] - bb[0]:.3f} x {bb[4] - bb[1]:.3f} x {bb[5] - bb[2]:.3f} {plan.frame.units}")
    holes = [h for hs in fm["holes"].values() for h in hs if h["measured"]]
    if holes:
        console.print(f"  {len(holes)} hole(s) measured on the reference solid")
    console.print(f"  [dim]{cq.step_path}[/dim]")
    pause(args, "press Enter to build it in SolidWorks")

    # 6 -------------------------------------------------------------------------
    sw_ok = None
    if not args.no_solidworks:
        step(6, "SolidWorks builds it, feature by feature", "After every feature the part's volume must match "
                                                           "the reference. A wrong direction is undone and retried.")
        with console.status("connecting to SolidWorks..."):
            app, pmap, template = connect_sw()
            try:
                app.Visible = True
            except Exception:
                pass

        def progress(f, res):
            ok = res.status == "built"
            mark = "[green]OK[/green]" if ok else ("[dim]--[/dim]" if res.status == "skipped" else "[red]!![/red]")
            note = "volume matches reference" if ok else res.status + (f" ({res.note})" if res.note else "")
            console.print(f"  {mark} {f.id:5s} {f.kind:8s} {note}")
            try:
                app.ActiveDoc.ViewZoomtofit2()
            except Exception:
                pass
            time.sleep(args.pace)

        rep = compile_solidworks(app, plan, dims, fm, out, template, pmap, progress=progress,
                                 keep_open=True)   # the audience looks at it
        sw_ok = rep.ok
        console.print(f"  final volume {'matches' if rep.volume_ok else 'DIFFERS'} · size "
                      f"{'matches' if rep.bbox_ok else 'DIFFERS'} · saved {rep.sldprt}")
        if rep.convention == "mti":
            console.print(f"  MTI conventions: origin {'centered' if rep.origin_ok else 'NOT centered'} on the base "
                          f"body · base sketch on the Top plane · through holes Up To Next")
        pause(args)

    # 7 (MTI parts) ---------------------------------------------------------------
    mti = None
    if gt.exists():
        step(7, "Compared with MTI's own SolidWorks model", "MTI's existing model of this part, never shown to "
             "the pipeline, as the answer key. Aligned, then overlap and surface distance.")
        import cadquery as cqm
        from pipeline.ir.score import aligned, clocked, iou, surface_deviation
        with console.status("comparing with MTI's model..."):
            a = cqm.importers.importStep(str(cq.step_path)).val()
            b = cqm.importers.importStep(str(gt)).val()
            value, key = iou(a, b)
            c = aligned(a, b, key) if key else None
            cv, _, c = clocked(c, b, base=value) if c is not None else (value, 0.0, None)
            dev = surface_deviation(c, b) if c is not None else None
            mti = (max(value, cv), a.Volume() / b.Volume(), dev)
        console.print(f"  overlap (IoU) [bold]{mti[0]:.4f}[/bold] · volume ratio {mti[1]:.4f}"
                      + (f" · surface distance mean {dev['mean']:.2f} mm, max {dev['max']:.2f} mm" if dev else ""))
        pause(args)

    # last ------------------------------------------------------------------------
    step(STEPS, "Result", "What a reviewing engineer gets.")
    cost = budget.spent_usd() - spent0
    lines = [
        f"Part [bold]{spec.part}[/bold]: "
        + ("[bold green]built in SolidWorks, every feature verified[/bold green]" if sw_ok
           else "[bold yellow]reference built[/bold yellow]" if sw_ok is None else "[bold red]check the log[/bold red]"),
        f"Features planned: {sum(f.status == 'planned' for f in plan.features)} · questions for an engineer: "
        f"{len(questions)} · values flagged for review: {len(flagged)} · default rules applied: {len(defaults)}",
        *([f"Against MTI's own model: overlap {mti[0]:.4f} · volume ratio {mti[1]:.4f}"] if mti else []),
        f"Time: {time.time() - t0:.0f} s (including pauses) · API cost this run: ${cost:.2f}"
        + ("" if args.live else " (replay)") + f" · budget used ${budget.spent_usd():.2f} of ${budget.cap_usd():.0f}",
        f"Files: {out}",
    ]
    console.print(Panel("\n".join(lines), border_style="bold green" if sw_ok else "yellow"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
