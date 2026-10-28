"""Structured overrides: convert policy resolutions; apply to an effective key."""
from bench.features import Feature, Flag, Key
from bench.overrides import apply, from_resolutions
from bench.prep import drawing_wins_resolution

SILENT = "drawing-silent: model detail not stated on the drawing; do not score it (...)"
WINS = "drawing-wins: score against the drawing, not the model (...)"


def _key():
    return Key(part="P", units="inch", source="s", envelope=[3, 3, 0.625], features=[
        Feature(id="K004", type="bore", d=0.985, depth=0.22, center=[1.5, 1.5, 0], axis=[0, 0, 1]),
        Feature(id="K005", type="counterbore", d=0.281, depth=0.245, cbore_d=0.4375, cbore_depth=0.044,
                center=[0.5, 0.5, 0.625], axis=[0, 0, 1]),
        Feature(id="K006", type="countersink", d=0.28, csink_d=0.5, center=[2, 2, 0], axis=[0, 0, 1])],
        flags=[Flag("unexplained_key_value", "counterbore cbore_depth=0.0437 not stated", "K005", SILENT),
               Flag("count_mismatch", "callout 'DR. & C'SINK FOR #10 FLAT HD. SCR. 12-HOLES' says 12, key has 8",
                    None, WINS),
               Flag("unexplained_drawing_value", "linear 0.375 (.375) matches no key quantity", None, WINS)])


def test_from_resolutions():
    ov = from_resolutions(_key())
    assert {"feature": "K005", "attr": "depth", "silent": True} in [
        {k: o[k] for k in ("feature", "attr", "silent") if k in o} for o in ov]
    assert any(o.get("type") == "countersink" and o.get("expected_count") == 12 for o in ov)
    assert any(o.get("drawing_only") == "linear 0.375" for o in ov)


def test_apply_value_and_silent_and_counts():
    k = _key()
    k.overrides = [{"feature": "K004", "attr": "depth", "value": 0.098},
                   {"feature": "K005", "attr": "depth", "silent": True},
                   {"type": "countersink", "expected_count": 3}]
    eff = apply(k)
    assert eff.key.feature("K004").depth == 0.098
    assert ("K005", "depth") in eff.silent
    assert eff.expected_counts == {"countersink": 3}
    assert k.feature("K004").depth == 0.22                    # original key untouched


def test_real_resolution_strings_map_by_kind():
    k = _key()
    k.flags = [
        Flag("unexplained_key_value", "counterbore cbore_d=0.5313 not stated on the drawing", "K005",
             drawing_wins_resolution("unexplained_key_value", "x", "me", "2026-10-24")),
        Flag("unexplained_position", "thru_hole at [0.5, 0.5, 0]: coordinate x is not located by any drawing "
             "distance", "K006", drawing_wins_resolution("unexplained_position", "x", "me", "2026-10-24")),
        Flag("unexplained_drawing_value", "bolt circle 3 (callout '.344 DIA. THRU (6) HLS. EQ. SP. ON 3.000 B.C.') "
             "matches no key quantity", None, drawing_wins_resolution("unexplained_drawing_value", "x", "me", "d")),
        Flag("count_mismatch", "callout '1.750-12 TAP THRU' says 1, key has 0", None,
             drawing_wins_resolution("count_mismatch", "x", "me", "d")),
        Flag("count_mismatch", "callout '.500-13 TAP THRU (3) HLS.' says 3, key has 0", None,
             drawing_wins_resolution("count_mismatch", "x", "me", "d")),
        Flag("count_mismatch", "callout '.25 DRILL THRU (4) HLS.' says 4, key has 2", None, None)]   # open
    eff = apply(k)
    assert eff.silent == {("K005", "size"), ("K006", "position")}
    assert eff.drawing_only == ["bolt circle 3"]
    assert eff.expected_counts == {"tapped_hole": 4}          # 1 + 3 called for (open flag ignored)


def test_count_is_the_drawing_count_not_key_plus_shortfall():
    k = _key()      # 1 countersink in the key; the callout describes none of it (size mismatch)
    k.flags = [Flag("count_mismatch", "callout 'C'SINK FOR #10 FLAT HD. SCR. 4 HOLES' says 4, key has 0", None, WINS)]
    assert apply(k).expected_counts == {"countersink": 4}


def test_explicit_override_wins_over_resolution():
    k = _key()
    k.flags = [Flag("unexplained_drawing_value", "linear 0.098 (.098) matches no key quantity", None, WINS),
               Flag("unexplained_key_value", "bore depth=0.2200 not stated", "K004", SILENT)]
    k.overrides = [{"feature": "K004", "attr": "depth", "value": 0.098, "note": "drawing: inner step"}]
    eff = apply(k)
    assert eff.key.feature("K004").depth == 0.098
    assert ("K004", "depth") not in eff.silent               # explicit value beats derived silence
    assert eff.drawing_only == []                             # 0.098 is now tied to K004


def test_explicit_silent_on_key_field_names_the_scored_attr():
    k = _key()
    k.flags = []
    k.overrides = [{"feature": "K005", "attr": "cbore_depth", "silent": True},
                   {"feature": "K006", "attr": "csink_d", "silent": True},
                   {"feature": "K004", "attr": "position", "silent": True}]
    assert apply(k).silent == {("K005", "depth"), ("K006", "size"), ("K004", "position")}


def test_explicit_silent_field_and_derived_silent_collapse():
    k = _key()      # derived: K005 depth silent (cbore_depth flag); explicit names the field
    k.flags = k.flags[:1]
    k.overrides = [{"feature": "K005", "attr": "cbore_depth", "silent": True, "note": "spec example"}]
    assert apply(k).silent == {("K005", "depth")}


def test_value_override_sets_the_key_field_and_beats_derived_silence():
    k = _key()      # derived silence on K005 depth (from the cbore_depth flag)
    k.flags = k.flags[:1]
    k.overrides = [{"feature": "K005", "attr": "cbore_depth", "value": 0.05}]
    eff = apply(k)
    assert eff.key.feature("K005").cbore_depth == 0.05
    assert eff.key.feature("K005").depth == 0.245
    assert ("K005", "depth") not in eff.silent


def test_value_override_on_scored_name_is_rejected():
    import pytest
    for attr in ("size", "position"):
        k = _key()
        k.overrides = [{"feature": "K004", "attr": attr, "value": 1.0}]
        with pytest.raises(ValueError, match="scored attribute"):
            apply(k)


def test_unknown_override_attr_is_rejected():
    import pytest
    k = _key()
    k.overrides = [{"feature": "K004", "attr": "diameter", "silent": True}]
    with pytest.raises(ValueError):
        apply(k)


def test_value_override_on_center_belongs_to_position():
    from bench.overrides import override_attrs, scored_attr
    assert scored_attr("center") == "position"
    k = _key()
    k.flags = [Flag("unexplained_position", "bore at [1.5, 1.5, 0]: x not located", "K004", SILENT)]
    k.overrides = [{"feature": "K004", "attr": "center", "value": [1.4, 1.5, 0]}]
    eff = apply(k)
    assert eff.key.feature("K004").center == [1.4, 1.5, 0]
    assert ("K004", "position") not in eff.silent             # the person's value beats derived silence
    assert override_attrs(k, "K004") == {"position"}


def test_override_attrs_covers_explicit_and_derived():
    from bench.overrides import override_attrs
    k = _key()      # derived: K005 silent depth (cbore_depth flag)
    k.overrides = [{"feature": "K006", "attr": "csink_d", "value": 0.52}]
    assert override_attrs(k, "K005") == {"depth"}
    assert override_attrs(k, "K006") == {"size"}
    assert override_attrs(k, "K004") == set()
