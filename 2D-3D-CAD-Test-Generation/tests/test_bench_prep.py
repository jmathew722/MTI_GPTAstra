"""bench.prep: resumable steps, per-part logging, failures don't stop the batch."""
import json

import pytest

from bench import config, crosscheck, dxfread, keygen, oda, prep, split, sw_tasks
from bench.callouts import parse
from bench.dxfread import Dim, Drawing
from bench.features import Feature, Key

P1, P2 = "A050291E", "A050381E"          # format-dev parts in the manifest


def test_run_step_skips_done_and_logs_failures(tmp_path):
    calls = []

    def ok(part, d):
        calls.append(part)
        (d / "out.txt").write_text("x")

    def boom(part, d):
        raise RuntimeError("bad file")

    log = tmp_path / "prep_log.jsonl"
    res = prep.run_step("demo", ["A", "B"], tmp_path, lambda d: d / "out.txt", ok, log, force=False)
    assert res == {"A": "ok", "B": "ok"} and calls == ["A", "B"]
    res2 = prep.run_step("demo", ["A", "B"], tmp_path, lambda d: d / "out.txt", ok, log, force=False)
    assert res2 == {"A": "skipped", "B": "skipped"} and calls == ["A", "B"]
    res3 = prep.run_step("demo2", ["A", "C"], tmp_path, lambda d: d / "never.txt", boom, log, force=False)
    assert res3["A"].startswith("failed") and res3["C"].startswith("failed")
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert {(x["step"], x["part"], x["status"].split(":")[0]) for x in lines} >= {
        ("demo", "A", "ok"), ("demo", "A", "skipped"), ("demo2", "C", "failed")}


def test_run_step_force_reruns(tmp_path):
    calls = []
    (tmp_path / "A").mkdir()
    (tmp_path / "A" / "out.txt").write_text("old")
    res = prep.run_step("demo", ["A"], tmp_path, lambda d: d / "out.txt",
                        lambda p, d: calls.append(p), tmp_path / "log.jsonl", force=True)
    assert res == {"A": "ok"} and calls == ["A"]


# ---- main() -------------------------------------------------------------------------------

@pytest.fixture
def root(tmp_path, monkeypatch):
    """A tmp data root; the real .env is never read."""
    monkeypatch.setattr(config, "DOTENV", tmp_path / "absent.env")
    r = tmp_path / "data"
    r.mkdir()
    monkeypatch.setenv(config.DATA_ENV, str(r))
    return r


def _key(part, units="inch", source="reference.step"):
    holes = [Feature(id=f"K{i:03d}", type="thru_hole", axis=[0, 0, 1], center=[x, y, 0], d=0.344,
                     depth=0.5, thru=True)
             for i, (x, y) in enumerate([(0.5, 0.5), (3.5, 0.5), (0.5, 2.5), (3.5, 2.5)], 1)]
    return Key(part=part, units=units, source=source, envelope=[4.0, 3.0, 0.5], features=holes)


def _drawing(width=4.0):
    dims = [Dim("linear", width, width, "<>", False, None), Dim("linear", 3.0, 3.0, "<>", False, None),
            Dim("linear", 0.5, 0.5, "<>", False, None), Dim("linear", 2.0, 2.0, "<>", False, None)]
    return Drawing(dims=dims, callouts=[parse(".344 DIA. THRU (4) HLS.")],
                   general_tol={3: 0.005, 2: 0.01}, units_hint="inch")


@pytest.fixture
def fakes(root, monkeypatch):
    """keygen / dxfread replaced by tiny objects. P2's drawing has one unexplained width."""
    seen = []

    def from_step(step, *, units, part):
        assert step.name == "reference.step" and step.is_file()
        seen.append((part, units))
        return _key(part, units)

    monkeypatch.setattr(keygen, "from_step", from_step)
    monkeypatch.setattr(dxfread, "read", lambda p: _drawing(4.25 if p.parent.name == P2 else 4.0))
    for p in (P1, P2):
        (root / p).mkdir()
        (root / p / "reference.step").write_text("ISO-10303-21;")
        (root / p / "drawing.dxf").write_text("0\nEOF\n")
    return seen


def _load(root, part):
    return Key.load(root / part / "key.json")


def test_missing_data_root_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "DOTENV", tmp_path / "absent.env")
    monkeypatch.setenv(config.DATA_ENV, str(tmp_path / "nope"))
    assert prep.main(["status"]) == 2
    assert "MTI_BENCH_DATA" in capsys.readouterr().out


def test_unknown_part_exits_2(root, capsys):
    assert prep.main(["status", "--parts", P1, "BOGUS"]) == 2
    out = capsys.readouterr().out
    assert "BOGUS" in out and P1 in out and P2 in out


def _fake_dataset(src):
    files = {}
    for p in (P1, P2):
        pr = split.pair(p)
        for rel, data in ((f"{split.DWG_ROOT}/{pr.dwg}", b"AC1015 dwg " + p.encode()),
                          (f"{split.MODEL_ROOT}/{pr.model}", b"sldprt " + p.encode())):
            f = src / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
            files[f] = (data, f.stat().st_mtime_ns)
    return files


def _snapshot(src):
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in src.rglob("*") if p.is_file()}


def test_copy_reads_source_only(root, tmp_path):
    src = tmp_path / "MTI Example Drawings"
    files = _fake_dataset(src)
    before = _snapshot(src)
    assert prep.main(["copy", "--source", str(src), "--parts", P1, P2]) == 0
    for p in (P1, P2):
        got = sorted(x.name for x in (root / "source" / p).iterdir())
        assert got == [f"{p}.DWG", f"{p}.SLDPRT"]
        assert (root / "source" / p / f"{p}.SLDPRT").read_bytes() == b"sldprt " + p.encode()
    assert _snapshot(src) == before and len(before) == len(files)
    # resumable: a second run skips
    assert prep.main(["copy", "--source", str(src), "--parts", P1]) == 0
    log = [json.loads(x) for x in (root / "prep_log.jsonl").read_text().splitlines()]
    assert [x["status"] for x in log if x["step"] == "copy" and x["part"] == P1] == ["ok", "skipped"]


def test_copy_refuses_missing_or_nested_source(root, tmp_path, capsys):
    assert prep.main(["copy", "--source", str(tmp_path / "missing"), "--parts", P1]) == 2
    assert prep.main(["copy", "--parts", P1]) == 2
    inner = root / "inner"
    inner.mkdir()
    assert prep.main(["copy", "--source", str(inner), "--parts", P1]) == 2
    assert not (root / "source").exists()


def test_copy_failure_is_logged_and_batch_continues(root, tmp_path):
    src = tmp_path / "ds"
    _fake_dataset(src)
    pr = split.pair(P1)
    (src / split.MODEL_ROOT / pr.model).unlink()           # P1's model is missing
    assert prep.main(["copy", "--source", str(src), "--parts", P1, P2]) == 1
    assert (root / "source" / P2 / f"{P2}.SLDPRT").is_file()
    log = [json.loads(x) for x in (root / "prep_log.jsonl").read_text().splitlines()]
    assert {x["part"]: x["status"].split(":")[0] for x in log} == {P1: "failed", P2: "ok"}


def test_keys_check_review_status(root, fakes, capsys):
    assert prep.main(["keys", "--parts", P1, P2]) == 0
    assert fakes == [(P1, "inch"), (P2, "inch")]          # units come from the manifest
    assert prep.main(["check", "--parts", P1, P2]) == 0
    k1, k2 = _load(root, P1), _load(root, P2)
    assert k1.flags == [] and k1.signoff["kind"] == "auto"
    assert [f.kind for f in k2.flags] == ["unexplained_drawing_value"] and not k2.signed
    assert prep.main(["review", "--parts", P1, P2]) == 0
    html = (root / P2 / "review.html").read_text(encoding="utf-8")
    assert "unexplained_drawing_value" in html and "flag 1" in html
    capsys.readouterr()
    assert prep.main(["status", "--parts", P1, P2]) == 0
    out = capsys.readouterr().out
    row1 = next(x for x in out.splitlines() if x.startswith(P1))
    row2 = next(x for x in out.splitlines() if x.startswith(P2))
    assert "auto" in row1 and "human" not in row1
    assert " 1 " in row2 and "-" in row2


def test_check_is_repeatable_and_keeps_resolutions(root, fakes):
    """check regenerates from reference.step, so a re-run cannot stack relabels; resolutions
    a person already wrote for unchanged flags carry over."""
    assert prep.main(["check", "--parts", P2]) == 0
    k = _load(root, P2)
    k.flags[0].resolution = "accepted: title-block width"
    k.save(root / P2 / "key.json")
    assert prep.main(["check", "--parts", P2]) == 0
    k2 = _load(root, P2)
    assert [(f.kind, f.resolution) for f in k2.flags] == [
        ("unexplained_drawing_value", "accepted: title-block width")]


def test_check_keeps_hand_edited_key_unless_forced(root, fakes):
    assert prep.main(["check", "--parts", P2]) == 0
    k = _load(root, P2)
    k.features[0].type = "blind_hole"                       # a reviewer's correction
    k.flags[0].resolution = "fixed key: K001 is blind"
    k.save(root / P2 / "key.json")
    before = (root / P2 / "key.json").read_text(encoding="utf-8")
    assert prep.main(["check", "--parts", P2]) == 0
    assert (root / P2 / "key.json").read_text(encoding="utf-8") == before
    log = [json.loads(x) for x in (root / "prep_log.jsonl").read_text().splitlines()]
    assert log[-1]["status"].startswith("skipped: key.json hand-edited")
    assert prep.main(["check", "--parts", P2, "--force"]) == 0   # regeneration wins
    assert _load(root, P2).features[0].type == "thru_hole"


def test_check_keeps_overrides_and_relinks(root, fakes):
    """A re-check rebuilds the key from keygen; it must keep the person's overrides and
    re-record each feature's drawing links / tolerances (crosscheck.link)."""
    assert prep.main(["check", "--parts", P1]) == 0
    k = _load(root, P1)
    assert all(f.links and f.tol for f in k.features)          # linked on the first check too
    ov = [{"feature": "K001", "attr": "depth", "silent": True, "note": "drawing silent"}]
    k.overrides = ov
    k.save(root / P1 / "key.json")
    assert prep.main(["check", "--parts", P1]) == 0
    k2 = _load(root, P1)
    assert k2.overrides == ov
    assert k2.features[0].links["size"] == [0.344] and k2.features[0].tol["size"] > 0
    assert prep.main(["check", "--parts", P1, "--force"]) == 0
    assert _load(root, P1).overrides == ov


def test_check_drops_overrides_for_vanished_features_and_logs(root, fakes):
    assert prep.main(["check", "--parts", P1]) == 0
    k = _load(root, P1)
    keep = {"feature": "K001", "attr": "depth", "silent": True}
    k.overrides = [keep, {"feature": "K099", "attr": "d", "value": 0.3},
                   {"type": "countersink", "expected_count": 4}, {"drawing_only": "linear 0.375"}]
    k.save(root / P1 / "key.json")
    assert prep.main(["check", "--parts", P1]) == 0
    assert _load(root, P1).overrides == [keep, {"type": "countersink", "expected_count": 4},
                                         {"drawing_only": "linear 0.375"}]
    log = [json.loads(x) for x in (root / "prep_log.jsonl").read_text().splitlines()]
    assert "dropped 1 override" in log[-1]["status"] and "K099" in log[-1]["status"]


def test_crosscheck_relabel_is_idempotent():
    """Belt and braces for the choice above: check() twice on one key gives the same result."""
    k = _key("P")
    k.features[0].d = 0.201
    d = _drawing()
    d.callouts.append(parse(".250-20 TAP THRU"))
    f1 = [(f.kind, f.detail) for f in crosscheck.check(k, d)]
    t1 = [(f.type, f.thread) for f in k.features]
    f2 = [(f.kind, f.detail) for f in crosscheck.check(k, d)]
    assert f1 == f2 and t1 == [(f.type, f.thread) for f in k.features]
    assert t1[0][0] == "tapped_hole"


def test_human_signoff_survives_recheck_unless_forced(root, fakes):
    assert prep.main(["check", "--parts", P2]) == 0
    assert prep.main(["signoff", P2, "--by", "smcanuff"]) == 1            # open flag
    k = _load(root, P2)
    k.flags[0].resolution = "fixed key: nothing to fix"
    k.save(root / P2 / "key.json")
    assert prep.main(["signoff", P2, "--by", "smcanuff"]) == 0
    assert _load(root, P2).signoff["kind"] == "human"
    assert prep.main(["check", "--parts", P2]) == 0
    so = _load(root, P2).signoff
    assert so["kind"] == "human" and so["by"] == "smcanuff"
    log = [json.loads(x) for x in (root / "prep_log.jsonl").read_text().splitlines()]
    assert log[-1]["status"].startswith("skipped")
    assert prep.main(["check", "--parts", P2, "--force"]) == 0
    assert _load(root, P2).signoff is None


def test_signoff_lists_open_flags(root, fakes, capsys):
    assert prep.main(["check", "--parts", P2]) == 0
    capsys.readouterr()
    assert prep.main(["signoff", P2, "--by", "x"]) == 1
    out = capsys.readouterr().out
    assert "flag 1" in out and "unexplained_drawing_value" in out
    assert _load(root, P2).signoff is None


def test_accept_resolves_flags_by_drawing_policy_and_signs(root, fakes, capsys):
    assert prep.main(["check", "--parts", P2]) == 0
    assert prep.main(["accept", "--parts", P2]) == 2              # needs --by
    assert prep.main(["accept", "--parts", P2, "--by", "x"]) == 0
    k = _load(root, P2)
    assert k.signoff["kind"] == "human" and k.signoff["by"] == "x"
    assert k.flags and all(f.resolution.startswith(("drawing-wins:", "drawing-silent:")) for f in k.flags)
    assert any(f.kind == "unexplained_drawing_value" and f.resolution.startswith("drawing-wins:")
               for f in k.flags)
    assert prep.main(["accept", "--parts", P1, "--by", "x"]) == 1   # never checked -> skipped


def test_drawing_wins_resolution_by_kind():
    r = prep.drawing_wins_resolution
    assert r("unexplained_key_value", "d", "x", "2026-10-24").startswith("drawing-silent:")
    assert r("unexplained_position", "d", "x", "2026-10-24").startswith("drawing-silent:")
    for kind in ("unexplained_drawing_value", "count_mismatch", "units_mismatch"):
        assert r(kind, "d", "x", "2026-10-24").startswith("drawing-wins:")


def test_signoff_refuses_unchecked_key(root, fakes, capsys):
    assert prep.main(["keys", "--parts", P1]) == 0
    assert prep.main(["signoff", P1, "--by", "x"]) == 1
    assert "check" in capsys.readouterr().out
    assert _load(root, P1).signoff is None


def test_signoff_unknown_part_or_missing_key(root, capsys):
    assert prep.main(["signoff", "BOGUS", "--by", "x"]) == 2
    assert prep.main(["signoff", P1, "--by", "x"]) == 1


def test_profile_writes_html(root, fakes, tmp_path, monkeypatch, capsys):
    from bench import profile
    assert prep.main(["check", "--parts", P1, P2]) == 0
    src = tmp_path / "ds"
    src.mkdir()
    monkeypatch.setattr(profile, "archive_keyword_counts", lambda d: {"tap": 7})
    capsys.readouterr()
    assert prep.main(["profile", "--source", str(src)]) == 0
    html = (root / "profile.html").read_text(encoding="utf-8")
    assert "thru_hole" in html and "<td>tap</td><td>7</td>" in html
    assert "bias flag" in capsys.readouterr().out


def test_pdf_without_solidworks_exits_3_before_touching_parts(root, monkeypatch, capsys):
    def no_sw(*a, **k):
        raise sw_tasks.SwUnavailable("SolidWorks is not reachable over COM")

    monkeypatch.setattr(sw_tasks, "connect", no_sw)
    called = []
    monkeypatch.setattr(sw_tasks, "dwg_to_pdf", lambda *a: called.append(a))
    assert prep.main(["pdf", "--parts", P1]) == 3
    assert "not reachable" in capsys.readouterr().out
    assert called == [] and list(root.iterdir()) == []


def test_pdf_and_step_with_fake_solidworks(root, monkeypatch):
    for p in (P1, P2):
        s = root / "source" / p
        s.mkdir(parents=True)
        (s / f"{p}.DWG").write_bytes(b"dwg")
        (s / f"{p}.SLDPRT").write_bytes(b"prt")
    app = object()
    monkeypatch.setattr(sw_tasks, "connect", lambda *a, **k: app)

    def pdf(a, dwg, out):
        assert a is app and dwg.name.endswith(".DWG")
        if dwg.parent.name == P1:
            raise RuntimeError("LoadFile4 failed")
        out.write_bytes(b"%PDF")

    def step(a, prt, out_step, out_png):
        out_step.write_text("ISO")

    monkeypatch.setattr(sw_tasks, "dwg_to_pdf", pdf)
    monkeypatch.setattr(sw_tasks, "sldprt_to_step", step)
    assert prep.main(["pdf", "--parts", P1, P2]) == 1          # P1 failed, P2 still done
    assert (root / P2 / "drawing.pdf").is_file() and not (root / P1 / "drawing.pdf").exists()
    assert prep.main(["step", "--parts", P1, P2]) == 0
    assert (root / P1 / "reference.step").is_file()


def test_dxf_needs_oda_converter(root, monkeypatch, capsys):
    monkeypatch.delenv(config.ODA_ENV, raising=False)
    assert prep.main(["dxf", "--parts", P1]) == 2
    assert "ODA_CONVERTER" in capsys.readouterr().out


def test_dxf_with_fake_converter(root, tmp_path, monkeypatch):
    exe = tmp_path / "ODAFileConverter.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv(config.ODA_ENV, str(exe))
    (root / "source" / P1).mkdir(parents=True)
    (root / "source" / P1 / f"{P1}.DWG").write_bytes(b"dwg")
    seen = []

    def convert(dwg, out, cmd=None):
        seen.append((dwg.name, cmd))
        out.write_text("0\nEOF\n")

    monkeypatch.setattr(oda, "convert", convert)
    assert prep.main(["dxf", "--parts", P1]) == 0
    assert seen == [(f"{P1}.DWG", [str(exe)])] and (root / P1 / "drawing.dxf").is_file()


def test_review_renders_drawing_png_from_pdf(root, fakes):
    pymupdf = pytest.importorskip("pymupdf")
    assert prep.main(["check", "--parts", P1]) == 0
    doc = pymupdf.open()
    doc.new_page(width=200, height=100).insert_text((20, 50), "DRAWING")
    doc.save(str(root / P1 / "drawing.pdf"))
    doc.close()
    assert prep.main(["review", "--parts", P1]) == 0
    assert (root / P1 / "drawing.png").read_bytes()[:4] == b"\x89PNG"
    assert "data:image/png;base64," in (root / P1 / "review.html").read_text(encoding="utf-8")


def test_run_step_failure_removes_partial_output(tmp_path):
    def half(part, d):
        (d / "out.txt").write_text("partial")
        raise RuntimeError("crop failed")

    res = prep.run_step("demo", ["A"], tmp_path, lambda d: d / "out.txt", half,
                        tmp_path / "log.jsonl", force=False)
    assert res["A"].startswith("failed") and not (tmp_path / "A" / "out.txt").exists()


def test_run_step_interrupt_removes_output_logs_and_propagates(tmp_path):
    def ctrl_c(part, d):
        (d / "out.txt").write_text("partial")
        raise KeyboardInterrupt

    log = tmp_path / "log.jsonl"
    with pytest.raises(KeyboardInterrupt):
        prep.run_step("demo", ["A", "B"], tmp_path, lambda d: d / "out.txt", ctrl_c, log, force=False)
    assert not (tmp_path / "A" / "out.txt").exists()
    recs = [json.loads(x) for x in log.read_text().splitlines()]
    assert [(r["part"], r["status"].split(":")[0]) for r in recs] == [("A", "failed")]


def test_pdf_partial_write_is_not_left_behind(root, monkeypatch):
    (root / "source" / P1).mkdir(parents=True)
    (root / "source" / P1 / f"{P1}.DWG").write_bytes(b"dwg")
    monkeypatch.setattr(sw_tasks, "connect", lambda *a, **k: object())

    def pdf(app, dwg, out):
        out.write_bytes(b"%PDF half")
        raise ValueError("no drawing content")

    monkeypatch.setattr(sw_tasks, "dwg_to_pdf", pdf)
    assert prep.main(["pdf", "--parts", P1]) == 1
    assert not (root / P1 / "drawing.pdf").exists()


def test_signoff_tolerates_bad_log_line_and_missing_log(root, fakes, capsys):
    assert prep.main(["check", "--parts", P1]) == 0
    log = root / "prep_log.jsonl"
    with open(log, "a", encoding="utf-8") as fh:
        fh.write('{"time": "2026-10-24T0')                   # half-written line
    assert prep.main(["signoff", P1, "--by", "x"]) == 0
    log.unlink()
    capsys.readouterr()
    assert prep.main(["signoff", P1, "--by", "x"]) == 1
    assert "run `check` first" in capsys.readouterr().out
