"""bench.sw_tasks: PDF crop and preference restore (no SolidWorks needed)."""
import re
from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")
from bench import sw_tasks  # noqa: E402
from bench.sw_tasks import crop_to_content, temporary_prefs  # noqa: E402


def test_crop_to_content(tmp_path):
    p = tmp_path / "x.pdf"
    doc = fitz.open()
    page = doc.new_page(width=3000, height=3000)
    page.draw_rect(fitz.Rect(1000, 1200, 1400, 1500))
    page.insert_text((10, 2990), "SOLIDWORKS Educational Product. For Instructional Use Only.")
    doc.new_page(width=3000, height=3000)          # empty sheet -> dropped
    doc.save(p)
    crop_to_content(p, margin_pt=10)
    out = fitz.open(p)
    assert len(out) == 1
    cb = out[0].cropbox
    assert 985 <= cb.x0 <= 995 and 1405 <= cb.x1 <= 1415


def test_prefs_restored_even_on_error():
    class App:
        def __init__(self):
            self.p = {323: True, 325: False}

        def GetUserPreferenceToggle(self, k):
            return self.p[k]

        def SetUserPreferenceToggle(self, k, v):
            self.p[k] = v

    app = App()
    with pytest.raises(RuntimeError):
        with temporary_prefs(app, {323: False, 325: True}):
            assert app.p == {323: False, 325: True}
            raise RuntimeError("boom")
    assert app.p == {323: True, 325: False}


def test_no_toplevel_com_imports():
    src = Path(sw_tasks.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^(import|from)\s+(win32com|pythoncom)", src, re.M)


class _Doc:
    def __init__(self, code, write=False):
        self.code, self.write, self.saved = code, write, []

    def GetTitle(self):
        return "part.SLDPRT"

    def SaveAs3(self, path, a, b):
        self.saved.append(path)
        if self.write:
            Path(path).write_text("x")
        return self.code


class _App:
    def __init__(self, doc):
        self.doc, self.ap, self.closed = doc, 203, []

    def OpenDoc6(self, *a):
        return self.doc

    def GetUserPreferenceIntegerValue(self, k):
        assert k == sw_tasks.STEP_AP
        return self.ap

    def SetUserPreferenceIntegerValue(self, k, v):
        assert k == sw_tasks.STEP_AP
        self.ap = v

    def CloseDoc(self, name):
        self.closed.append(name)


@pytest.fixture
def no_com(monkeypatch):
    class V:
        value = 0

    monkeypatch.setattr(sw_tasks, "_byref_long", lambda: V())


def test_step_failure_restores_ap_and_closes(no_com, tmp_path):
    app = _App(_Doc(1))
    with pytest.raises(RuntimeError):
        sw_tasks.sldprt_to_step(app, tmp_path / "a.SLDPRT", tmp_path / "a.step", tmp_path / "a.png")
    assert app.ap == 203
    assert app.closed == ["part.SLDPRT"]


def test_step_success_and_stale_file_rejected(no_com, tmp_path):
    out = tmp_path / "a.step"
    app = _App(_Doc(0, write=True))
    sw_tasks.sldprt_to_step(app, tmp_path / "a.SLDPRT", out, tmp_path / "a.png")
    assert out.exists() and app.ap == 203
    # stale file: SaveAs3 says 0 but writes nothing -> must not pass as success
    out2 = tmp_path / "b.step"
    out2.write_text("old")
    app2 = _App(_Doc(0, write=False))
    with pytest.raises(RuntimeError):
        sw_tasks.sldprt_to_step(app2, tmp_path / "b.SLDPRT", out2, tmp_path / "b.png")
    assert app2.closed == ["part.SLDPRT"]


# ---- review fixes -------------------------------------------------------------------

def test_crop_all_empty_raises_and_ignores_frames(tmp_path):
    p = tmp_path / "e.pdf"
    doc = fitz.open()
    pg = doc.new_page(width=3000, height=3000)
    pg.draw_rect(fitz.Rect(5, 5, 2995, 2995))          # border frame only
    doc.save(p)
    doc.close()
    with pytest.raises(ValueError, match="no drawing content"):
        crop_to_content(p)
    p.unlink()                                          # not locked after the error

    doc = fitz.open()
    pg = doc.new_page(width=3000, height=3000)
    pg.draw_rect(fitz.Rect(5, 5, 2995, 2995))
    pg.draw_rect(fitz.Rect(1000, 1200, 1400, 1500))
    doc.save(p)
    doc.close()
    crop_to_content(p, margin_pt=10)
    out = fitz.open(p)
    cb = out[0].cropbox
    out.close()
    assert cb.x0 > 900 and cb.x1 < 1500


class _Data:
    def __init__(self, reject=()):
        self.reject, self.calls = set(reject), []


def _fake_invoke(obj, name, kind, sheet, *args):
    obj.calls.append((name, sheet))
    return False if (name, sheet) in obj.reject else True


def test_configure_import_rejection(monkeypatch):
    monkeypatch.setattr(sw_tasks, "_invoke", _fake_invoke)
    sw_tasks._configure_import(_Data())
    with pytest.raises(RuntimeError, match="SetPaperSize.*''"):
        sw_tasks._configure_import(_Data({("SetPaperSize", "")}))
    d = _Data({("SetSheetScale", "Model")})            # warning only
    sw_tasks._configure_import(d)
    assert ("SetPosition", "Model") in d.calls


def test_relative_paths_made_absolute_and_stale_removed(no_com, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "old.step").write_text("stale")
    doc = _Doc(1)                                       # fails, so the stale file must be gone
    app = _App(doc)
    with pytest.raises(RuntimeError):
        sw_tasks.sldprt_to_step(app, "p.SLDPRT", "old.step", "old.png")
    assert not (tmp_path / "old.step").exists()
    assert all(Path(x).is_absolute() for x in doc.saved)


def test_dwg_paths_absolute(no_com, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sw_tasks, "_invoke", _fake_invoke)
    seen = []

    class PDoc(_Doc):
        def SaveAs3(self, path, a, b):
            d = fitz.open()
            d.new_page(width=500, height=500).draw_rect(fitz.Rect(100, 100, 200, 200))
            d.save(path)
            d.close()
            return super().SaveAs3(path, a, b)

    class DApp(_App):
        def __init__(self, doc):
            super().__init__(doc)
            self.t = {323: True, 325: False}

        def GetImportFileData(self, f):
            seen.append(f)
            return _Data()

        def LoadFile4(self, f, a, d, e):
            seen.append(f)
            return self.doc

        def GetUserPreferenceToggle(self, k):
            return self.t[k]

        def SetUserPreferenceToggle(self, k, v):
            self.t[k] = v

    doc = PDoc(0)
    app = DApp(doc)
    sw_tasks.dwg_to_pdf(app, "a.DWG", "o.pdf")
    assert all(Path(x).is_absolute() for x in seen + doc.saved) and len(seen) == 2
    assert app.t == {323: True, 325: False}


def test_cleanup_failure_does_not_mask_original(no_com, tmp_path):
    class BadClose(_App):
        def CloseDoc(self, name):
            raise OSError("close blew up")

    with pytest.raises(RuntimeError, match="SaveAs3 1"):
        sw_tasks.sldprt_to_step(BadClose(_Doc(1)), tmp_path / "a.SLDPRT",
                                tmp_path / "a.step", tmp_path / "a.png")
    # no original error: the cleanup failure is raised
    with pytest.raises(OSError, match="close blew up"):
        sw_tasks.sldprt_to_step(BadClose(_Doc(0, write=True)), tmp_path / "a.SLDPRT",
                                tmp_path / "b.step", tmp_path / "b.png")


# ---- no partial outputs: write to a temp name, os.replace only after every check -------

def test_step_partial_write_then_error_leaves_nothing(no_com, tmp_path):
    doc = _Doc(1, write=True)                           # writes a file, then reports failure
    with pytest.raises(RuntimeError, match="SaveAs3 1"):
        sw_tasks.sldprt_to_step(_App(doc), tmp_path / "a.SLDPRT", tmp_path / "reference.step",
                                tmp_path / "model.png")
    assert doc.saved[0].endswith("reference.tmp.step")
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_step_success_moves_temp_into_place(no_com, tmp_path):
    sw_tasks.sldprt_to_step(_App(_Doc(0, write=True)), tmp_path / "a.SLDPRT",
                            tmp_path / "reference.step", tmp_path / "model.png")
    assert (tmp_path / "reference.step").is_file()
    assert not (tmp_path / "reference.tmp.step").exists()


def _pdf_app(page_draw):
    class PDoc(_Doc):
        def SaveAs3(self, path, a, b):
            d = fitz.open()
            page_draw(d.new_page(width=500, height=500))
            d.save(path)
            d.close()
            return super().SaveAs3(path, a, b)

    class DApp(_App):
        t = {323: True, 325: False}

        def GetImportFileData(self, f):
            return _Data()

        def LoadFile4(self, f, a, d, e):
            return self.doc

        def GetUserPreferenceToggle(self, k):
            return self.t[k]

        def SetUserPreferenceToggle(self, k, v):
            self.t[k] = v

    doc = PDoc(0)
    return DApp(doc), doc


def test_pdf_crop_failure_after_save_leaves_nothing(no_com, tmp_path, monkeypatch):
    monkeypatch.setattr(sw_tasks, "_invoke", _fake_invoke)
    app, doc = _pdf_app(lambda pg: pg.draw_rect(fitz.Rect(2, 2, 498, 498)))   # frame only
    with pytest.raises(ValueError, match="no drawing content"):
        sw_tasks.dwg_to_pdf(app, tmp_path / "a.DWG", tmp_path / "drawing.pdf")
    assert doc.saved[0].endswith("drawing.tmp.pdf")
    assert list(tmp_path.iterdir()) == []


def test_pdf_success_moves_temp_into_place(no_com, tmp_path, monkeypatch):
    monkeypatch.setattr(sw_tasks, "_invoke", _fake_invoke)
    app, _ = _pdf_app(lambda pg: pg.draw_rect(fitz.Rect(100, 100, 200, 200)))
    sw_tasks.dwg_to_pdf(app, tmp_path / "a.DWG", tmp_path / "drawing.pdf")
    assert [p.name for p in tmp_path.iterdir()] == ["drawing.pdf"]


def test_connect_always_returns_a_late_bound_object(monkeypatch):
    """E027: a makepy cache for sldworks.tlb made SolidWorks objects typed, and their
    [in,out] params rejected the byref VARIANTs passed to OpenDoc6/LoadFile4."""
    win32 = pytest.importorskip("win32com.client")
    import win32com.client.dynamic as dynamic

    class Typed:
        _oleobj_ = object()

    seen = {}
    monkeypatch.setattr(win32, "GetActiveObject", lambda progid: Typed())
    monkeypatch.setattr(dynamic, "Dispatch", lambda ole: seen.setdefault("ole", ole))
    sw_tasks.connect(retries=1, wait_s=0)
    assert seen["ole"] is Typed._oleobj_
