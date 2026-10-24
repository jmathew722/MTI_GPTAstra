"""bench.dxfread: dimensions (shown value, override, scale), callouts, general tolerance."""
import pytest

ezdxf = pytest.importorskip("ezdxf")
from bench.dxfread import read  # noqa: E402


def _dxf(tmp_path, override=None):
    doc = ezdxf.new(setup=True)
    m = doc.modelspace()
    d = m.add_linear_dim(base=(0, 4), p1=(0, 0), p2=(4, 0), dimstyle="EZDXF",
                       override={"dimlfac": 1})
    if override is not None:
        d.dimension.dxf.text = override
    d.render()
    m.add_diameter_dim(center=(1, 1), radius=0.25, angle=45, dimstyle="EZDXF",
                         override={"dimlfac": 1}).render()
    m.add_mtext(".500-13 TAP THRU (3) HLS.")
    m.add_text("DECIMAL DIMENSIONS TO BE:")
    m.add_text(".000 %%P.010")
    m.add_text(".00 %%P.030")
    m.add_text("DIMENSIONS ARE IN INCHES")
    p = tmp_path / "t.dxf"
    doc.saveas(p)
    return p


def test_dimensions_and_callouts(tmp_path):
    dr = read(_dxf(tmp_path))
    kinds = sorted((x.kind, round(x.shown, 4)) for x in dr.dims)
    assert kinds == [("diameter", 0.5), ("linear", 4.0)]
    assert [c.thread for c in dr.callouts] == [".500-13"]
    assert dr.general_tol == {3: 0.010, 2: 0.030}
    assert dr.units_hint == "inch"


def test_override_text_is_what_the_drawing_says(tmp_path):
    dr = read(_dxf(tmp_path, override="4.250"))
    lin = next(x for x in dr.dims if x.kind == "linear")
    assert lin.shown == 4.25 and lin.measured == pytest.approx(4.0) and lin.not_to_scale


def test_decimals_of_shown_text(tmp_path):
    dr = read(_dxf(tmp_path, override="<> TYP."))
    lin = next(x for x in dr.dims if x.kind == "linear")
    assert lin.shown == pytest.approx(4.0) and not lin.not_to_scale and lin.text == "<> TYP."


def test_diameter_dim_is_diameter_not_radius(tmp_path):
    dr = read(_dxf(tmp_path))
    dia = next(x for x in dr.dims if x.kind == "diameter")
    assert dia.measured == pytest.approx(0.5) and dia.shown == pytest.approx(0.5)


def test_rendered_dimension_block_is_not_double_counted(tmp_path):
    dr = read(_dxf(tmp_path))
    assert len(dr.callouts) == 1
    assert len(dr.dims) == 2
    assert len(dr.texts) == 5
