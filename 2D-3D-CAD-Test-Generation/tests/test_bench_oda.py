"""bench.oda: stages one DWG, calls the converter, moves the DXF; errors are clear."""
import sys

import pytest

from bench.oda import OdaError, convert

FAKE = r'''
import sys, pathlib
src, dst, ver, typ, rec, aud = sys.argv[1:7]
for p in pathlib.Path(src).iterdir():
    (pathlib.Path(dst) / (p.stem + "." + typ.lower())).write_text("0\nEOF\n")
'''


def _script(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return [sys.executable, str(p)]


def _dwg(tmp_path, name="x.dwg"):
    d = tmp_path / name
    d.write_bytes(b"AC1015")
    return d


def test_convert(tmp_path):
    fake = tmp_path / "fake_oda.py"
    fake.write_text(FAKE, encoding="utf-8")
    dwg = tmp_path / "A050511E.DWG"
    dwg.write_bytes(b"AC1015")
    out = tmp_path / "out" / "drawing.dxf"
    convert(dwg, out, cmd=[sys.executable, str(fake)])
    assert out.read_text() == "0\nEOF\n"


def test_converter_produces_nothing(tmp_path):
    noop = tmp_path / "noop.py"
    noop.write_text("pass", encoding="utf-8")
    dwg = tmp_path / "x.dwg"
    dwg.write_bytes(b"AC1015")
    with pytest.raises(OdaError, match="no DXF"):
        convert(dwg, tmp_path / "o.dxf", cmd=[sys.executable, str(noop)])


def test_stale_output_removed_on_failure(tmp_path):
    out = tmp_path / "o.dxf"
    out.write_text("stale")
    cmd = _script(tmp_path, "noop.py", "pass")
    with pytest.raises(OdaError):
        convert(_dwg(tmp_path), out, cmd=cmd)
    assert not out.exists()


def test_stale_output_replaced(tmp_path):
    out = tmp_path / "o.dxf"
    out.write_text("stale")
    convert(_dwg(tmp_path), out, cmd=_script(tmp_path, "f.py", FAKE))
    assert out.read_text() == "0\nEOF\n"


def test_timeout(tmp_path):
    cmd = _script(tmp_path, "slow.py", "import time; time.sleep(30)")
    with pytest.raises(OdaError, match="timed out"):
        convert(_dwg(tmp_path), tmp_path / "o.dxf", cmd=cmd, timeout_s=1)


def test_missing_input(tmp_path):
    cmd = _script(tmp_path, "boom.py", "raise SystemExit(9)")
    with pytest.raises(FileNotFoundError):
        convert(tmp_path / "nope.dwg", tmp_path / "o.dxf", cmd=cmd)


def test_multiple_outputs(tmp_path):
    body = ("import sys, pathlib\n"
            "d = pathlib.Path(sys.argv[2])\n"
            "(d / 'a.dxf').write_text('1'); (d / 'b.dxf').write_text('2')\n")
    with pytest.raises(OdaError, match="more than one"):
        convert(_dwg(tmp_path), tmp_path / "o.dxf", cmd=_script(tmp_path, "m.py", body))


def test_non_utf8_stderr(tmp_path):
    body = "import sys; sys.stderr.buffer.write(b'\xff\xfe bad')\n"
    with pytest.raises(OdaError, match="no DXF"):
        convert(_dwg(tmp_path), tmp_path / "o.dxf", cmd=_script(tmp_path, "e.py", body))


def test_argument_list(tmp_path):
    log = tmp_path / "argv.txt"
    body = (
        "import sys, pathlib\n"
        f"pathlib.Path(r'{log}').write_text('|'.join(sys.argv[3:8]))\n"
        "(pathlib.Path(sys.argv[2]) / 'd.dxf').write_text('x')\n"
    )
    convert(_dwg(tmp_path), tmp_path / "o.dxf", cmd=_script(tmp_path, "a.py", body))
    assert log.read_text() == "ACAD2018|DXF|0|1|*.DWG"


def test_filter_is_seventh_arg(tmp_path):
    log = tmp_path / "argv7.txt"
    body = ("import sys, pathlib\n"
            f"pathlib.Path(r'{log}').write_text(sys.argv[7] + '|' + "
            "','.join(p.name for p in pathlib.Path(sys.argv[1]).iterdir()))\n"
            "(pathlib.Path(sys.argv[2]) / 'd.dxf').write_text('x')\n")
    convert(_dwg(tmp_path), tmp_path / "o.dxf", cmd=_script(tmp_path, "a7.py", body))
    assert log.read_text() == "*.DWG|drawing.DWG"


def test_stdout_in_error(tmp_path):
    body = "print('STDOUT-MARKER')\n"
    with pytest.raises(OdaError, match="STDOUT-MARKER"):
        convert(_dwg(tmp_path), tmp_path / "o.dxf", cmd=_script(tmp_path, "so.py", body))
