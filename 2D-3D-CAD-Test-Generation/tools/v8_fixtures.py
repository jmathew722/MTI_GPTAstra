"""v8 test fixtures (labelled, never presented as real drawings).

multipage: ``ring_2page.pdf`` = the ring drawing's page twice (byte-identical page content), so page 2's extraction IS the page-1 extraction. The cache entry is
seeded from the real, paid ring extraction with ZERO new model calls. It exercises sheet order / count / per-sheet size, scale, geometry, notes and per-page
verification. It does not test that a *different* second page reads correctly (that needs a real multi-page drawing and a paid read per page).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.v7_env import REPO  # noqa: E402
from reverse import safety  # noqa: E402

EVID = REPO / "docs" / "solidflow-upgrades" / "v8-evidence"


def make_multipage() -> Path:
    import fitz
    src = REPO / "Simple Parts" / "A001651E.PDF"
    out = EVID / "_fixtures" / "ring_2page.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for _ in range(2):
        d = fitz.open(str(src))
        doc.insert_pdf(d)
        d.close()
    doc.save(str(out))
    doc.close()
    sha_src = safety.sha256_file(src)
    sha_new = safety.sha256_file(out)
    base = json.loads((EVID / "_cache" / sha_src[:32] / "reference_extraction.json").read_text(encoding="utf-8"))
    base.pop("more_pages", None)
    p1 = copy.deepcopy(base)
    p2 = copy.deepcopy(base)
    for i, p in enumerate((p1, p2)):
        p["source"] = dict(base["source"], sha256=sha_new, filename=out.name, pages=2, page_extracted=i + 1)
        p["provenance"] = dict(base["provenance"], origin="fixture_duplicate_page")
        p["warnings"] = list(base.get("warnings", [])) + ["FIXTURE: page 2 is a copy of page 1; its extraction was copied, not read."]
        p["extraction_id"] = f"fixture_p{i + 1}_{sha_new[:8]}"
    p1["more_pages"] = [p2]
    dst = EVID / "_cache" / sha_new[:32] / "reference_extraction.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(p1, indent=2, ensure_ascii=False), encoding="utf-8")
    (EVID / "_fixtures" / "README.txt").write_text(__doc__, encoding="utf-8")
    return out


if __name__ == "__main__":
    print(make_multipage())
