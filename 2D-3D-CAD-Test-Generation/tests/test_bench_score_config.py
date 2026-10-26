"""Scorer config + data-model additions (tol, links, overrides)."""
from bench.features import Feature, Key
from bench.score_config import load


def test_defaults_load_and_are_sane():
    c = load()
    assert c.credit.drop == 0.5 and 4.0 < c.credit.k < 5.0
    assert abs(sum(c.shares.values()) - 1.0) < 1e-9
    assert c.tiers["base_body"] == 10 and c.tiers["thru_hole"] == 5 and c.tiers["tapped_hole"] == 2
    assert c.size_floor == 0.5 and c.extra_penalty == 0.5
    assert c.fallback_tol == {"inch": 0.005, "mm": 0.1}
    assert "countersink" in c.unsupported_types


def test_override_file(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("credit: {drop: 0.6}\n", encoding="utf-8")
    c = load(p)
    assert c.credit.drop == 0.6 and c.tiers["base_body"] == 10     # unspecified keys keep defaults


def test_feature_and_key_new_fields_roundtrip(tmp_path):
    f = Feature(id="K1", type="thru_hole", d=0.25, tol={"size": 0.005}, links={"size": [0.25]})
    k = Key(part="P", units="inch", source="s", envelope=[1, 1, 1], features=[f],
            overrides=[{"feature": "K1", "attr": "depth", "silent": True}])
    k.save(tmp_path / "k.json")
    assert Key.load(tmp_path / "k.json") == k


def test_old_key_without_new_fields_still_loads(tmp_path):
    import json
    d = {"part": "P", "units": "inch", "source": "s", "envelope": [1, 1, 1],
         "features": [{"id": "K1", "type": "thru_hole"}], "flags": [], "signoff": None, "version": 1}
    (tmp_path / "k.json").write_text(json.dumps(d), encoding="utf-8")
    k = Key.load(tmp_path / "k.json")
    assert k.overrides == [] and k.features[0].tol == {} and k.features[0].links == {}
