"""Benchmark prep CLI (spec 2026-10-23). Resumable; every step logs one line per part.

    python -m bench.prep copy --source "<MTI Example Drawings folder>"
    python -m bench.prep pdf | dxf | step | keys | check | link | review | status
    python -m bench.prep profile [--source "<MTI Example Drawings folder>"]
    python -m bench.prep signoff A050071E --by smcanuff

Options: --parts P1 P2 ... (default: all format-dev + held-out MTI parts), --force.

A step whose output already exists is skipped unless --force. `check` and `review` always
run (they are cheap and must follow the latest key). A failed part is logged and the batch
goes on; the exit code is 1 when any part failed, 2 for a configuration error, 3 when
SolidWorks is not reachable.

`check` regenerates the key from reference.step every time (so relabels from an earlier
cross-check can never carry over), copies over the resolutions a person already wrote for
flags that are still the same, and never touches a human-signed key unless --force.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from bench import config, crosscheck, dxfread, keygen, oda, profile, split, sw_tasks
from bench.features import Key
from bench.review import flag_line, render

MANIFEST = Path(__file__).resolve().parent / "manifest.yaml"
LOG_NAME = "prep_log.jsonl"
OLD_PLANS = config.CODE_ROOT / "output" / "ir_runs"

Output = Optional[Callable[[Path], Path]]
StepFn = Callable[[str, Path], Optional[str]]


# ---- the resumable loop --------------------------------------------------------------------

def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def log_line(log: Path, step: str, part: str, status: str, tool: str = "") -> None:
    rec = {"time": _now(), "step": step, "part": part, "status": status, "tool": tool}
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def run_step(step: str, parts: list[str], root: Path, output: Output, fn: StepFn, log: Path,
             force: bool, tool: str = "") -> dict[str, str]:
    """Run fn(part, root/part) for each part. Skipped when output(dir) exists (unless force;
    output=None means never skip). fn may return a status string (e.g. "skipped: ...").
    Exceptions become "failed: Type: msg" and the loop goes on. On any failure, including
    Ctrl-C, output(dir) is removed so a partial file is never skipped as done next time;
    KeyboardInterrupt / SystemExit are logged and then re-raised."""
    res: dict[str, str] = {}
    for part in parts:
        d = Path(root) / part
        d.mkdir(parents=True, exist_ok=True)
        stop: Optional[BaseException] = None
        if output is not None and output(d).exists() and not force:
            status = "skipped"
        else:
            try:
                status = fn(part, d) or "ok"
            except BaseException as e:  # noqa: BLE001 - one bad part must not stop the batch
                status = f"failed: {type(e).__name__}: {e}"[:300]
                if output is not None:
                    output(d).unlink(missing_ok=True)
                if not isinstance(e, Exception):
                    stop = e
        res[part] = status
        log_line(log, step, part, status, tool)
        print(f"{step:8} {part:10} {status}")
        if stop is not None:
            raise stop
    return res


# ---- context --------------------------------------------------------------------------------

@dataclass
class Ctx:
    root: Path
    args: argparse.Namespace
    manifest: dict
    parts: list[str]
    app: Any = None
    oda_cmd: list[str] = field(default_factory=list)

    @property
    def log(self) -> Path:
        return self.root / LOG_NAME

    def units(self, part: str) -> str:
        m = split.mti_entries(self.manifest)
        return next(e.get("units", "inch") for e in m["dev"] + m["held_out"] if e["part"] == part)

    def source_file(self, part: str, which: str) -> Path:
        """The copy in root/source/<part>/ of the pair's DWG ("dwg") or SLDPRT ("model")."""
        p = self.root / "source" / part / Path(getattr(split.pair(part), which)).name
        if not p.is_file():
            raise FileNotFoundError(f"{p} missing; run `copy` first")
        return p

    def run(self, step: str, output: Output, fn: StepFn, tool: str = "", root: Optional[Path] = None) -> int:
        res = run_step(step, self.parts, root or self.root, output, fn, self.log, self.args.force,
                       f"{tool} | bench@{_version()}" if tool else f"bench@{_version()}")
        failed = [p for p, s in res.items() if s.startswith("failed")]
        if failed:
            print(f"{step}: {len(failed)} of {len(res)} part(s) failed: {' '.join(failed)}")
        return 1 if failed else 0


_VERSION: Optional[str] = None


def _version() -> str:
    global _VERSION
    if _VERSION is None:
        try:
            r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.CODE_ROOT,
                               capture_output=True, text=True, timeout=10)
            _VERSION = r.stdout.strip() or "unknown"
        except Exception:  # noqa: BLE001
            _VERSION = "unknown"
    return _VERSION


# ---- steps ----------------------------------------------------------------------------------

def _within(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a == b or b in a.parents


def step_copy(ctx: Ctx) -> int:
    src = ctx.args.source
    if src is None or not Path(src).is_dir():
        print(f"copy: --source must be the MTI dataset folder (got {src!r})")
        return 2
    src = Path(src)
    if _within(src, ctx.root):
        print(f"copy: --source {src} is inside the data root {ctx.root}; refusing")
        return 2

    def fn(part: str, d: Path) -> None:
        pr = split.pair(part)
        files = [src / split.DWG_ROOT / pr.dwg, src / split.MODEL_ROOT / pr.model]
        for f in files:
            if not f.is_file():
                raise FileNotFoundError(f"not in the dataset: {f}")
        for f in files:
            dest = d / f.name
            if dest.resolve() == f.resolve():
                raise RuntimeError(f"refusing to copy {f} onto itself")
            shutil.copy2(f, dest)          # read-only use of the MTI original

    return ctx.run("copy", lambda d: d / Path(split.pair(d.name).model).name, fn, "shutil.copy2",
                   root=ctx.root / "source")


def _sw(ctx: Ctx, work: Callable[[Any, str, Path], None]) -> StepFn:
    """Wrap a SolidWorks step: reconnect before the next part after any failure (the COM
    connection drops after idle periods on this machine)."""
    def fn(part: str, d: Path) -> None:
        if ctx.app is None:
            ctx.app = sw_tasks.connect()
        try:
            work(ctx.app, part, d)
        except Exception:
            ctx.app = None
            raise
    return fn


def step_pdf(ctx: Ctx) -> int:
    return ctx.run("pdf", lambda d: d / "drawing.pdf",
                   _sw(ctx, lambda app, p, d: sw_tasks.dwg_to_pdf(app, ctx.source_file(p, "dwg"), d / "drawing.pdf")),
                   "SolidWorks COM")


def step_step(ctx: Ctx) -> int:
    return ctx.run("step", lambda d: d / "reference.step",
                   _sw(ctx, lambda app, p, d: sw_tasks.sldprt_to_step(
                       app, ctx.source_file(p, "model"), d / "reference.step", d / "model.png")),
                   "SolidWorks COM")


def step_dxf(ctx: Ctx) -> int:
    def fn(part: str, d: Path) -> None:
        oda.convert(ctx.source_file(part, "dwg"), d / "drawing.dxf", cmd=ctx.oda_cmd)
    return ctx.run("dxf", lambda d: d / "drawing.dxf", fn, f"ODA {Path(ctx.oda_cmd[0]).parent.name}")


def step_keys(ctx: Ctx) -> int:
    def fn(part: str, d: Path) -> None:
        keygen.from_step(d / "reference.step", units=ctx.units(part), part=part).save(d / "key.json")
    return ctx.run("keys", lambda d: d / "key.json", fn, "bench.keygen")


def _hand_edited(old: Key, raw: list[dict], checked: Key) -> bool:
    """True when old's features match neither the fresh keygen output (an untouched `keys`
    result) nor the fresh cross-checked key (an untouched `check` result; relabelling is
    idempotent, so a re-check of an untouched key compares equal)."""
    def bare(fs: list[dict]) -> list[dict]:          # links/tol come from `link`, not from an edit
        return [{k: v for k, v in f.items() if k not in ("tol", "links")} for f in fs]

    have = bare([asdict(f) for f in old.features])
    return have != bare(raw) and have != bare([asdict(f) for f in checked.features])


def step_check(ctx: Ctx) -> int:
    def fn(part: str, d: Path) -> str:
        path = d / "key.json"
        old = Key.load(path) if path.is_file() else None
        if old and (old.signoff or {}).get("kind") == "human" and not ctx.args.force:
            return "skipped: human sign-off kept (--force re-checks and clears it)"
        if not (d / "reference.step").is_file():
            raise FileNotFoundError(f"{d / 'reference.step'} missing; run `step` first")
        key = keygen.from_step(d / "reference.step", units=ctx.units(part), part=part)
        raw = [asdict(f) for f in key.features]
        drawing = dxfread.read(d / "drawing.dxf")
        flags = crosscheck.check(key, drawing)
        if old and not ctx.args.force and _hand_edited(old, raw, key):
            return "skipped: key.json hand-edited since last check (--force discards edits)"
        kept = {(f.kind, f.detail, f.feature): f.resolution for f in (old.flags if old else []) if f.resolution}
        for f in flags:
            f.resolution = kept.get((f.kind, f.detail, f.feature))
        key.flags, key.signoff = flags, None
        # a person's overrides are not feature edits: keep them, except those aimed at a feature
        # id the rebuilt key no longer has (reported in the step status / prep log)
        ids = {f.id for f in key.features}
        key.overrides = [o for o in (old.overrides if old else []) if "feature" not in o or o["feature"] in ids]
        dropped = sorted({o["feature"] for o in (old.overrides if old else [])
                          if "feature" in o and o["feature"] not in ids})
        n_dropped = len(old.overrides) - len(key.overrides) if old else 0
        crosscheck.link(key, drawing)                          # the rebuilt features need their links / tol
        crosscheck.sign_auto(key, f"bench.crosscheck@{_version()}")
        key.save(path)
        warn = (f"; WARNING dropped {n_dropped} override(s) for missing feature(s) {', '.join(dropped)}"
                if n_dropped else "")
        return (f"ok: {len(flags)} flag(s), {len(key.open_flags())} open, "
                f"{'auto-signed' if key.signed else 'needs a person'}{warn}")
    return ctx.run("check", None, fn, "bench.crosscheck")


def step_link(ctx: Ctx) -> int:
    """Record each key feature's drawing values and tolerances (crosscheck.link). Runs on
    human-signed keys too: it only writes `tol` / `links`, never flags, sign-off or geometry."""
    def fn(part: str, d: Path) -> str:
        path = d / "key.json"
        if not path.is_file():
            raise FileNotFoundError(f"{path} missing; run `keys` and `check` first")
        key = Key.load(path)
        crosscheck.link(key, dxfread.read(d / "drawing.dxf"))
        key.save(path)
        return f"ok: {sum(1 for f in key.features if f.links)} features linked"
    return ctx.run("link", None, fn, "bench.crosscheck.link")


def _drawing_png(pdf: Path, png: Path, force: bool) -> None:
    """Page 1 of drawing.pdf as a PNG (long edge ~1600 px), redone when the PDF is newer."""
    if not pdf.is_file() or (png.is_file() and not force and png.stat().st_mtime >= pdf.stat().st_mtime):
        return
    import pymupdf
    with pymupdf.open(pdf) as doc:
        page = doc[0]
        zoom = min(4.0, 1600 / max(page.rect.width, page.rect.height))
        page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).save(str(png))


def step_review(ctx: Ctx) -> int:
    def fn(part: str, d: Path) -> None:
        key = Key.load(d / "key.json")
        png = d / "drawing.png"
        _drawing_png(d / "drawing.pdf", png, ctx.args.force)
        (d / "review.html").write_text(render(key, png, d / "model.png"), encoding="utf-8")
    return ctx.run("review", None, fn, "bench.review")


def _keys(root: Path, entries: list[dict]) -> tuple[list[Key], list[str]]:
    keys, missing = [], []
    for e in entries:
        p = root / e["part"] / "key.json"
        if p.is_file():
            keys.append(Key.load(p))
        else:
            missing.append(e["part"])
    return keys, missing


def step_profile(ctx: Ctx) -> int:
    src = ctx.args.source
    if src is not None and not Path(src).is_dir():
        print(f"profile: --source {src!r} is not a folder")
        return 2
    m = split.mti_entries(ctx.manifest)
    dev_keys, miss_dev = _keys(ctx.root, m["dev"])
    held_keys, miss_held = _keys(ctx.root, m["held_out"])
    old: dict[str, int] = {}
    for e in ctx.manifest["splits"].get("dev") or []:
        plan = OLD_PLANS / e["part"] / "plan.json"
        if e.get("source") != "mti_bench" and plan.is_file():
            for t, n in profile.plan_type_counts(json.loads(plan.read_text(encoding="utf-8"))["plan"]).items():
                old[t] = old.get(t, 0) + n
    archive = profile.archive_keyword_counts(Path(src)) if src else {}
    dev, held = profile.type_counts(dev_keys), profile.type_counts(held_keys)
    flags = profile.bias_flags(dev, held)
    out = ctx.root / "profile.html"
    out.write_text(profile.render_html(dev, held, old, archive, flags), encoding="utf-8")
    unsigned = sum(1 for k in dev_keys + held_keys if not k.signed)
    status = f"ok: {len(flags)} bias flag(s), {len(dev_keys) + len(held_keys)} key(s), {unsigned} unsigned"
    if miss_dev or miss_held:
        status += f", no key: {' '.join(miss_dev + miss_held)}"
    log_line(ctx.log, "profile", "*", status, f"bench.profile | bench@{_version()}")
    print(f"profile: {out}")
    for f in flags:
        print(f"  bias flag: {f}")
    print(status)
    return 0


def _last_key_step(log: Path, part: str) -> Optional[str]:
    """'keys' or 'check': whichever last wrote this part's key.json (per prep_log.jsonl)."""
    last = None
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue                     # a half-written line (interrupted run)
            if not isinstance(r, dict) or not {"part", "step", "status"} <= r.keys():
                continue
            if r["part"] == part and r["step"] in ("keys", "check") and r["status"].startswith("ok"):
                last = r["step"]
    return last


def step_signoff(ctx: Ctx) -> int:
    part, by = ctx.args.part, ctx.args.by
    path = ctx.root / part / "key.json"
    if not path.is_file():
        print(f"signoff: {path} missing; run `keys` and `check` first")
        return 1
    if not ctx.log.is_file():
        print(f"signoff: {ctx.log} is missing, so the key's history is unknown; "
              f"run `check` first (python -m bench.prep check --parts {part})")
        return 1
    if _last_key_step(ctx.log, part) != "check":
        print(f"signoff: {part}'s key.json has not been cross-checked; run `check --parts {part}` first")
        return 1
    key = Key.load(path)
    if not crosscheck.sign_human(key, by):
        print(f"signoff: {part} has {len(key.open_flags())} open flag(s); write a resolution on each in {path}:")
        for i, f in enumerate(key.flags, 1):
            if not f.resolution:
                print(f"  {flag_line(i, f)}")
        return 1
    key.save(path)
    log_line(ctx.log, "signoff", part, f"ok: human by {by}", f"bench@{_version()}")
    print(f"signoff: {part} signed by {by}")
    return 0


def drawing_wins_resolution(kind: str, detail: str, by: str, date: str) -> str:
    """Resolution text for the "drawing is ground truth" policy (user decision 2026-10-24):
    keep the pair, record the difference, and score against the drawing. The scorer reads the
    prefix: `drawing-wins` = score the drawing's value; `drawing-silent` = the drawing doesn't
    state this model detail, so don't score it."""
    if kind == "unexplained_key_value":
        rule = "drawing-silent: model detail not stated on the drawing; do not score it"
    elif kind == "unexplained_position":
        rule = "drawing-silent: the drawing does not locate this feature; do not score its position"
    else:                                   # drawing values, counts, units, unparsed threads
        rule = "drawing-wins: score against the drawing, not the model"
    return f"{rule} ({detail}) [policy, {by} {date}]"


def step_accept(ctx: Ctx) -> int:
    """Resolve every open flag by the drawing-is-ground-truth policy and sign the key."""
    by = ctx.args.by
    if not by:
        print("accept: needs --by NAME")
        return 2
    failed = 0
    for part in ctx.parts:
        path = ctx.root / part / "key.json"
        if not path.is_file() or _last_key_step(ctx.log, part) != "check":
            print(f"accept   {part:10s} skipped: run `check --parts {part}` first")
            failed += 1
            continue
        key = Key.load(path)
        if key.signoff and key.signoff.get("kind") == "human":
            print(f"accept   {part:10s} already signed by {key.signoff.get('by')}")
            continue
        today = _now()[:10]
        n = 0
        for f in key.open_flags():
            f.resolution = drawing_wins_resolution(f.kind, f.detail, by, today)
            n += 1
        crosscheck.sign_human(key, by)
        key.save(path)
        log_line(ctx.log, "accept", part, f"ok: {n} flag(s) resolved by policy, signed by {by}",
                 f"bench@{_version()}")
        print(f"accept   {part:10s} {n} flag(s) resolved by policy, signed by {by}")
    return 1 if failed else 0


STATUS_FILES = (("pdf", "drawing.pdf"), ("dxf", "drawing.dxf"), ("step", "reference.step"),
                ("key", "key.json"), ("review", "review.html"))


def step_status(ctx: Ctx) -> int:
    head = f"{'part':10} " + " ".join(f"{n:>6}" for n, _ in STATUS_FILES) + f" {'flags':>5} {'open':>5}  signed"
    print(head)
    print("-" * len(head))
    for part in ctx.parts:
        d = ctx.root / part
        cells = " ".join(f"{'yes' if (d / f).is_file() else '-':>6}" for _, f in STATUS_FILES)
        n = n_open = "-"
        signed = "-"
        if (d / "key.json").is_file():
            try:
                k = Key.load(d / "key.json")
                n, n_open = str(len(k.flags)), str(len(k.open_flags()))
                if k.signed:
                    signed = f"{k.signoff['kind']} ({k.signoff.get('by', '')}, {k.signoff.get('date', '')})"
            except Exception as e:  # noqa: BLE001
                signed = f"unreadable key: {type(e).__name__}"
        print(f"{part:10} {cells} {n:>5} {n_open:>5}  {signed}")
    return 0


STEPS: dict[str, Callable[[Ctx], int]] = {
    "copy": step_copy, "pdf": step_pdf, "dxf": step_dxf, "step": step_step, "keys": step_keys,
    "check": step_check, "link": step_link, "review": step_review, "profile": step_profile, "signoff": step_signoff,
    "accept": step_accept, "status": step_status,
}


# ---- preflight + CLI ------------------------------------------------------------------------

def _preflight(step: str, ctx: Ctx) -> Optional[int]:
    """Stop before touching any part when a tool the step needs is missing."""
    if step in ("pdf", "step"):
        try:
            ctx.app = sw_tasks.connect()
        except sw_tasks.SwUnavailable as e:
            print(f"{step}: {e}")
            return 3
    if step == "dxf":
        ctx.oda_cmd = [str(config.oda_converter())]     # BenchConfigError -> exit 2 in main
    return None


def _load_manifest() -> dict:
    import yaml
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m bench.prep", description=__doc__.split("\n\n")[0])
    ap.add_argument("step", choices=list(STEPS))
    ap.add_argument("part", nargs="?", help="signoff only: the part to sign")
    ap.add_argument("--parts", nargs="+", help="default: all format-dev + held-out MTI parts")
    ap.add_argument("--source", help="MTI dataset folder (copy; optional for profile). Only read.")
    ap.add_argument("--by", help="signoff only: your name")
    ap.add_argument("--force", action="store_true", help="redo existing outputs / re-check human-signed keys")
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    manifest = _load_manifest()
    valid = split.bench_parts(manifest)
    asked = ([args.part] if args.step == "signoff" else args.parts) or []
    if args.step == "signoff" and (not args.part or not args.by):
        print("signoff needs a part and --by NAME")
        return 2
    unknown = [p for p in asked if p not in valid]
    if unknown:
        print(f"unknown part(s): {' '.join(unknown)}\nvalid parts: {' '.join(valid)}")
        return 2
    try:
        root = config.data_root()
        ctx = Ctx(root=root, args=args, manifest=manifest, parts=args.parts or valid)
        stop = _preflight(args.step, ctx)
        if stop is not None:
            return stop
        return STEPS[args.step](ctx)
    except config.BenchConfigError as e:
        print(f"configuration error: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
