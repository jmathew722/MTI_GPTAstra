"""The serialized Windows CAD worker for 3D -> 2D: one SOLIDWORKS session, one thread, COM only.

Rules enforced here (architecture spec):
* the source SLDPRT is only ever opened silently and never saved; its SHA-256 is compared before and after the job;
* documents the user already had open are never closed; only documents this worker opened are closed;
* global preferences we change (STL export) are captured and restored even on failure;
* every constant comes from the installed type library (see ``api_validation.md``), never guessed.
"""
from __future__ import annotations

import logging
import math
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# swDocumentTypes_e / swUserPreference* / swLengthUnit_e values, read from the installed 2025 type library (api_validation.md)
SW_DOC_PART, SW_DOC_ASM, SW_DOC_DRW = 1, 2, 3
OPEN_SILENT = 1                       # swOpenDocOptions_Silent. NOT ReadOnly (2): see error log E025
PREF_STL_BINARY = 69                  # swSTLBinaryFormat (toggle)
PREF_STL_QUALITY = 78                 # swSTLQuality (integer); 2 = Fine
PREF_STL_UNITS = 211                  # swExportStlUnits (integer, swLengthUnit_e); 0 = mm
PREF_STL_SHOW_INFO = 70               # swSTLShowInfoOnSave
PREF_STL_NO_TRANSLATE = 71            # swSTLDontTranslateToPositive
STL_QUALITY_FINE = 2
SW_MM = 0


class CadError(RuntimeError):
    """A CAD failure whose message is safe to show the user."""


@dataclass
class SwInfo:
    revision: str = ""
    major: int = 0
    service_pack: str = ""
    is_2025: bool = False

    def as_dict(self) -> dict:
        return {"revision": self.revision, "major": self.major, "service_pack": self.service_pack, "is_2025": self.is_2025}


class CadSession:
    """Owns the connection. Not thread-safe by design: create it and use it on ONE thread (the job runner's STA thread)."""

    def __init__(self, sw_app=None):
        self._owns_session = sw_app is None
        self.app = sw_app
        self.last_open_warnings = 0
        self.opened: dict[str, str] = {}          # normalized path -> title, for docs THIS worker opened
        self.info = SwInfo()
        self._prefs: dict[tuple[str, int], object] = {}

    # ------------------------------------------------------------ connection
    def connect(self) -> SwInfo:
        if self.app is None:
            from pipeline.solidworks_builder import connect_to_solidworks
            self.app = connect_to_solidworks()
        rev = str(self.app.RevisionNumber)
        m = re.match(r"^(\d+)\.(\d+)\.(\d+)", rev)
        major = int(m.group(1)) if m else 0
        self.info = SwInfo(revision=rev, major=major, service_pack=f"SP{m.group(2)}.{m.group(3)}" if m else "", is_2025=(major == 33))
        return self.info

    def typed(self, obj, interface: str):
        from pipeline.solidworks_builder import typed
        return typed(obj, interface)

    def dyn(self, obj):
        from win32com.client.dynamic import Dispatch
        return Dispatch(obj._oleobj_)

    # ------------------------------------------------------------ documents
    def _norm(self, p) -> str:
        return str(Path(p).resolve()).lower()

    def open_part(self, path: Path):
        """Open a saved part silently. Refuses a file the user already has open (we will not touch their session state) and anything that is not a
        part. Returns the typed IModelDoc2."""
        path = Path(path).resolve()
        existing = None
        try:
            existing = self.app.GetOpenDocumentByName(str(path))
        except Exception:      # noqa: BLE001
            existing = None
        if existing is not None:
            raise CadError(f"{path.name} is already open in SOLIDWORKS. Close it there (or save and close) and retry; this tool will not edit a document you have open.")
        res = self.typed(self.app, "ISldWorks").OpenDoc6(str(path), SW_DOC_PART, OPEN_SILENT, "", 0, 0)
        doc = res[0] if isinstance(res, tuple) else res
        errs = res[1] if isinstance(res, tuple) and len(res) > 1 else 0
        warns = res[2] if isinstance(res, tuple) and len(res) > 2 else 0
        if doc is None:
            raise CadError(_open_error_text(path.name, errs))
        if int(doc.GetType()) != SW_DOC_PART:
            self._close_title(str(doc.GetTitle()))
            raise CadError(f"{path.name} is not a part document.")
        self.opened[self._norm(path)] = str(doc.GetTitle())
        self.last_open_warnings = int(warns or 0)
        return doc

    def close_part(self, path: Path) -> None:
        title = self.opened.pop(self._norm(path), None)
        if title:
            self._close_title(title)

    def _close_title(self, title: str) -> None:
        try:
            self.app.CloseDoc(title)
        except Exception as e:      # noqa: BLE001
            log.warning("CloseDoc(%s) failed: %s", title, e)

    def close_all_owned(self) -> None:
        for n, t in list(self.opened.items()):
            self._close_title(t)
            self.opened.pop(n, None)

    def configurations(self, doc) -> list[str]:
        try:
            return [str(c) for c in (doc.GetConfigurationNames() or ())]
        except Exception:      # noqa: BLE001
            return []

    def active_configuration(self, doc) -> str:
        try:
            return str(doc.ConfigurationManager.ActiveConfiguration.Name)
        except Exception:      # noqa: BLE001
            return ""

    def activate_configuration(self, doc, name: str) -> None:
        if not name:
            return
        if name not in self.configurations(doc):
            raise CadError(f"The part has no configuration named {name!r}.")
        if self.active_configuration(doc) != name:
            if not doc.ShowConfiguration2(name):
                raise CadError(f"Could not activate configuration {name!r}.")

    # ------------------------------------------------------------ preferences
    def _get_pref(self, kind: str, idx: int):
        s = self.typed(self.app, "ISldWorks")
        return s.GetUserPreferenceToggle(idx) if kind == "toggle" else s.GetUserPreferenceIntegerValue(idx)

    def _set_pref(self, kind: str, idx: int, val) -> None:
        s = self.typed(self.app, "ISldWorks")
        (s.SetUserPreferenceToggle if kind == "toggle" else s.SetUserPreferenceIntegerValue)(idx, val)

    def push_prefs(self, items: list[tuple[str, int, object]]) -> None:
        for kind, idx, val in items:
            self._prefs.setdefault((kind, idx), self._get_pref(kind, idx))
            self._set_pref(kind, idx, val)

    def pop_prefs(self) -> None:
        for (kind, idx), old in list(self._prefs.items()):
            try:
                self._set_pref(kind, idx, old)
            except Exception as e:      # noqa: BLE001
                log.warning("Could not restore preference %s/%s: %s", kind, idx, e)
        self._prefs.clear()

    # ------------------------------------------------------------ STL
    def export_stl(self, doc, out: Path) -> dict:
        """Binary STL in millimetres, fine quality, in a declared unit; preferences restored afterwards. Returns the validation record."""
        out = Path(out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        try:
            self.push_prefs([("toggle", PREF_STL_BINARY, True), ("int", PREF_STL_UNITS, SW_MM), ("int", PREF_STL_QUALITY, STL_QUALITY_FINE),
                             ("toggle", PREF_STL_SHOW_INFO, False), ("toggle", PREF_STL_NO_TRANSLATE, True)])
            ok = doc.SaveAs3(str(out), 0, 1)
            if ok is False:
                log.warning("SaveAs3 STL returned failure")
        finally:
            self.pop_prefs()
        return validate_stl(out)

    # ------------------------------------------------------------ geometry
    def body_box(self, doc) -> Optional[tuple[float, ...]]:
        bodies = self.typed(doc, "IPartDoc").GetBodies2(0, False) or ()
        if not bodies:
            return None
        mins = [math.inf] * 3
        maxs = [-math.inf] * 3
        for b in bodies:
            bb = list(b.GetBodyBox())
            for i in range(3):
                mins[i] = min(mins[i], bb[i])
                maxs[i] = max(maxs[i], bb[i + 3])
        return tuple(mins + maxs)


def _open_error_text(name: str, errs: int) -> str:
    table = {1: "a generic error", 2: "the file was not found", 4: "the file could not be opened (unsupported or corrupt)", 8: "the file was saved in a newer SOLIDWORKS version",
             16: "a SOLIDWORKS license is not available", 1024: "the file is damaged or from a future version", 32768: "the file is not a SOLIDWORKS file",
             65536: "a file with the same name is already open"}
    why = [t for bit, t in table.items() if errs and (int(errs) & bit)]
    return f"SOLIDWORKS could not open {name}" + (f": {'; '.join(why)}." if why else f" (error code {errs}).")


# ---------------------------------------------------------------- STL validation (no SOLIDWORKS)

def validate_stl(path: Path) -> dict:
    """Binary or ASCII STL facts: triangle count, finite vertices, bounding box in the file's units (mm)."""
    p = Path(path)
    rec: dict = {"path": p.name, "exists": p.is_file(), "ok": False, "triangles": 0, "bbox_mm": None, "errors": []}
    if not rec["exists"] or p.stat().st_size < 84:
        rec["errors"].append("STL missing or too small")
        return rec
    data = p.read_bytes()
    rec["bytes"] = len(data)
    if data[:5].lower() == b"solid" and b"facet" in data[:600]:
        rec["format"] = "ascii"
        verts = [tuple(map(float, m)) for m in re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data)]
        rec["triangles"] = len(verts) // 3
    else:
        rec["format"] = "binary"
        n = struct.unpack_from("<I", data, 80)[0]
        if len(data) != 84 + 50 * n:
            rec["errors"].append(f"binary STL size {len(data)} does not match {n} triangles")
            return rec
        rec["triangles"] = n
        verts = []
        off = 84
        for _ in range(n):
            v = struct.unpack_from("<12f", data, off)
            verts += [v[3:6], v[6:9], v[9:12]]
            off += 50
    if not verts:
        rec["errors"].append("STL has no triangles")
        return rec
    if any(not math.isfinite(c) for v in verts for c in v):
        rec["errors"].append("STL has non-finite vertices")
        return rec
    mn = [min(v[i] for v in verts) for i in range(3)]
    mx = [max(v[i] for v in verts) for i in range(3)]
    rec["bbox_mm"] = [round(c, 4) for c in mn + mx]
    rec["size_mm"] = [round(mx[i] - mn[i], 4) for i in range(3)]
    rec["ok"] = rec["triangles"] > 0 and all(s > 0 for s in rec["size_mm"])
    if not rec["ok"]:
        rec["errors"].append("STL is degenerate (a zero-size axis)")
    return rec


def compare_stl_to_native(stl: dict, native_box_m: tuple[float, ...], tol_rel: float = 0.01) -> dict:
    """STL size (mm) vs the native body box (metres), compared as sorted extents so a re-orientation is not a failure; scale errors are."""
    if not stl.get("size_mm") or native_box_m is None:
        return {"ok": False, "reason": "missing data"}
    nat = sorted((native_box_m[i + 3] - native_box_m[i]) * 1000.0 for i in range(3))
    got = sorted(stl["size_mm"])
    worst = max(abs(a - b) / max(b, 1e-9) for a, b in zip(got, nat))
    return {"ok": worst <= tol_rel, "worst_relative_error": round(worst, 6), "native_size_mm": [round(v, 4) for v in nat], "stl_size_mm": got, "tolerance": tol_rel}
