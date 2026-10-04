"""Feature IR v2, Task 6: SolidWorks compiler, the parts that run on any OS.

The COM build itself is verified live (ir_build.py --solidworks; all 5 golden plans
match the CadQuery reference feature by feature, 2026-10-04). These tests pin the
plane-map math measured on that SW 2025 template.
"""
import pytest

from pipeline.ir.compile_solidworks import PlaneMap

# Measured by probe_plane_map on the SW 2025 SP5 template (Z-up): Front = model YZ, +X normal.
SW2025 = PlaneMap({
    "Front Plane": ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
    "Top Plane": ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
    "Right Plane": ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
})


def test_ir_frame_is_the_front_sketch():
    assert SW2025.to_model((1.0, 2.0, 3.0)) == (3.0, 1.0, 2.0)   # IR z = Front normal = model X


@pytest.mark.parametrize("axis, plane, sign", [("Z", "Front Plane", 1), ("Y", "Top Plane", 1),
                                               ("X", "Right Plane", 1)])
def test_plane_for_each_ir_axis(axis, plane, sign):
    assert SW2025.plane_for_ir_axis(axis) == (plane, sign)


def test_revolve_profile_point_lands_in_the_top_sketch():
    # IR (r=2, y=0, z=5) on the Top plane: sketch u = model Y = r, v = -model X = -z
    m = SW2025.to_model((2.0, 0.0, 5.0))
    assert SW2025.sketch_coords("Top Plane", m) == (2.0, -5.0)
