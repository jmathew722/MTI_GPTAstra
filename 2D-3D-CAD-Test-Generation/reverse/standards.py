"""Native drawing standards for 3D -> 2D (v7, spec 03). Every API here was probed on SOLIDWORKS 2025 SP5 (33.5.0) against the installed type library;
see docs/solidflow-upgrades/api_validation.md ("v7 drawing standards").

* Isometric view = Shaded With Edges: ``IView.SetDisplayMode3(UseParent=False, Mode=3 (swDisplayMode_e.swSHADED), Faceted=False, Edges=True)``;
  verified by ``IView.GetDisplayMode2() == 3`` and ``GetDisplayEdgesInShadedMode() == True`` (and, after export, by filled shading in the PDF).
  NOTE: ``Mode=7 (swSHADED_EDGES)`` is refused by SetDisplayMode3 (returns False); the edges flag is what produces Shaded With Edges.
* Leadered dimensions: ``IDisplayDimension.SetBrokenLeader2(UseDoc=False, Broken=swDisplayDimensionLeaderText_e.swBrokenLeaderHorizontalText (2))`` is the
  API behind the dimension PropertyManager's Leaders tab -> Custom text position -> "Broken leader, horizontal text". Read back with
  ``GetBrokenLeader2() == 2`` and ``GetUseDocBrokenLeader() == False``. Linear dimensions have no leader text option (they read -1 before) and
  are reported as not applicable, never forced. Notes have no broken-leader style in the API (``swLeaderStyle_e``: straight / bent / underlined): a leadered
  note would use ``IAnnotation.SetLeader3`` with a bent leader and horizontal text; Solid Flow creates no leadered notes, and says so in the report.
* Black: layer SF_BLACK (colour 0) is current while annotations are created, and every annotation's ``Color`` is read back and, if not 0, set to 0.
* Arrange: ``IModelDocExtension.AlignDimensions(swAlignDimensionType_AutoArrange (0), spacing)`` on the dimensions of one view (selected with
  ``SelectByID2(IDisplayDimension.GetNameForSelection(), "DIMENSION", ...)``; ``IAnnotation.Select3`` does NOT select them), with a before / after inventory.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

SW_DISP_SHADED = 3                 # swDisplayMode_e.swSHADED (with Edges=True -> Shaded With Edges)
SW_BROKEN_LEADER_HORIZONTAL_TEXT = 2   # swDisplayDimensionLeaderText_e.swBrokenLeaderHorizontalText
SW_ALIGN_AUTO_ARRANGE = 0          # swAlignDimensionType_e.swAlignDimensionType_AutoArrange
SW_ANN_DISPLAY_DIMENSION, SW_ANN_NOTE = 4, 6
# swDimensionType_e values that carry a leader whose text style is configurable
LEADERED_DIM_TYPES = {3: "angular", 4: "arc length", 5: "radial", 6: "diameter", 10: "chamfer", 14: "radial linear", 15: "diametric linear"}
DIM_TYPE_NAME = {1: "ordinate", 2: "linear", 3: "angular", 4: "arc length", 5: "radial", 6: "diameter", 7: "hor ordinate", 8: "vert ordinate", 10: "chamfer",
                 11: "hor linear", 12: "vert linear", 13: "scalar", 14: "radial linear", 15: "diametric linear", 16: "angular ordinate"}


class Standards:
    def __init__(self, dd):
        self.dd = dd
        self.s = dd.s
        self.T = dd.s.typed
        self.report: dict = {"iso": {"views": []}, "leaders": {"applied": [], "not_applicable": [], "failed": []}, "black": {"checked": 0, "fixed": 0, "failed": []},
                             "arrange": {"views": []}, "notes": {"leadered_notes": 0, "note": "No leadered notes are generated: broken leaders do not exist for notes in the 2025 API."}}

    # ------------------------------------------------------------ views
    def iter_views(self):
        """(name, typed IView) of every model view (the sheet's own pseudo-view is skipped)."""
        v = self.dd.drw.GetFirstView()
        v = self.T(v, "IView").GetNextView() if v is not None else None
        while v is not None:
            tv = self.T(v, "IView")
            yield str(tv.GetName2()), tv
            nv = tv.GetNextView()
            v = nv if nv is not None else None

    def role_of(self, view_name: str) -> str:
        for role, v in self.dd.views.items():
            try:
                if str(self.T(v, "IView").GetName2()) == view_name:
                    return role
            except Exception:      # noqa: BLE001
                continue
        return view_name

    # ------------------------------------------------------------ isometric: Shaded With Edges
    def apply_iso_style(self) -> dict:
        res = {"views": []}
        for role, v in self.dd.views.items():
            sw_view = ""
            try:
                sw_view = str(self.T(v, "IView").GetName2())
            except Exception:      # noqa: BLE001
                pass
            if role != "iso" and not role.startswith("iso"):
                continue
            tv = self.T(v, "IView")
            rec = {"role": role, "view": sw_view, "applied": False}
            try:
                rec["set_returned"] = bool(tv.SetDisplayMode3(False, SW_DISP_SHADED, False, True))
                rec["display_mode_readback"] = int(tv.GetDisplayMode2())
                rec["edges_in_shaded_readback"] = bool(tv.GetDisplayEdgesInShadedMode())
                rec["applied"] = rec["display_mode_readback"] == SW_DISP_SHADED and rec["edges_in_shaded_readback"]
                rec["label"] = "Shaded With Edges" if rec["applied"] else "NOT Shaded With Edges"
            except Exception as e:      # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {e}"
            res["views"].append(rec)
        self.report["iso"] = res
        return res

    # ------------------------------------------------------------ inventory
    def inventory(self) -> list[dict]:
        """Every dimension and note on the sheet with value, position, attachment and style facts (native read-back, no PDF)."""
        out: list[dict] = []
        counters: dict[str, int] = {}
        for vname, tv in self.iter_views():
            role = self.role_of(vname)
            try:
                dds = tv.GetDisplayDimensions() or ()
            except Exception:      # noqa: BLE001
                dds = ()
            for d in dds:
                try:
                    td = self.T(d, "IDisplayDimension")
                    dim = self.T(td.GetDimension2(0), "IDimension")
                    an = self.T(td.GetAnnotation(), "IAnnotation")
                    pos = [float(x) for x in an.GetPosition()[:2]]
                    typ = int(td.GetType())
                    nm = str(td.GetNameForSelection())
                    try:
                        dangling = bool(an.IsDangling())
                    except Exception:      # noqa: BLE001
                        dangling = None
                    try:
                        ents = int(an.GetAttachedEntityCount3())
                    except Exception:      # noqa: BLE001
                        ents = None
                    try:
                        full = str(dim.FullName)
                    except Exception:      # noqa: BLE001
                        full = nm
                    rec = {"id": f"{role}/{nm.split('@')[0]}", "kind": "dimension", "view": role, "view_name": vname, "select_name": nm, "dim_type": typ,
                           "dim_type_name": DIM_TYPE_NAME.get(typ, str(typ)), "value_m": round(float(dim.SystemValue), 9), "position_m": [round(pos[0], 6), round(pos[1], 6)],
                           "dangling": dangling, "attached_entities": ents, "color": int(an.Color), "layer": str(an.Layer), "broken_leader": int(td.GetBrokenLeader2()),
                           "use_doc_broken_leader": bool(td.GetUseDocBrokenLeader()), "full_name": full}
                    counters[role] = counters.get(role, 0) + 1
                    out.append(rec)
                except Exception as e:      # noqa: BLE001
                    out.append({"id": f"{role}/?", "kind": "dimension", "view": role, "error": f"{type(e).__name__}: {e}"})
        return out

    def notes_inventory(self) -> list[dict]:
        out = []
        sheet_view = self.dd.drw.GetFirstView()
        views = [("sheet", self.T(sheet_view, "IView"))] if sheet_view is not None else []
        views += [(self.role_of(n), tv) for n, tv in self.iter_views()]
        for role, tv in views:
            try:
                notes = tv.GetNotes() or ()
            except Exception:      # noqa: BLE001
                notes = ()
            for i, n in enumerate(notes):
                try:
                    tn = self.T(n, "INote")
                    an = self.T(tn.GetAnnotation(), "IAnnotation")
                    pos = [float(x) for x in an.GetPosition()[:2]]
                    out.append({"id": f"{role}/note{i + 1}", "kind": "note", "view": role, "view_name": vname_of(tv), "note_index": i, "text": str(tn.GetText()), "position_m": [round(pos[0], 6), round(pos[1], 6)],
                                "color": int(an.Color), "layer": str(an.Layer), "leader_count": int(tn.GetLeaderCount())})
                except Exception as e:      # noqa: BLE001
                    out.append({"id": f"{role}/note{i + 1}", "kind": "note", "view": role, "error": f"{type(e).__name__}: {e}"})
        return out

    # ------------------------------------------------------------ leaders / black
    def apply_leader_style(self) -> dict:
        """Broken leader, horizontal text on every leadered dimension; verified by read-back. Linear dims: not applicable (reported)."""
        rep = {"applied": [], "not_applicable": [], "failed": []}
        for vname, tv in self.iter_views():
            role = self.role_of(vname)
            for d in (tv.GetDisplayDimensions() or ()):
                try:
                    td = self.T(d, "IDisplayDimension")
                    typ = int(td.GetType())
                    nm = str(td.GetNameForSelection()).split("@")[0]
                    ident = f"{role}/{nm}"
                    if typ not in LEADERED_DIM_TYPES:
                        rep["not_applicable"].append({"id": ident, "type": DIM_TYPE_NAME.get(typ, str(typ)), "why": "no configurable leader text style (linear / ordinate dimension)"})
                        continue
                    td.SetBrokenLeader2(False, SW_BROKEN_LEADER_HORIZONTAL_TEXT)
                    got, use_doc = int(td.GetBrokenLeader2()), bool(td.GetUseDocBrokenLeader())
                    rec = {"id": ident, "type": LEADERED_DIM_TYPES[typ], "readback": got, "use_document_display": use_doc}
                    (rep["applied"] if got == SW_BROKEN_LEADER_HORIZONTAL_TEXT and not use_doc else rep["failed"]).append(rec)
                except Exception as e:      # noqa: BLE001
                    rep["failed"].append({"id": f"{role}/?", "error": f"{type(e).__name__}: {e}"})
        self.report["leaders"] = rep
        return rep

    def ensure_black(self) -> dict:
        rep = {"checked": 0, "fixed": 0, "failed": []}
        for item in self.inventory() + self.notes_inventory():
            if "error" in item:
                continue
            rep["checked"] += 1
            if item.get("color", 0) != 0:
                rep["failed"].append(item["id"])
        # fix by walking annotations
        for vname, tv in list(self.iter_views()) + [("sheet", self.T(self.dd.drw.GetFirstView(), "IView"))]:
            try:
                anns = tv.GetAnnotations() or ()
            except Exception:      # noqa: BLE001
                anns = ()
            for a in anns:
                try:
                    an = self.T(a, "IAnnotation")
                    if int(an.Color) != 0:
                        an.Color = 0
                        if int(an.Color) == 0:
                            rep["fixed"] += 1
                except Exception:      # noqa: BLE001
                    continue
        rep["failed"] = [x for x in rep["failed"]]
        self.report["black"] = rep
        return rep

    # ------------------------------------------------------------ arrange
    def arrange(self, spacing_m: float = 0.0) -> dict:
        """Native Auto Arrange per view, with the dimension inventory before and after. The caller decides (by measured collisions) whether to keep it."""
        before = [i for i in self.inventory() if "error" not in i]
        res = {"requested": True, "views": [], "before": before, "after": None, "moved": 0}
        byview: dict[str, list[dict]] = {}
        for i in before:
            byview.setdefault(i["view"], []).append(i)
        for role, items in byview.items():
            rec = {"view": role, "dimensions": len(items), "selected": 0, "returned": None, "error": None}
            if len(items) < 2:
                rec["skipped"] = "fewer than two dimensions: nothing to arrange"
                res["views"].append(rec)
                continue
            try:
                self.dd.mdl.ClearSelection2(True)
                for k, it in enumerate(items):
                    if self.dd.ext.SelectByID2(it["select_name"], "DIMENSION", 0, 0, 0, k > 0, 0, None, 0):
                        rec["selected"] += 1
                if rec["selected"] >= 2:
                    rec["returned"] = bool(self.dd.ext.AlignDimensions(SW_ALIGN_AUTO_ARRANGE, spacing_m))
                else:
                    rec["error"] = f"only {rec['selected']} of {len(items)} dimensions could be selected"
            except Exception as e:      # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {e}"
            finally:
                try:
                    self.dd.mdl.ClearSelection2(True)
                except Exception:      # noqa: BLE001
                    pass
            res["views"].append(rec)
        after = [i for i in self.inventory() if "error" not in i]
        res["after"] = after
        bmap = {i["id"]: i for i in before}
        res["moved"] = sum(1 for a in after if a["id"] in bmap and a["position_m"] != bmap[a["id"]]["position_m"])
        res["integrity"] = arrange_integrity(before, after)
        self.report["arrange"] = {k: v for k, v in res.items() if k not in ("before", "after")} | {"before_count": len(before), "after_count": len(after)}
        return res


def all_views(dd):
    """The sheet's own pseudo-view first (it owns the template's and our sheet-level notes), then every model view, as typed IView."""
    T = dd.s.typed
    out = []
    v = dd.drw.GetFirstView()
    while v is not None:
        tv = T(v, "IView")
        out.append(tv)
        nv = tv.GetNextView()
        v = nv if nv is not None else None
    return out


def vname_of(tv) -> str:
    try:
        return str(tv.GetName2())
    except Exception:      # noqa: BLE001
        return ""


def arrange_integrity(before: list[dict], after: list[dict]) -> dict:
    """Same ids, same values, still attached, same count. Anything else means the arrangement damaged the drawing (the caller then restores positions)."""
    b = {i["id"]: i for i in before}
    a = {i["id"]: i for i in after}
    lost = sorted(set(b) - set(a))
    added = sorted(set(a) - set(b))
    changed = [i for i in b if i in a and abs(b[i]["value_m"] - a[i]["value_m"]) > 1e-9]
    dangling = [i for i in a if a[i].get("dangling")]
    return {"ok": not (lost or added or changed or dangling) and len(b) == len(a), "lost": lost, "added": added, "value_changed": changed, "dangling": dangling,
            "count_before": len(b), "count_after": len(a)}


def restore_positions(dd, before: list[dict]) -> int:
    """Put every dimension back where the inventory says it was (used when an arrangement made the measured layout worse)."""
    n = 0
    T = dd.s.typed
    byname = {(i["view_name"], i["select_name"]): i for i in before if i.get("kind") == "dimension"}
    bynote = {(i["view_name"], i["note_index"]): i for i in before if i.get("kind") == "note"}
    v = dd.drw.GetFirstView()
    v = T(v, "IView").GetNextView() if v is not None else None
    while v is not None:
        tv = T(v, "IView")
        vn = str(tv.GetName2())
        for d in (tv.GetDisplayDimensions() or ()):
            td = T(d, "IDisplayDimension")
            rec = byname.get((vn, str(td.GetNameForSelection())))
            if rec:
                an = T(td.GetAnnotation(), "IAnnotation")
                if an.SetPosition2(rec["position_m"][0], rec["position_m"][1], 0):
                    n += 1
        nv = tv.GetNextView()
        v = nv if nv is not None else None
    if bynote:
        for tv in all_views(dd):
            for i, nn in enumerate(tv.GetNotes() or ()):
                rec = bynote.get((vname_of(tv), i))
                if rec:
                    an = T(T(nn, "INote").GetAnnotation(), "IAnnotation")
                    if an.SetPosition2(rec["position_m"][0], rec["position_m"][1], 0):
                        n += 1
    return n
