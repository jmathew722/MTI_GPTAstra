"""Managed drawing-template catalog: the stock template, the generated default (ANSI B / C, A3), and user-uploaded ``.drwdot`` files.

A template is accepted only after SOLIDWORKS itself creates a drawing from it and that drawing holds no model references.  A ``.slddrt`` (sheet
format) is accepted only paired with a validated ``.drwdot``.  The original file is never modified: it is copied into the catalog and hashed.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Optional

from reverse import safety, worker

MAX_TEMPLATE_BYTES = 25 * 1024 * 1024
ALLOWED = {".drwdot", ".slddrt"}
DEFAULT_ID = "solidflow-ansi-b"


class TemplateError(ValueError):
    pass


class TemplateCatalog:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"

    # ---- persistence
    def _load(self) -> list[dict]:
        if self.index_path.is_file():
            try:
                return json.loads(self.index_path.read_text(encoding="utf-8")).get("templates", [])
            except (OSError, json.JSONDecodeError):
                return []
        return []

    def _save(self, items: list[dict]) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"schema_version": 1, "templates": items}, indent=2), encoding="utf-8")
        os.replace(tmp, self.index_path)

    # ---- queries
    def list(self) -> list[dict]:
        out = []
        for t in self._load():
            ok = Path(t["path"]).is_file()
            out.append(dict(t, available=ok))
        stock = stock_entry()
        if stock and not any(t["id"] == stock["id"] for t in out):
            out.append(dict(stock, available=True))
        return out

    def get(self, tid: str) -> dict:
        for t in self.list():
            if t["id"] == tid:
                if not t.get("available"):
                    raise TemplateError(f"Template {tid} is no longer on disk.")
                return t
        raise TemplateError(f"Unknown template {tid!r}.")

    def default(self) -> dict:
        for t in self.list():
            if t["id"] == DEFAULT_ID and t.get("available"):
                return t
        stock = stock_entry()
        if stock:
            return dict(stock, available=True)
        raise TemplateError("No drawing template is available. Generate the default template first.")

    # ---- mutation
    def register(self, entry: dict) -> dict:
        items = [t for t in self._load() if t["id"] != entry["id"]]
        items.append(entry)
        self._save(items)
        return entry

    def add_uploaded(self, session: worker.CadSession, src: Path, name: Optional[str] = None) -> dict:
        """Copy a user's ``.drwdot`` into the catalog and validate it by creating a drawing from it in SOLIDWORKS."""
        src = Path(src)
        if src.suffix.lower() not in ALLOWED:
            raise TemplateError("Only .drwdot drawing templates are accepted (a .slddrt sheet format needs a validated .drwdot).")
        if src.suffix.lower() == ".slddrt":
            raise TemplateError("A .slddrt sheet format cannot be used alone; upload it with its .drwdot.")
        if not src.is_file() or src.stat().st_size == 0 or src.stat().st_size > MAX_TEMPLATE_BYTES:
            raise TemplateError("The template file is missing, empty or larger than 25 MB.")
        tid = "user-" + safety.safe_id(src.stem).lower()
        dest = self.root / "user" / f"{tid}{src.suffix.lower()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        check = validate_template(session, dest)
        if not check["ok"]:
            dest.unlink(missing_ok=True)
            raise TemplateError("SOLIDWORKS rejected the template: " + "; ".join(check["errors"]))
        entry = {"id": tid, "name": name or src.name, "path": str(dest), "sha256": safety.sha256_file(dest), "own_sheet_format": check.get("sheet_format", False),
                 "source": "uploaded", "validation": check, "paper": check.get("paper")}
        return self.register(entry)


def stock_entry() -> Optional[dict]:
    p = Path(os.environ.get("SOLIDFLOW_STOCK_TEMPLATE", "") or r"C:\ProgramData\SolidWorks\SOLIDWORKS 2025\templates\Drawing.drwdot")
    if not p.is_file():
        return None
    return {"id": "stock-default", "name": "SOLIDWORKS stock drawing template", "path": str(p), "sha256": safety.sha256_file(p), "own_sheet_format": False,
            "source": "stock", "paper": "as installed"}


def validate_template(session: worker.CadSession, path: Path) -> dict:
    """Create a drawing from the template, check it loads, has a sheet and references no model; close it. Never leaves the document open."""
    res: dict = {"ok": False, "errors": [], "sheet_format": False, "views": None, "paper": None}
    mdl = None
    try:
        T = session.typed
        model = T(session.app, "ISldWorks").NewDocument(str(path), 2, 0.4318, 0.2794)
        if model is None:
            res["errors"].append("NewDocument returned nothing")
            return res
        mdl = T(model, "IModelDoc2")
        drw = T(model, "IDrawingDoc")
        sheet = T(drw.GetCurrentSheet(), "ISheet")
        props = sheet.GetProperties2()
        res["paper"] = {"paper_size": props[0], "width_m": props[5], "height_m": props[6]}
        try:
            res["sheet_format"] = bool(sheet.GetSheetFormatName())
        except Exception:      # noqa: BLE001
            pass
        first = drw.GetFirstView()
        v = T(first, "IView").GetNextView() if first is not None else None
        n = 0
        while v is not None:
            n += 1
            v = T(v, "IView").GetNextView()
        res["views"] = n
        if n:
            res["errors"].append(f"the template already contains {n} model view(s); a template must not reference any model")
        res["ok"] = not res["errors"]
    except Exception as e:      # noqa: BLE001
        res["errors"].append(f"{type(e).__name__}: {e}")
    finally:
        if mdl is not None:
            try:
                session.app.CloseDoc(str(mdl.GetTitle()))
            except Exception:      # noqa: BLE001
                pass
    return res
