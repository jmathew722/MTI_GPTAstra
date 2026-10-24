"""DWG -> DXF with the ODA File Converter (free; path from ODA_CONVERTER).

The converter is a GUI application and may briefly pop a window while it runs.
It converts whole folders, so one DWG is staged in a temporary input folder and
the single DXF it produces is moved to the requested path.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

OUT_VERSION = "ACAD2018"


class OdaError(RuntimeError):
    pass


def convert(dwg: Path, out_dxf: Path, cmd: Optional[list[str]] = None,
            timeout_s: int = 300) -> Path:
    """Convert one DWG to DXF at out_dxf and return the absolute out path."""
    dwg = Path(dwg).resolve()
    out_dxf = Path(out_dxf).resolve()
    if not dwg.is_file():
        raise FileNotFoundError(f"DWG not found: {dwg}")
    if cmd is None:
        from bench.config import oda_converter
        cmd = [str(oda_converter())]
    out_dxf.parent.mkdir(parents=True, exist_ok=True)
    # Never leave a stale DXF behind if this conversion fails.
    out_dxf.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tin, tempfile.TemporaryDirectory() as tout:
        staged = Path(tin) / ("drawing" + dwg.suffix.lower())
        shutil.copy2(dwg, staged)
        try:
            r = subprocess.run(
                list(cmd) + [tin, tout, OUT_VERSION, "DXF", "0", "1"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout_s)
        except subprocess.TimeoutExpired as e:
            raise OdaError(f"ODA converter timed out after {timeout_s}s for {dwg}") from e
        produced = sorted(Path(tout).glob("*.dxf"))
        if not produced:
            raise OdaError(f"ODA converter wrote no DXF for {dwg} "
                           f"(exit {r.returncode}): {(r.stderr or '')[-300:]}")
        if len(produced) > 1:
            raise OdaError(f"ODA converter wrote more than one DXF for {dwg}: "
                           f"{[p.name for p in produced]}")
        shutil.move(str(produced[0]), out_dxf)
    return out_dxf
