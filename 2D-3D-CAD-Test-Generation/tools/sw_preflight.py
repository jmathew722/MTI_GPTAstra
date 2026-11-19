"""Run the SOLIDWORKS 2025 environment gate against the running session (read-only) and write a path-free result.

    python tools/sw_preflight.py [--out docs/hole-wizard/preflight-result.json]

Never clicks a dialog, edits a database or changes a SolidWorks setting. Exit code 0 = ready, 3 = preflight failed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.ir.solidworks import sw_preflight as pf  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT.parent / "docs" / "hole-wizard" / "preflight-result.json"))
    a = ap.parse_args(argv)
    import win32com.client as w
    app = w.GetActiveObject("SldWorks.Application")
    res, extras = pf.run_live_preflight(app)
    out = {**res.to_dict(), **extras}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("status", "code", "application_revision", "database_version", "database_expected_version",
                                          "toolbox_file_version", "toolbox_index_version")}))
    return 0 if res.ok else 3


if __name__ == "__main__":
    sys.exit(main())
