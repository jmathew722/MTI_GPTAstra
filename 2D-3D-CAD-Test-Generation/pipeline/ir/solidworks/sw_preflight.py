"""SOLIDWORKS 2025 environment gate (Stage 4, Slice A).

Proves, BEFORE any document is created, that the running SOLIDWORKS is 2025 (revision 33.x) and that the Hole Wizard /
Toolbox data it is configured to use is the compatible family (database 28.x, exact version when the install states one,
Toolbox index 33.x). A mismatch is a configuration error, never a hole error: it is NOT retryable, and no step that could
open the modal "database is not the expected version" dialog (any ``IHoleStandardsData`` / ``InitializeHole`` call) runs.

Everything is read-only. This module never clicks a dialog, edits or upgrades a database, or changes a SOLIDWORKS setting.
The decision logic is a pure function of a ``Probe``; ``LiveProbe`` is the Windows/COM implementation.

Failure codes: SW_VERSION_UNSUPPORTED, HW_DATABASE_VERSION_MISMATCH, HW_DATABASE_MISSING, HW_CATALOG_LOOKUP_FAILED,
SW_MODAL_DIALOG_BLOCKED, SW_JOB_TIMEOUT (plus SW_JOB_ERROR for an exception inside a bounded job).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

REQUIRED_APP_MAJOR = 33          # SOLIDWORKS 2025
REQUIRED_DB_MAJOR = 28           # Hole Wizard / Toolbox database family of SOLIDWORKS 2025
REQUIRED_INDEX_MAJOR = 33        # ToolboxFiles.index (sldtoolboxdata assembly) family of SOLIDWORKS 2025
DISCOVERY_VERSION = 1
STAGE = "environment_preflight"
USER_ACTION = ("Point SOLIDWORKS 2025 to the company-approved 2025 Hole Wizard/Toolbox data folder "
               "(Tools > Options > System Options > Hole Wizard/Toolbox), restart SOLIDWORKS, then rerun preflight.")


class PreflightError(RuntimeError):
    def __init__(self, result: "PreflightResult"):
        super().__init__(f"{result.code}: {result.message}")
        self.result = result
        self.code = result.code


@dataclass
class PreflightResult:
    status: str = "ready"                   # ready | failed
    code: Optional[str] = None
    message: str = ""
    retryable: bool = False
    user_action: str = ""
    stage: str = STAGE
    revision: str = ""
    service_pack: str = ""
    db_version: Optional[str] = None
    db_expected_version: Optional[str] = None
    toolbox_file_version: Optional[str] = None
    toolbox_index_version: Optional[str] = None
    fingerprint: str = ""
    standards_found: int = 0
    details: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict:
        """Machine-readable and path-free (no filesystem paths, no catalog rows)."""
        return {"status": self.status, "code": self.code, "message": self.message, "retryable": self.retryable,
                "user_action": self.user_action, "stage": self.stage, "application_revision": self.revision,
                "application_service_pack": self.service_pack, "database_version": self.db_version,
                "database_expected_version": self.db_expected_version, "toolbox_file_version": self.toolbox_file_version,
                "toolbox_index_version": self.toolbox_index_version, "fingerprint": self.fingerprint,
                "standards_found": self.standards_found, "details": self.details}


def _major(v: Optional[str]) -> Optional[int]:
    m = re.match(r"\s*(\d+)", v or "")
    return int(m.group(1)) if m else None


def fingerprint(revision: str, db_version: str, index_version: str, toolbox_file_version: str, profile: str = "default") -> str:
    """Cache key for discovered catalog data: revision/SP, database version, index version, company profile, code version."""
    blob = json.dumps([revision, toolbox_file_version, db_version, index_version, profile, DISCOVERY_VERSION], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _fail(code: str, message: str, *, retryable=False, action="", **kw) -> PreflightResult:
    return PreflightResult(status="failed", code=code, message=message, retryable=retryable, user_action=action or USER_ACTION, **kw)


def run_preflight(probe, profile: str = "default", require_catalog: bool = True) -> PreflightResult:
    """Decide readiness from a probe. Order matters: nothing that could block on SOLIDWORKS UI runs after a cheaper
    check has already failed, and the catalog (COM) is queried last. ``require_catalog=False`` skips only that last step (used
    by the compiler's per-hole gate, where an unreadable catalog must not disable a Hole Wizard recipe that still works)."""
    rev = str(probe.revision() or "")
    major = _major(rev)
    base = dict(revision=rev, service_pack=rev)
    if major != REQUIRED_APP_MAJOR:
        return _fail("SW_VERSION_UNSUPPORTED", f"SOLIDWORKS 2025 (revision {REQUIRED_APP_MAJOR}.x) is required; the running application reports {rev or 'unknown'}.",
                     action="Run the pipeline against SOLIDWORKS 2025.", **base)
    root = probe.hole_wizard_root()
    if not root or not probe.db_exists(root):
        return _fail("HW_DATABASE_MISSING", "The configured Hole Wizard/Toolbox database (swbrowser.sldedb) was not found.", **base)
    dbv = probe.db_version(root)
    if not dbv:
        return _fail("HW_DATABASE_MISSING", "The configured Hole Wizard/Toolbox database exists but its version could not be read.", **base)
    expected = probe.expected_db_version()
    tfv, idx = probe.toolbox_file_version(root), probe.index_version(root)
    base.update(db_version=dbv, db_expected_version=expected, toolbox_file_version=tfv, toolbox_index_version=idx)
    if expected:
        db_ok = str(dbv).strip() == str(expected).strip()
        want = expected
    else:
        db_ok = _major(dbv) == REQUIRED_DB_MAJOR
        want = f"{REQUIRED_DB_MAJOR}.x"
    if not db_ok:
        return _fail("HW_DATABASE_VERSION_MISMATCH", f"SOLIDWORKS 2025 expects Hole Wizard database {want}, but the configured database is {dbv}. "
                     f"Hole Wizard database {dbv} is incompatible with expected {want}.", **base)
    if idx and _major(idx) != REQUIRED_INDEX_MAJOR:
        return _fail("HW_DATABASE_VERSION_MISMATCH", f"The Toolbox index version {idx} is not the SOLIDWORKS 2025 family ({REQUIRED_INDEX_MAJOR}.x).", **base)
    modal = probe.modal_windows()
    if modal:
        return _fail("SW_MODAL_DIALOG_BLOCKED", "A modal SOLIDWORKS dialog is open; automation would block behind it.",
                     action="Close the dialog in SOLIDWORKS (the pipeline never clicks it), then rerun preflight.",
                     details={"windows": list(modal)}, **base)
    if not require_catalog:
        return PreflightResult(status="ready", fingerprint=fingerprint(rev, str(dbv), str(idx or ""), str(tfv or ""), profile),
                               details={"catalog": "not_required"}, **base)
    try:
        standards = list(probe.catalog_standards() or ())
    except Exception as e:      # noqa: BLE001 - any COM failure is a lookup failure with the error attached
        return _fail("HW_CATALOG_LOOKUP_FAILED", "IHoleStandardsData could not enumerate the installed standards.", retryable=True,
                     details={"error": f"{type(e).__name__}: {e}"[:300]}, **base)
    if not standards:
        return _fail("HW_CATALOG_LOOKUP_FAILED", "IHoleStandardsData returned no installed Hole Wizard standards.", retryable=True, **base)
    return PreflightResult(status="ready", standards_found=len(standards),
                           fingerprint=fingerprint(rev, str(dbv), str(idx or ""), str(tfv or ""), profile), **base)


def require_ready(result: PreflightResult) -> PreflightResult:
    if not result.ok:
        raise PreflightError(result)
    return result


# ---- bounded execution --------------------------------------------------------------------------------------------
@dataclass
class BoundedResult:
    value: Any = None
    code: Optional[str] = None
    message: str = ""
    retryable: bool = False
    elapsed: float = 0.0


def run_bounded(fn: Callable[[], Any], timeout: float, heartbeat: Optional[Callable[[float], None]] = None,
                beat_every: float = 1.0) -> BoundedResult:
    """Run ``fn`` on a worker thread under a wall-clock timeout with a heartbeat. A timeout is ``SW_JOB_TIMEOUT``, not retryable
    (the caller recycles the worker). The thread cannot be killed; a COM caller should use a child process (see
    ``tools/run_hole_wizard_matrix.py``) when a hang must be fully contained."""
    box: dict = {}

    def target():
        try:
            box["v"] = fn()
        except BaseException as e:      # noqa: BLE001
            box["e"] = e

    t0 = time.monotonic()
    th = threading.Thread(target=target, daemon=True)
    th.start()
    while th.is_alive():
        left = timeout - (time.monotonic() - t0)
        if left <= 0:
            return BoundedResult(code="SW_JOB_TIMEOUT", message=f"no return after {timeout:g}s", elapsed=time.monotonic() - t0)
        th.join(min(beat_every, left))
        if th.is_alive() and heartbeat:
            heartbeat(time.monotonic() - t0)
    if "e" in box:
        e = box["e"]
        return BoundedResult(code="SW_JOB_ERROR", message=f"{type(e).__name__}: {e}"[:300], elapsed=time.monotonic() - t0)
    return BoundedResult(value=box.get("v"), elapsed=time.monotonic() - t0)


# ---- modal detection ------------------------------------------------------------------------------------------------
def detect_modal(windows: list, pid: int) -> list:
    """Dialogs of the SOLIDWORKS process: a visible ``#32770`` window, or a visible window owned by a DISABLED window of that
    process. A disabled main window alone is only evidence, not asserted as a dialog."""
    by_hwnd = {w["hwnd"]: w for w in windows}
    out = []
    for w in windows:
        if w.get("pid") != pid or not w.get("visible"):
            continue
        owner = by_hwnd.get(w.get("owner"))
        if w.get("class") == "#32770" or (owner is not None and owner.get("pid") == pid and not owner.get("enabled", True)):
            out.append({"hwnd": w["hwnd"], "title": w.get("title", ""), "class": w.get("class", "")})
    return out


def enum_windows() -> list:
    """Top-level windows via ctypes EnumWindows (read-only; never sends input)."""
    import ctypes
    import ctypes.wintypes as wt
    u = ctypes.windll.user32
    out: list = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _):
        p = wt.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        n = u.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, b, n + 1)
        c = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(h, c, 256)
        out.append({"hwnd": int(h), "pid": p.value, "title": b.value, "class": c.value, "visible": bool(u.IsWindowVisible(h)),
                    "enabled": bool(u.IsWindowEnabled(h)), "owner": int(u.GetWindow(h, 4) or 0)})
        return True
    u.EnumWindows(cb, 0)
    return out


# ---- the Windows / COM probe -------------------------------------------------------------------------------------
HOLE_WIZARD_FOLDER_PREF = 52     # swUserPreferenceStringValue_e.swHoleWizardToolBoxFolder (verified in the installed swconst.tlb)


def _read_db_version(db_path: str) -> Optional[str]:
    """Read ``VERSION`` from swbrowser.sldedb strictly read-only (SQLite ``mode=ro&immutable=1``; the file is never written)."""
    uri = "file:" + db_path.replace("\\", "/").replace(" ", "%20") + "?mode=ro&immutable=1"
    try:
        con = sqlite3.connect(uri, uri=True)
        try:
            row = con.execute("select * from VERSION limit 1").fetchone()
        finally:
            con.close()
        return str(row[0]) if row else None
    except sqlite3.Error:
        return None


def _db_path(root: str) -> str:
    for rel in (("lang", "english", "swbrowser.sldedb"), ("swbrowser.sldedb",)):
        p = os.path.join(root, *rel)
        if os.path.isfile(p):
            return p
    return os.path.join(root, "lang", "english", "swbrowser.sldedb")


def _data_root(configured: str) -> str:
    """The preference points at ``<root>\\lang\\english``; the data root (ToolboxVersion.dat, browser\\) is two levels up."""
    c = configured.rstrip("\\/")
    low = c.lower().replace("/", "\\")
    return c[:-len("\\lang\\english")] if low.endswith("\\lang\\english") else c


class LiveProbe:
    """Read-only probe of the RUNNING SolidWorks session."""

    def __init__(self, app, expected_db_version: Optional[str] = None):
        self.app = app
        self._expected = expected_db_version or os.environ.get("SW_HW_EXPECTED_DB_VERSION") or None
        self._root = None

    def revision(self):
        return str(self.app.RevisionNumber)

    def hole_wizard_root(self):
        if self._root is None:
            try:
                self._root = _data_root(str(self.app.GetUserPreferenceStringValue(HOLE_WIZARD_FOLDER_PREF) or ""))
            except Exception:       # noqa: BLE001
                self._root = ""
        return self._root

    def db_exists(self, root):
        return os.path.isfile(_db_path(root))

    def db_version(self, root):
        return _read_db_version(_db_path(root))

    def expected_db_version(self):
        return self._expected

    def toolbox_file_version(self, root):
        try:
            txt = open(os.path.join(root, "ToolboxVersion.dat"), encoding="utf-8", errors="replace").read()
        except OSError:
            return None
        m = re.search(r"FileVersion\s*=\s*([\d.]+)", txt)
        return m.group(1) if m else None

    def index_version(self, root):
        """Release family of ToolboxFiles.index: the ``sldtoolboxdata, Version=`` assembly stamp in its header."""
        try:
            with open(os.path.join(root, "browser", "ToolboxFiles.index"), "rb") as f:
                head = f.read(512).decode("latin-1")
        except OSError:
            return None
        m = re.search(r"sldtoolboxdata, Version=([\d.]+)", head)
        return m.group(1) if m else None

    def modal_windows(self):
        return detect_modal(enum_windows(), int(self.app.GetProcessID))

    def catalog_standards(self):
        from pipeline.ir.solidworks import hole_catalog as cat
        snap = cat.discover(self.app)
        if not snap.available:
            raise RuntimeError(f"{snap.code}: {snap.detail}")
        return [s for fam in snap.families.values() for s in fam.get("standards", [])]


def sibling_roots(configured_root: str) -> list:
    """Other ``SOLIDWORKS Data*`` folders next to the configured one with their ToolboxVersion.dat release line and database
    version (read-only): used to RECOMMEND which root is the 2025 one. Nothing is configured automatically."""
    parent = os.path.dirname(configured_root.rstrip("\\/")) or "C:\\"
    out = []
    try:
        names = sorted(os.listdir(parent))
    except OSError:
        return out
    for n in names:
        if not n.lower().startswith("solidworks data"):
            continue
        root = os.path.join(parent, n)
        pr = LiveProbe.__new__(LiveProbe)
        txt = ""
        try:
            txt = open(os.path.join(root, "ToolboxVersion.dat"), encoding="utf-8", errors="replace").read()
        except OSError:
            pass
        rel = re.search(r"//\s*(SOLIDWORKS\s+\d{4}\s+SP[\d.]+)", txt)
        out.append({"name": n, "release_line": rel.group(1) if rel else None, "toolbox_file_version": LiveProbe.toolbox_file_version(pr, root),
                    "index_version": LiveProbe.index_version(pr, root), "database_version": _read_db_version(_db_path(root)),
                    "is_configured": os.path.normcase(root) == os.path.normcase(configured_root)})
    return out


def run_live_preflight(app) -> tuple:
    """(PreflightResult, extras) for the RUNNING session. Read-only. The exact expected database version is taken from the
    data root that SOLIDWORKS 2025 itself shipped (a ``SOLIDWORKS Data*`` folder beside the configured one whose
    ToolboxVersion.dat says 2025) unless ``SW_HW_EXPECTED_DB_VERSION`` is set. Nothing is configured automatically."""
    probe = LiveProbe(app)
    configured = probe.hole_wizard_root()
    sib = sibling_roots(configured) if configured else []
    source = "env SW_HW_EXPECTED_DB_VERSION" if probe.expected_db_version() else "REQUIRED_DB_MAJOR family (no exact expectation found)"
    if not probe.expected_db_version():
        cand = [x for x in sib if (x["release_line"] or "").startswith("SOLIDWORKS 2025") and x["database_version"]]
        if len(cand) == 1:
            probe._expected = cand[0]["database_version"]
            source = "database of the SOLIDWORKS 2025 data root found beside the configured one"
    res = run_preflight(probe)
    extras = {"expected_version_source": source, "configured_root_is": next((x["name"] for x in sib if x["is_configured"]), None),
              "data_roots_found": sib,
              "remediation_owner": ("environment owner: select the SOLIDWORKS 2025 data root in Tools > Options > System Options > "
                                    "Hole Wizard/Toolbox. The pipeline does not change it.")}
    return res, extras
