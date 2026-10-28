"""bench.review: one-page review sheet per part."""
import base64

from bench.features import Feature, Flag, Key
from bench.review import render

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def test_review_html():
    k = Key(part="P9", units="inch", source="reference.step", envelope=[1, 2, 3],
            features=[Feature(id="K001", type="thru_hole", d=0.25, center=[0.5, 0.5, 0], axis=[0, 0, 1])],
            flags=[Flag("count_mismatch", "says 3, key has 4")])
    html = render(k, drawing_png=None, model_png=None)
    for s in ("P9", "K001", "thru_hole", "count_mismatch", "says 3, key has 4", "not signed"):
        assert s in html


def _key():
    holes = [Feature(id=f"K00{i}", type="thru_hole", d=0.25, center=[float(i), 0.5, 0.0], axis=[0, 0, 1])
             for i in (1, 2, 3)]
    pat = Feature(id="K004", type="hole_pattern", members=["K001", "K002", "K003"],
                  pattern={"mode": "line", "pitch": 1.0, "count": 3})
    return Key(part="P1", units="inch", source="reference.step", envelope=[4.0, 1.0, 0.5],
               features=holes + [pat],
               flags=[Flag("count_mismatch", "a", "K001"),
                      Flag("unexplained_drawing_value", "b < c", resolution="accepted: title block"),
                      Flag("units_mismatch", "c")])


def test_pattern_rows_show_members_and_pattern():
    html = render(_key(), None, None)
    assert "K001, K002, K003" in html
    assert "mode=line" in html and "pitch=1" in html and "count=3" in html


def test_flags_have_stable_one_based_indices_and_escape():
    html = render(_key(), None, None)
    i1, i2, i3 = (html.index(f"flag {n}") for n in (1, 2, 3))
    assert i1 < i2 < i3
    assert "b &lt; c" in html and "accepted: title block" in html
    assert "2 open" in html          # 2 of 3 flags have no resolution


def test_signed_key_and_images(tmp_path):
    k = _key()
    k.signoff = {"kind": "human", "by": "smcanuff", "date": "2026-10-24"}
    png = tmp_path / "d.png"
    png.write_bytes(PNG_1PX)
    html = render(k, drawing_png=png, model_png=tmp_path / "missing.png")
    assert "not signed" not in html and "human" in html and "smcanuff" in html
    assert "data:image/png;base64," in html and "no image" in html
