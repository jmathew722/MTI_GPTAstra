"""Writes TEST-ONLY 3D -> 2D fixture jobs into an ISOLATED data dir (never the real one): python make_reverse_fixture.py <data_dir> [reset]

Every artifact is a labelled stand-in (see tests/server/reverse_fixtures.py): the PDF says it is a test fixture, manifest.json has "demo": true.
SOLIDWORKS is not used and these are not evidence of native CAD output.

Jobs (ids are fixed so the specs can open them by URL):
  r3d_0000000000000001  one completed part
  r3d_0000000000000002  running: one part at Dimensions (STL exists, no drawing yet) and one queued part
  r3d_0000000000000003  mixed: review required (2 sheets, 3 issues), completed, failed (STL only)
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
import reverse_fixtures as fx  # noqa: E402

JOBS = {
    "r3d_0000000000000001": ([("flange.SLDPRT", "completed")], "2026-11-25T09:00:00+00:00", None),
    "r3d_0000000000000002": ([("bracket-run.SLDPRT", "processing"), ("cover.SLDPRT", "queued")], "2026-11-25T10:00:00+00:00", None),
    "r3d_0000000000000003": ([("bracket.SLDPRT", "review"), ("plate.SLDPRT", "completed"), ("broken.SLDPRT", "failed")], "2026-11-25T11:00:00+00:00",
                             [{"name": "notes.txt", "reason": "notes.txt is not a SOLIDWORKS part (.SLDPRT)."}]),
}


def main() -> int:
    data = Path(sys.argv[1])
    if len(sys.argv) > 2 and sys.argv[2] == "reset":
        shutil.rmtree(data / "outputs" / "3d-to-2d", ignore_errors=True)
    for jid, (parts, created, rej) in JOBS.items():
        fx.write_job(data, jid, parts, created=created, rejected=rej)
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
