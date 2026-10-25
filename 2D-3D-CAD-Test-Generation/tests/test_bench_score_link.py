"""crosscheck.link records, per key feature attribute, the drawing values that explain it and their tolerance."""
from bench.callouts import parse
from bench.crosscheck import link
from bench.dxfread import Dim, Drawing
from bench.features import Feature, Key


def _key():
    return Key(part="P", units="inch", source="s", envelope=[4.0, 3.0, 0.5], features=[
        Feature(id="K1", type="thru_hole", axis=[0, 0, 1], center=[0.5, 0.5, 0], d=0.344, depth=0.5, thru=True),
        Feature(id="K2", type="thru_hole", axis=[0, 0, 1], center=[3.5, 0.5, 0], d=0.344, depth=0.5, thru=True)])


def _drawing():
    return Drawing(dims=[Dim("linear", 4.0, 4.0, "<>", False, 3), Dim("linear", 0.5, 0.5, "<>", False, 2),
                         Dim("linear", 3.0, 3.0, "<>", False, 3)],
                   callouts=[parse(".344 DIA. THRU (2) HLS.")], general_tol={3: 0.005, 2: 0.01}, units_hint="inch")


def test_link_records_values_and_tolerances():
    k = _key()
    link(k, _drawing())
    f = k.feature("K1")
    assert 0.344 in f.links["size"] and f.tol["size"] == 0.005          # callout .344 = 3 decimals
    # x is located by .50 (2 decimals, +-.01) to the edge and 3.000 (+-.005) to K2: tightest wins
    assert 0.5 in f.links["position"] and 3.0 in f.links["position"]
    assert f.tol["position"] == 0.005
    assert 0.5 in f.links["depth"] and f.tol["depth"] == 0.01           # thru depth = .50 thickness
    assert k.feature("K2").links["position"]                            # 3.0 between holes / 0.5 to edge


def test_link_is_idempotent_and_touches_nothing_else():
    k = _key()
    link(k, _drawing())
    before = k.to_dict()
    link(k, _drawing())
    assert k.to_dict() == before
    assert k.flags == [] and k.signoff is None
    assert [f.type for f in k.features] == ["thru_hole", "thru_hole"]


def test_unlinked_attribute_gets_fallback_tolerance():
    k = _key()
    link(k, Drawing(dims=[], callouts=[], general_tol={}, units_hint="inch"))
    assert k.feature("K1").links == {} and k.feature("K1").tol == {}     # scorer uses fallback_tol


def test_prep_link_keeps_signoff(tmp_path, monkeypatch):
    from bench import dxfread, prep
    monkeypatch.setenv("MTI_BENCH_DATA", str(tmp_path))
    part = "A050381E"
    d = tmp_path / part
    d.mkdir()
    k = _key()
    k.part = part
    k.signoff = {"kind": "human", "by": "x", "date": "2026-10-24"}
    k.save(d / "key.json")
    (d / "drawing.dxf").write_text("", encoding="utf-8")
    monkeypatch.setattr(dxfread, "read", lambda p: _drawing())
    assert prep.main(["link", "--parts", part]) == 0
    k2 = Key.load(d / "key.json")
    assert k2.signoff["kind"] == "human" and k2.feature("K1").links


def test_hand_edited_ignores_links_and_tol():
    from dataclasses import asdict
    from bench.prep import _hand_edited
    raw_key = _key()
    raw = [asdict(f) for f in raw_key.features]
    linked = _key()
    link(linked, _drawing())
    assert not _hand_edited(linked, raw, _key())
    linked.features[0].d = 0.5
    assert _hand_edited(linked, raw, _key())
