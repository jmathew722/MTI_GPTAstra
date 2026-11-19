"""Adds a SolidWorks build recording to a fixture part's run folder, produced by the REAL recorder (pipeline.solidworks_recorder)
with a synthetic frame source (a box that grows as "features" are added). Nothing here writes a manifest by hand except the
failure kinds, which use the recorder's own writers.

    python make_recording_fixture.py --run-dir <FINAL_OUTPUTs>/<part> --part NAME --kind ready|partial|failed|skipped
WebM is forced: Playwright's bundled Chromium has no H.264 decoder, and the player is the same element either way.
Prints one JSON object: the manifest.
"""
import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4] / "2D-3D-CAD-Test-Generation"
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from pipeline import solidworks_recorder as rec  # noqa: E402


class Growing(rec.FrameSource):
    """A fake SolidWorks window: a part that gets bigger over time. `cover` makes every other poll 'covered'."""
    name = "fake"

    def __init__(self, cover=False):
        self.t0, self.cover, self.n = time.time(), cover, 0

    def latest(self):
        self.n += 1
        if self.cover and self.n % 3 == 0:
            return None, True
        f = np.full((360, 640, 3), 235, np.uint8)
        k = min(1.0, (time.time() - self.t0) / 3.0)
        w, h = int(80 + 380 * k), int(60 + 200 * k)
        f[180 - h // 2:180 + h // 2, 320 - w // 2:320 + w // 2] = (150, 110, 90)
        return f, False


def webm(out, size, fps):
    return rec._CvWebmEncoder(Path(out) / "solidworks_recording.partial.webm", size, fps)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--part", required=True)
    ap.add_argument("--kind", choices=("ready", "partial", "failed", "skipped"), default="ready")
    ap.add_argument("--sha", default="")
    a = ap.parse_args()
    out = a.run_dir
    out.mkdir(parents=True, exist_ok=True)
    rec.clear_stale(out)
    if a.kind == "skipped":
        rec.write_skipped(out, run_id="run_fixture_" + a.part, part=a.part, source_sha256=a.sha, reason="Extraction failed before SolidWorks.")
    elif a.kind == "failed":
        r = rec.SolidWorksRecorder(out, part=a.part, run_id="run_fixture_" + a.part, source_sha256=a.sha, window_finder=lambda app: None)
        rec.capability = lambda: {"available": True, "backend": "wgc", "encoder": "x", "reason": ""}      # reach the window lookup
        r.start()
    else:
        r = rec.SolidWorksRecorder(out, part=a.part, run_id="run_fixture_" + a.part, source_sha256=a.sha, fps=10, paced=False, hold_s=0,
                                   source_factory=lambda h: Growing(cover=a.kind == "partial"), encoder_factory=webm, total_features=3)
        r.start()
        for i, (fid, kind) in enumerate((("F001", "prism"), ("F002", "hole"), ("F005", "hole"))):
            time.sleep(1.1)
            r.after_feature(fid, kind, "built")
        time.sleep(0.5)
        r.stop(outcome="completed")
    print(json.dumps(json.loads((out / rec.MANIFEST).read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
