"""SolidWorks feature-tree reader for the MTI practices score (spec 2026-10-25, 2b).

``read_tree(sw, sldprt)`` opens the part read-only (as ``sw_tasks.sldprt_to_step`` does), walks
the feature tree and closes it. The record, in tree order:

    [{"name": "Boss-Extrude1", "type": "Extrusion", "index": 7, "status": None,
      "subs": [{"name": "Sketch1", "type": "ProfileFeature", "status": 3}]}]

Every feature is recorded (origin, planes and folders included). ``status`` is the sketch's
``GetConstrainedStatus()`` (3 = fully defined, error log E023) on ``ProfileFeature`` features
and sub-features, else None.

Only SolidWorks APIs already used in this repo (hard rule 1): OpenDoc6, FirstFeature /
GetNextFeature, GetTypeName2, Name, GetFirstSubFeature / GetNextSubFeature,
GetSpecificFeature2, GetConstrainedStatus, CloseDoc. Features are read through their
early-bound interfaces as the IR compiler does (``pipeline.solidworks_builder.typed``).
win32com is imported lazily.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from bench import sw_tasks

CACHE = "feature_tree.json"
SKETCH = "ProfileFeature"
MAX_FEATURES = 100_000      # a cycle guard, never reached by a real part


def _typed(obj, iface: str):
    from pipeline.solidworks_builder import typed
    return typed(obj, iface)


def _first_feature(doc):
    from pipeline.solidworks_builder import _g
    return _g(doc, "FirstFeature")


def _status(f) -> Optional[int]:
    """A sketch's swConstrainedStatus_e, or None when it can't be read."""
    try:
        spec = f.GetSpecificFeature2()
        return None if spec is None else int(_typed(spec, "ISketch").GetConstrainedStatus())
    except Exception:
        return None


def _record(f) -> dict:
    typ = str(f.GetTypeName2())
    return {"name": str(f.Name), "type": typ, "status": _status(f) if typ == SKETCH else None}


def walk(doc) -> list[dict]:
    out: list[dict] = []
    raw = _first_feature(doc)
    while raw is not None and len(out) < MAX_FEATURES:
        f = _typed(raw, "IFeature")
        rec = _record(f)
        subs, sub = [], f.GetFirstSubFeature()
        while sub is not None and len(subs) < MAX_FEATURES:
            sf = _typed(sub, "IFeature")
            subs.append(_record(sf))
            sub = sf.GetNextSubFeature()
        out.append({"name": rec["name"], "type": rec["type"], "index": len(out), "status": rec["status"],
                    "subs": subs})
        raw = f.GetNextFeature()
    return out


def read_tree(sw, sldprt: Path) -> list[dict]:
    """Open ``sldprt`` read-only, return its feature-tree record, close it. Never saves."""
    sldprt = Path(sldprt).resolve()
    err, warn = sw_tasks._byref_long(), sw_tasks._byref_long()
    doc = sw.OpenDoc6(str(sldprt), sw_tasks.SW_DOC_PART, sw_tasks.OPEN_SILENT | sw_tasks.OPEN_READONLY,
                      "", err, warn)
    if doc is None:
        raise RuntimeError(f"OpenDoc6 failed for {sldprt} (error {err.value})")
    try:
        return walk(doc)
    finally:
        sw_tasks._cleanup([lambda: sw_tasks._close(sw, doc)], "close part")


def is_stale(part_dir: Path, sldprt: Path) -> bool:
    """True when there is no cache or it is older than the SLDPRT."""
    cache = Path(part_dir) / CACHE
    return not cache.is_file() or cache.stat().st_mtime < Path(sldprt).stat().st_mtime


def cached_tree(part_dir: Path, sldprt: Path, sw) -> Optional[list]:
    """``feature_tree.json`` if it is at least as new as the SLDPRT; otherwise the tree read via
    SolidWorks (written to the cache). With ``sw`` None, any cache is returned (the caller
    flags a stale one with ``is_stale``), else None."""
    cache = Path(part_dir) / CACHE
    if cache.is_file() and (sw is None or not is_stale(part_dir, sldprt)):
        return json.loads(cache.read_text(encoding="utf-8"))
    if sw is None:
        return None
    tree = read_tree(sw, sldprt)
    tmp = cache.with_name(cache.name + ".tmp")
    tmp.write_text(json.dumps(tree, indent=1), encoding="utf-8")
    os.replace(tmp, cache)
    return tree
