"""Read enums and interface members from the installed SolidWorks type libraries (no SolidWorks session needed).

The installed type library is authoritative for what THIS release exposes. Usage:
    python tools/read_sw_typelib.py enum swWzdHoleTypes_e
    python tools/read_sw_typelib.py iface IHoleStandardsData
"""
import glob
import json
import os
import sys

import pythoncom

SW_DIR_GLOBS = [r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS*"]


def live_install_dir():
    """The install folder of the SolidWorks session that is running now (None if none is)."""
    try:
        import win32com.client as w
        return w.GetActiveObject("SldWorks.Application").GetExecutablePath
    except Exception:
        return None


def tlb_paths(prefer_dir=None):
    """Type libraries of the install that matters: ``prefer_dir``, else the RUNNING session's install, else the
    newest. Several releases can be installed side by side; evidence must come from the one that is running."""
    dirs = [prefer_dir] if prefer_dir else ([live_install_dir()] if live_install_dir() else [])
    for pat in SW_DIR_GLOBS:
        dirs += sorted(glob.glob(pat), reverse=True)
    out = {}
    for d in dirs:
        for name in ("swconst.tlb", "sldworks.tlb"):
            p = os.path.join(d or "", name)
            if os.path.isfile(p):
                out.setdefault(name, p)
    return out


def _walk(tlb):
    for i in range(tlb.GetTypeInfoCount()):
        ti = tlb.GetTypeInfo(i)
        name = tlb.GetDocumentation(i)[0]
        yield name, ti, ti.GetTypeAttr()


def enum_members(name, prefer_dir=None):
    for tlbname, p in tlb_paths(prefer_dir).items():
        tlb = pythoncom.LoadTypeLib(p)
        for n, ti, attr in _walk(tlb):
            if n == name and attr.typekind == pythoncom.TKIND_ENUM:
                rows = []
                for k in range(attr.cVars):
                    vd = ti.GetVarDesc(k)
                    rows.append((ti.GetNames(vd.memid)[0], vd.value))
                return rows
    return None


def iface_members(name, prefer_dir=None):
    for tlbname, p in tlb_paths(prefer_dir).items():
        tlb = pythoncom.LoadTypeLib(p)
        for n, ti, attr in _walk(tlb):
            if n == name and attr.typekind in (pythoncom.TKIND_INTERFACE, pythoncom.TKIND_DISPATCH):
                rows = []
                for k in range(attr.cFuncs):
                    fd = ti.GetFuncDesc(k)
                    names = ti.GetNames(fd.memid)
                    kind = {1: "method", 2: "get", 4: "put", 8: "putref"}.get(fd.invkind, str(fd.invkind))
                    rows.append({"name": names[0], "kind": kind, "params": list(names[1:])})
                return rows
    return None


if __name__ == "__main__":
    what, name = sys.argv[1], sys.argv[2]
    res = enum_members(name) if what == "enum" else iface_members(name)
    print(json.dumps(res, indent=1) if res is not None else "NOT FOUND")
