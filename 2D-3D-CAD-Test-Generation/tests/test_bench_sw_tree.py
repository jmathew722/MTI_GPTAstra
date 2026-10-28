"""bench.sw_tree: feature-tree reader over a fake COM object (no SolidWorks)."""
import json
import os
import time

import pytest

from bench import sw_tasks, sw_tree


class _Sketch:
    def __init__(self, status):
        self.status = status

    def GetConstrainedStatus(self):
        return self.status


class _Feat:
    def __init__(self, name, typ, subs=(), status=None):
        self.Name, self.typ, self.subs, self.status, self.next = name, typ, list(subs), status, None
        self.sub_next = None
        for a, b in zip(self.subs, self.subs[1:]):
            a.sub_next = b

    def GetTypeName2(self):
        return self.typ

    def GetNextFeature(self):
        return self.next

    def GetFirstSubFeature(self):
        return self.subs[0] if self.subs else None

    def GetNextSubFeature(self):
        return self.sub_next

    def GetSpecificFeature2(self):
        if self.status == "boom":
            raise RuntimeError("COM")
        return _Sketch(self.status) if self.status is not None else None


class _Doc:
    def __init__(self, feats):
        self.feats = feats
        for a, b in zip(feats, feats[1:]):
            a.next = b

    def FirstFeature(self):
        return self.feats[0] if self.feats else None

    def GetTitle(self):
        return "p_ir.SLDPRT"


class _App:
    def __init__(self, doc):
        self.doc, self.closed, self.opened = doc, [], []

    def OpenDoc6(self, path, typ, opts, cfg, err, warn):
        self.opened.append((path, typ, opts))
        return self.doc

    def CloseDoc(self, title):
        self.closed.append(title)


@pytest.fixture
def fake_com(monkeypatch):
    class V:
        value = 0

    monkeypatch.setattr(sw_tasks, "_byref_long", lambda: V())
    monkeypatch.setattr(sw_tree, "_typed", lambda obj, iface: obj)
    monkeypatch.setattr(sw_tree, "_first_feature", lambda doc: doc.FirstFeature())


def _doc():
    return _Doc([
        _Feat("Origin", "OriginProfileFeature"),
        _Feat("Top Plane", "RefPlane"),
        _Feat("Boss-Extrude1", "Extrusion", [_Feat("Sketch1", "ProfileFeature", status=3)]),
        _Feat("CBORE1", "HoleWzd", [_Feat("Sketch2", "ProfileFeature", status=2),
                                    _Feat("Sketch3", "ProfileFeature", status=3),
                                    _Feat("CosmeticThread1", "CosmeticThread")]),
        _Feat("Sketch9", "ProfileFeature", status="boom"),
        _Feat("Fillet1", "Fillet"),
    ])


def test_read_tree_records_every_feature_and_closes(fake_com, tmp_path):
    app = _App(_doc())
    tree = sw_tree.read_tree(app, tmp_path / "p_ir.SLDPRT")
    assert [f["name"] for f in tree] == ["Origin", "Top Plane", "Boss-Extrude1", "CBORE1", "Sketch9", "Fillet1"]
    assert [f["index"] for f in tree] == list(range(6))
    assert tree[0]["status"] is None and tree[0]["subs"] == []
    assert tree[2]["subs"] == [{"name": "Sketch1", "type": "ProfileFeature", "status": 3}]
    assert [s["status"] for s in tree[3]["subs"]] == [2, 3, None]
    assert tree[4]["status"] is None                     # a COM failure reading the sketch: unknown, not a crash
    assert app.closed == ["p_ir.SLDPRT"]
    path, typ, opts = app.opened[0]
    assert os.path.isabs(path) and typ == sw_tasks.SW_DOC_PART
    assert opts & sw_tasks.OPEN_READONLY
    json.dumps(tree)                                      # the record is plain JSON


def test_read_tree_open_failure_raises(fake_com, tmp_path):
    app = _App(None)
    with pytest.raises(RuntimeError, match="OpenDoc6"):
        sw_tree.read_tree(app, tmp_path / "p.SLDPRT")


def test_read_tree_closes_on_error(fake_com, tmp_path, monkeypatch):
    app = _App(_doc())
    monkeypatch.setattr(sw_tree, "_first_feature", lambda doc: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        sw_tree.read_tree(app, tmp_path / "p.SLDPRT")
    assert app.closed == ["p_ir.SLDPRT"]


def test_cached_tree(fake_com, tmp_path):
    sld = tmp_path / "p_ir.SLDPRT"
    sld.write_bytes(b"x")
    app = _App(_doc())
    tree = sw_tree.cached_tree(tmp_path, sld, app)
    cache = tmp_path / sw_tree.CACHE
    assert cache.is_file() and json.loads(cache.read_text(encoding="utf-8")) == tree
    # a fresh cache is used without SolidWorks
    assert sw_tree.cached_tree(tmp_path, sld, None) == tree
    assert sw_tree.cached_tree(tmp_path, sld, _App(None)) == tree      # OpenDoc6 never called
    assert not sw_tree.is_stale(tmp_path, sld)
    # an older cache is re-read when SolidWorks is there; without it, it is still returned (stale)
    old = time.time() - 100
    os.utime(cache, (old, old))
    assert sw_tree.is_stale(tmp_path, sld)
    assert sw_tree.cached_tree(tmp_path, sld, None) == tree
    app2 = _App(_Doc([_Feat("Origin", "OriginProfileFeature")]))
    assert len(sw_tree.cached_tree(tmp_path, sld, app2)) == 1 and app2.opened
    # no cache, no SolidWorks
    assert sw_tree.cached_tree(tmp_path / "nope", sld, None) is None
