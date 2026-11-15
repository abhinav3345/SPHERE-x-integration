"""Sky grid against the astropy-generated reference vectors (Contract v1.0, section 2)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from tombaugh.grid import (
    ALLOWED_FOV,
    NATIVE_PIXSCALE_ARCSEC,
    PIXSCALE_ARCSEC,
    Grid,
    grid_size,
    native_half_window,
    pixel_centres_sky,
    pixel_to_sky,
    sky_to_pixel,
    snap,
)

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "docs" / "contract" / "vectors" / "grid.json").read_text(
        encoding="utf-8"
    )
)
TOL_PX = VECTORS["tolerance_px"]
TOL_ARCSEC = VECTORS["tolerance_arcsec"]
CASES = [
    pytest.param(g, c, id=f"{g['name']}-{i}") for g in VECTORS["grids"] for i, c in enumerate(g["cases"])
]


def _grid(entry: dict) -> Grid:
    return Grid.for_field(entry["ra0"], entry["dec0"], entry["fov_arcmin"])


def _separation_arcsec(ra1, dec1, ra2, dec2) -> float:
    """Great-circle separation in arcsec (haversine), inputs in degrees."""
    a1, d1, a2, d2 = (math.radians(v) for v in (ra1, dec1, ra2, dec2))
    h = math.sin((d2 - d1) / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin((a2 - a1) / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h)))) * 3600.0


def test_vector_file_is_contract_v1_and_not_empty():
    assert VECTORS["contract"] == "1.0"
    assert len(VECTORS["grids"]) >= 4
    assert len(CASES) >= 60


@pytest.mark.parametrize("entry", VECTORS["grids"], ids=lambda g: g["name"])
def test_grid_geometry_matches_vectors(entry):
    grid = _grid(entry)
    assert (grid.ra0, grid.dec0) == (entry["ra0"], entry["dec0"])
    assert grid.n == entry["nx"] == entry["ny"]
    assert grid.cx == entry["cx"] and grid.cy == entry["cy"]
    assert grid.pixscale == entry["pixscale_arcsec"] == PIXSCALE_ARCSEC
    assert grid.shape == (entry["ny"], entry["nx"])


@pytest.mark.parametrize("entry, case", CASES)
def test_sky_to_pixel_matches_astropy_reference(entry, case):
    x, y = sky_to_pixel(_grid(entry), case["ra"], case["dec"])
    assert abs(x - case["x"]) <= TOL_PX
    assert abs(y - case["y"]) <= TOL_PX


@pytest.mark.parametrize("entry, case", CASES)
def test_pixel_to_sky_matches_astropy_reference(entry, case):
    ra, dec = pixel_to_sky(_grid(entry), case["x"], case["y"])
    assert 0.0 <= ra < 360.0
    assert _separation_arcsec(ra, dec, case["ra"], case["dec"]) <= TOL_ARCSEC


@pytest.mark.parametrize("entry", VECTORS["grids"], ids=lambda g: g["name"])
def test_round_trips(entry):
    grid = _grid(entry)
    xs, ys = np.meshgrid(np.linspace(-6.0, grid.n + 5.0, 23), np.linspace(-6.0, grid.n + 5.0, 19))
    ra, dec = pixel_to_sky(grid, xs, ys)
    x_back, y_back = sky_to_pixel(grid, ra, dec)
    assert np.max(np.abs(x_back - xs)) < 1e-7
    assert np.max(np.abs(y_back - ys)) < 1e-7
    ra_back, dec_back = pixel_to_sky(grid, x_back, y_back)
    dra = (ra_back - ra + 180.0) % 360.0 - 180.0
    assert np.max(np.abs(dra) * np.cos(np.radians(dec))) * 3600.0 < 1e-6
    assert np.max(np.abs(dec_back - dec)) * 3600.0 < 1e-6


@pytest.mark.parametrize("entry", VECTORS["grids"], ids=lambda g: g["name"])
def test_centre_and_orientation(entry):
    grid = _grid(entry)
    assert sky_to_pixel(grid, grid.ra0, grid.dec0) == (grid.cx, grid.cy)
    ra_c, dec_c = pixel_to_sky(grid, grid.cx, grid.cy)
    assert _separation_arcsec(ra_c, dec_c, grid.ra0, grid.dec0) < 1e-9
    # Row 0 is north: straight up from the centre the declination grows and the right ascension stays.
    ra_n, dec_n = pixel_to_sky(grid, grid.cx, 0)
    assert dec_n > grid.dec0
    assert abs((ra_n - grid.ra0 + 180.0) % 360.0 - 180.0) < 1e-9
    assert _separation_arcsec(ra_n, dec_n, grid.ra0, grid.dec0) == pytest.approx(
        grid.cy * PIXSCALE_ARCSEC, rel=1e-5
    )
    # Column 0 is east: right ascension grows towards column 0.
    ra_e, _ = pixel_to_sky(grid, 0, grid.cy)
    assert (ra_e - grid.ra0 + 180.0) % 360.0 - 180.0 > 0.0
    ra_w, _ = pixel_to_sky(grid, grid.n - 1, grid.cy)
    assert (ra_w - grid.ra0 + 180.0) % 360.0 - 180.0 < 0.0


def test_grid_sizes_for_allowed_fields():
    assert ALLOWED_FOV == (3, 4, 5, 6, 8, 10)
    assert [grid_size(f) for f in ALLOWED_FOV] == [59, 79, 99, 119, 157, 197]
    for fov in (0.5, 1, 2, 2.5, 7, 9, 12.3):
        assert grid_size(fov) % 2 == 1
    for bad in (0, -3, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            grid_size(bad)


def test_snap_rounds_to_four_decimals_and_wraps():
    assert snap(133.75991234, -7.24184999) == (133.7599, -7.2418)
    assert snap(269.44620001, 4.76719999) == (269.4462, 4.7672)
    assert snap(359.99996, 10.0) == (0.0, 10.0)
    assert snap(-0.00001, 10.0) == (0.0, 10.0)
    assert snap(-10.5, -90.0) == (349.5, -90.0)
    assert snap(725.25, 0.0) == (5.25, 0.0)
    ra, dec = snap(-0.0, -0.00001)
    assert math.copysign(1.0, ra) == 1.0 and math.copysign(1.0, dec) == 1.0  # no negative zero in cache keys
    assert 0.0 <= snap(359.99995, 0.0)[0] < 360.0
    for bad in ((10.0, 90.5), (10.0, -91.0), (float("nan"), 0.0), (0.0, float("inf"))):
        with pytest.raises(ValueError):
            snap(*bad)


def test_for_field_snaps_the_centre():
    grid = Grid.for_field(133.75991234, -7.24184999, 6)
    assert (grid.ra0, grid.dec0, grid.n, grid.pixscale) == (133.7599, -7.2418, 119, 3.075)
    assert (grid.cx, grid.cy) == (59, 59)
    assert isinstance(grid.cx, int) and isinstance(grid.cy, int)


def test_grid_must_be_odd_and_positive():
    for bad in (0, -1, 118, 2):
        with pytest.raises(ValueError):
            Grid(10.0, 10.0, bad)
    with pytest.raises(ValueError):
        Grid(10.0, 10.0, 119, pixscale=0.0)


def test_scalars_give_floats_and_arrays_give_arrays():
    grid = Grid.for_field(269.4462, 4.7672, 6)
    x, y = sky_to_pixel(grid, 269.45, 4.77)
    assert isinstance(x, float) and isinstance(y, float)
    ra, dec = pixel_to_sky(grid, 10, 20.5)
    assert isinstance(ra, float) and isinstance(dec, float)
    xs, ys = sky_to_pixel(grid, np.array([269.45, 269.44, 269.43]), np.array([4.77, 4.76, 4.75]))
    assert xs.shape == ys.shape == (3,)
    assert (xs[0], ys[0]) == pytest.approx((x, y), abs=1e-12)


def test_pixel_centres_sky_is_indexed_row_then_column():
    grid = Grid.for_field(133.7599, -7.2418, 3)
    ra2d, dec2d = pixel_centres_sky(grid)
    assert ra2d.shape == dec2d.shape == (grid.n, grid.n) == (59, 59)
    for row, col in ((0, 0), (0, 58), (58, 0), (29, 29), (7, 41)):
        ra, dec = pixel_to_sky(grid, col, row)
        assert ra2d[row, col] == pytest.approx(ra, abs=1e-12)
        assert dec2d[row, col] == pytest.approx(dec, abs=1e-12)
    assert np.all(np.diff(dec2d[:, 29]) < 0)  # declination falls down the rows
    assert np.all(np.diff(ra2d[29, :]) < 0)  # right ascension falls along the columns
    assert (ra2d[29, 29], dec2d[29, 29]) == pytest.approx((grid.ra0, grid.dec0), abs=1e-12)


def test_pixel_centres_sky_handles_the_ra_wrap():
    grid = Grid.for_field(0.0003, 20.0, 4)
    ra2d, _ = pixel_centres_sky(grid)
    assert np.all((ra2d >= 0.0) & (ra2d < 360.0))
    assert ra2d[39, 0] < 1.0 and ra2d[39, 78] > 359.0  # east of 0 h on the left, west of it on the right


def test_far_hemisphere_has_no_image():
    grid = Grid.for_field(10.0, 0.0, 6)
    x, y = sky_to_pixel(grid, 190.0, 0.0)
    assert math.isnan(x) and math.isnan(y)
    xs, _ = sky_to_pixel(grid, np.array([10.0, 100.0, 120.0]), np.array([0.0, 0.0, 0.0]))
    assert np.isfinite(xs[0]) and np.isnan(xs[1]) and np.isnan(xs[2])


def test_native_half_window_formula_and_coverage():
    assert [native_half_window(f) for f in ALLOWED_FOV] == [23, 30, 37, 44, 58, 71]
    for fov in ALLOWED_FOV:
        half = native_half_window(fov)
        assert half == math.ceil((fov * 60.0 / 2.0) * math.sqrt(2.0) / NATIVE_PIXSCALE_ARCSEC) + 2
        # The farthest pixel centre (a grid corner) plus one native pixel for the bilinear neighbour and
        # half a pixel for centring the window must lie inside it, whatever the roll angle.
        corner_arcsec = math.hypot(grid_size(fov) // 2, grid_size(fov) // 2) * PIXSCALE_ARCSEC
        assert half >= corner_arcsec / NATIVE_PIXSCALE_ARCSEC + 1.5
    with pytest.raises(ValueError):
        native_half_window(0)
