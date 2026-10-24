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


def _save(doc, tmp_path, name="u.dxf"):
    p = tmp_path / name
    doc.saveas(p)
    return p


def _linear_doc(override=None, **dimov):
    doc = ezdxf.new(setup=True)
    d = doc.modelspace().add_linear_dim(base=(0, 4), p1=(0, 0), p2=(4, 0), dimstyle="EZDXF",
                                        override={"dimlfac": 1, **dimov})
    if override is not None:
        d.dimension.dxf.text = override
    d.render()
    return doc


def test_ordinate_dims_do_not_crash(tmp_path):
    doc = ezdxf.new(setup=True)
    m = doc.modelspace()
    for dtype in (0, 1):  # 0 = Y-type, 1 = X-type
        m.add_ordinate_dim(feature_location=(3, 2), offset=(1, 1), dtype=dtype, origin=(0, 0),
                           dimstyle="EZDXF", override={"dimlfac": 1}).render()
    dr = read(_save(doc, tmp_path))
    assert sorted(round(d.measured, 4) for d in dr.dims if d.kind == "ordinate") == [2.0, 3.0]


def test_one_bad_dimension_does_not_abort_the_drawing(tmp_path, monkeypatch):
    import bench.dxfread as dx
    real = dx._dim
    calls = []

    def flaky(e):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(e)

    monkeypatch.setattr(dx, "_dim", flaky)
    dr = read(_dxf(tmp_path))
    assert len(dr.dims) == 1 and len(dr.callouts) == 1
    assert any("boom" in w for w in dr.warnings)


@pytest.mark.parametrize("text,expected", [
    ("2X 4.250", 4.25), ("4 PLCS 4.250", 4.25), ("(2) 1.500", 1.5), ("2X 4.250 TYP.", 4.25),
    ("4.250", 4.25), ("%%C.500", 0.5), ("2X \P4.250", 4.25),
])
def test_quantity_prefixes_are_not_the_dimension(tmp_path, text, expected):
    dr = read(_save(_linear_doc(override=text), tmp_path))
    lin = next(x for x in dr.dims if x.kind == "linear")
    assert lin.shown == pytest.approx(expected)


def test_decimals_come_from_dimdec_when_not_overridden(tmp_path):
    dr = read(_save(_linear_doc(dimdec=3), tmp_path))
    assert next(x for x in dr.dims).decimals == 3
    dr = read(_save(_linear_doc(override="4.25", dimdec=3), tmp_path))
    assert next(x for x in dr.dims).decimals == 2


def test_dimlfac_scales_shown_value(tmp_path):
    dr = read(_save(_linear_doc(dimlfac=2), tmp_path))
    lin = next(x for x in dr.dims)
    assert lin.shown == pytest.approx(8.0) and lin.measured == pytest.approx(8.0)


def test_dimlfac_not_applied_to_angular(tmp_path):
    doc = ezdxf.new(setup=True)
    doc.modelspace().add_angular_dim_cra(center=(0, 0), radius=2, start_angle=0, end_angle=90,
                                         distance=3, dimstyle="EZDXF",
                                         override={"dimlfac": 2}).render()
    dr = read(_save(doc, tmp_path))
    ang = next(x for x in dr.dims if x.kind == "angular")
    assert ang.measured == pytest.approx(90.0)


def _units(tmp_path, *lines):
    doc = ezdxf.new(setup=True)
    for t in lines:
        doc.modelspace().add_text(t)
    return read(_save(doc, tmp_path)).units_hint


def test_units_hint_word_boundaries_and_precedence(tmp_path):
    assert _units(tmp_path, "DIMENSIONS ARE IN INCHES") == "inch"
    assert _units(tmp_path, "ALL DIMENSIONS IN MM") == "mm"
    assert _units(tmp_path, "MILLIMETERS") == "mm"
    assert _units(tmp_path, "PINCHER", "COMMON") is None
    assert _units(tmp_path, "REF 25.4 MILLIMETERS", "DIMENSIONS ARE IN INCHES") == "inch"
    assert _units(tmp_path, "INCH", "MM") is None


def test_missing_file_propagates(tmp_path):
    with pytest.raises(FileNotFoundError):
        read(tmp_path / "nope.dxf")


def test_garbage_file_is_unreadable_value_error(tmp_path):
    p = tmp_path / "bad.dxf"
    p.write_bytes(b"this is not a dxf file at all\n" * 5)
    with pytest.raises(ValueError, match="unreadable DXF"):
        read(p)


def test_damaged_file_is_recovered_with_warning(tmp_path):
    p = _dxf(tmp_path)
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    # drop the trailing "0 / EOF" marker: strict reading fails, ezdxf.recover succeeds
    p.write_text(chr(10).join(lines[:-2]), encoding="utf-8")
    with pytest.raises(ezdxf.DXFStructureError):
        ezdxf.readfile(str(p))
    dr = read(p)
    assert dr.warnings and len(dr.dims) == 2
