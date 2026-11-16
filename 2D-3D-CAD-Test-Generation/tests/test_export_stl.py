"""STL copy written beside the .sldprt after a COM build (no SolidWorks needed)."""
from pathlib import Path

from pipeline.solidworks_builder import export_stl


class _Doc:
    def __init__(self, write=True, fail=False):
        self.write, self.fail, self.calls = write, fail, []

    def SaveAs3(self, path, version, options):
        self.calls.append((path, version, options))
        if self.fail:
            raise RuntimeError("COM error")
        if self.write:
            Path(path).write_bytes(b"solid part")
        return 0


def test_export_stl_writes_beside_the_sldprt(tmp_path):
    doc = _Doc()
    out = export_stl(doc, tmp_path / "Bracket.sldprt")
    assert out == str((tmp_path / "Bracket.stl").resolve())
    assert Path(out).read_bytes() == b"solid part"
    assert doc.calls == [(out, 0, 1)]          # absolute path, silent save


def test_export_stl_failure_is_not_fatal(tmp_path):
    assert export_stl(_Doc(fail=True), tmp_path / "P.sldprt") is None


def test_export_stl_never_reports_a_stale_file(tmp_path):
    stale = tmp_path / "P.stl"
    stale.write_bytes(b"old build")
    assert export_stl(_Doc(write=False), tmp_path / "P.sldprt") is None
    assert not stale.exists()
