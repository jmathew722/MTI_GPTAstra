"""bench.profile: counts per split, shares, bias flags, HTML."""
from bench.features import Feature, Key
from bench.profile import archive_keyword_counts, bias_flags, plan_type_counts, render_html, type_counts


def _k(part, types):
    return Key(part=part, units="inch", source="s", envelope=[1, 1, 1],
               features=[Feature(id=f"K{i}", type=t) for i, t in enumerate(types)])


def test_counts_and_flags():
    dev = [_k("D1", ["tapped_hole", "tapped_hole", "chamfer"])]
    held = [_k("H1", ["tapped_hole", "counterbore", "thru_hole", "thru_hole", "chamfer"])]
    cd, ch = type_counts(dev), type_counts(held)
    assert cd == {"tapped_hole": 2, "chamfer": 1}
    assert ch["thru_hole"] == 2
    flags = bias_flags(cd, ch, threshold=0.30)
    assert any("tapped_hole" in f and "30%" in f for f in flags)          # 3 of 8 = 37.5%
    assert any("counterbore" in f and "dev" in f for f in flags)          # in held-out, absent from dev


def test_hole_pattern_groups_excluded_from_shares():
    dev = {"hole_pattern": 10, "thru_hole": 1}
    held = {"thru_hole": 1}
    flags = bias_flags(dev, held, threshold=0.30)
    assert not any(f.startswith("hole_pattern") and "of all features" in f for f in flags)
    assert any(f.startswith("thru_hole") and "of all features" in f for f in flags)  # 2 of 2
    html = render_html(dev, held, {}, {}, flags)
    assert "hole_pattern (groups)" in html


def test_plan_type_counts_maps_ir_kinds():
    plan = {"features": [
        {"kind": "revolve", "status": "planned"},
        {"kind": "hole", "status": "planned", "spec": {"type": "cbore"}},
        {"kind": "hole", "status": "planned", "spec": {"type": "tapped"}},
        {"kind": "edge_op", "status": "planned", "operation": "chamfer"},
        {"kind": "edge_op", "status": "unresolved", "operation": "fillet"},
        {"kind": "pattern", "status": "planned", "count": "4"},
        {"kind": "prism", "status": "planned", "op": "cut"},
    ]}
    assert plan_type_counts(plan) == {"turned_diameter": 1, "counterbore": 1, "tapped_hole": 1,
                                      "chamfer": 1, "hole_pattern": 1, "pocket_step": 1}


def test_archive_keyword_counts(tmp_path):
    (tmp_path / "a.dwg").write_bytes(b"\x00\x01...1/4-20 TAP THRU...\x00")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.DWG").write_bytes(b"\x02..DR. & C'BORE..\x00")
    (tmp_path / "c.txt").write_bytes(b"TAP SLOT")
    c = archive_keyword_counts(tmp_path)
    assert c == {"tap": 1, "thru/drill": 2, "counterbore": 1}


def test_html_mentions_every_type():
    html = render_html({"tapped_hole": 2}, {"thru_hole": 1}, {"chamfer": 3}, {"tap": 10}, ["flag x"])
    for s in ("tapped_hole", "thru_hole", "chamfer", "flag x", "approximate"):
        assert s in html
