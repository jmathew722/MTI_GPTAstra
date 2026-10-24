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
