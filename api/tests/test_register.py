"""Registration onto the contract grid. Headers and images are synthetic: this tests geometry and resampling.

The SIP coefficients have the size found in real SPHEREx headers (several native pixels across a detector),
so a registration that dropped them would fail these tests.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning
from reproject import reproject_interp

from tombaugh.grid import (
    NATIVE_PIXSCALE_ARCSEC,
    PIXSCALE_ARCSEC,
    Grid,
    native_half_window,
    pixel_to_sky,
    sky_to_pixel,
)
from tombaugh.register import celestial_wcs, native_coordinates, register
from tombaugh.types import Cutout, Exposure

ROLLS = (0.0, 90.0, 180.0, 200.0)
TARGET_DETECTOR_XY = (410.3, 1650.7)  # far from the reference pixel, where the distortion is several pixels
SYNTHETIC_SIP = {
    "A_0_0": 0.14,
    "A_0_1": -3.2e-4,
    "A_1_0": 5.5e-4,
    "A_0_2": -1.4e-6,
    "A_1_1": 4.2e-6,
    "A_2_0": -1.6e-6,
    "A_0_3": -6.0e-11,
    "A_1_2": 6.4e-10,
    "A_2_1": -2.0e-10,
    "A_3_0": 5.7e-10,
    "B_0_0": -1.07,
    "B_0_1": -1.2e-3,
    "B_1_0": -6.0e-4,
    "B_0_2": 1.9e-6,
    "B_1_1": -7.3e-7,
    "B_2_0": 6.7e-6,
    "B_0_3": 3.2e-10,
    "B_1_2": -1.4e-10,
    "B_2_1": 6.3e-10,
    "B_3_0": -4.5e-11,
}


def synthetic_header(
    roll_deg: float, *, sip: bool = True, crval: tuple[float, float] = (210.3, 33.7)
) -> fits.Header:
    """A TAN(-SIP) header of a 2040 x 2040 detector with 6.15 arcsec pixels, rolled by ``roll_deg``."""
    scale = NATIVE_PIXSCALE_ARCSEC / 3600.0
    cos_t, sin_t = math.cos(math.radians(roll_deg)), math.sin(math.radians(roll_deg))
    header = fits.Header()
    header["NAXIS"] = 2
    header["NAXIS1"] = 2040
    header["NAXIS2"] = 2040
    header["BUNIT"] = "MJy / sr"
    header["WCSAXES"] = 2
    header["CTYPE1"] = "RA---TAN-SIP" if sip else "RA---TAN"
    header["CTYPE2"] = "DEC--TAN-SIP" if sip else "DEC--TAN"
    header["CRPIX1"] = 1020.5
    header["CRPIX2"] = 1020.5
    header["CRVAL1"] = crval[0]
    header["CRVAL2"] = crval[1]
    header["CUNIT1"] = "deg"
    header["CUNIT2"] = "deg"
    header["CDELT1"] = 1.0
    header["CDELT2"] = 1.0
    header["PC1_1"] = -scale * cos_t
    header["PC1_2"] = scale * sin_t
    header["PC2_1"] = scale * sin_t
    header["PC2_2"] = scale * cos_t
    header["RADESYS"] = "ICRS"
    header["MJD-AVG"] = 61000.5
    header["PSF_FWHM"] = 8.6
    if sip:
        header["A_ORDER"] = 3
        header["B_ORDER"] = 3
        for key, value in SYNTHETIC_SIP.items():
            header[key] = value
    return header


def _text(header: fits.Header) -> str:
    return header.tostring(sep="\n", endcard=False, padding=False)


def _astropy_wcs(header: fits.Header) -> WCS:
    """The reference WCS straight from astropy and the whole header (astropy warns about the MJD cards)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        return WCS(header)


def _scene(roll_deg: float, fov_arcmin: float, *, sip: bool = True, half: int | None = None):
    """A blank synthetic cutout around TARGET_DETECTOR_XY, the grid centred there and the detector WCS."""
    header = synthetic_header(roll_deg, sip=sip)
    wcs = _astropy_wcs(header)
    ra, dec = (float(v) for v in wcs.all_pix2world(*TARGET_DETECTOR_XY, 0))
    grid = Grid.for_field(ra, dec, fov_arcmin)
    half = native_half_window(fov_arcmin) if half is None else half
    x0, y0 = round(TARGET_DETECTOR_XY[0]) - half, round(TARGET_DETECTOR_XY[1]) - half
    synthetic_image = np.zeros((2 * half + 1, 2 * half + 1), dtype=np.float32)
    exposure = Exposure(
        obs_id="synthetic_obs", det=4, mjd=61000.5, collection="synthetic", bucket="b", region="r", key="k"
    )
    cut = Cutout(
        exposure=exposure,
        image=synthetic_image,
        flags=None,
        x0=x0,
        y0=y0,
        wcs_header=_text(header),
        lam=3.0,
        dlam=0.03,
        mjd=61000.5,
        psf_fwhm=8.6,
    )
    return cut, grid, wcs


def _blob(cut: Cutout, wcs: WCS, ra: float, dec: float, sigma_px: float = 1.3) -> np.ndarray:
    """A compact synthetic Gaussian centred on the sky position (ra, dec), drawn in native pixels."""
    x, y = (float(v) for v in wcs.all_world2pix(ra, dec, 0))
    rows, cols = np.indices(cut.image.shape)
    return np.exp(-0.5 * ((cols + cut.x0 - x) ** 2 + (rows + cut.y0 - y) ** 2) / sigma_px**2).astype(
        np.float32
    )


def _centroid(image: np.ndarray, box: int = 10) -> tuple[float, float]:
    """Position (x, y) of a blob: flux-weighted centroid in a box wide enough to hold all of it.

    The brightest pixel is not used as the position: after bilinear resampling it always sits on the centre
    of the brightest NATIVE pixel, which is up to half a native pixel (one output pixel) from the true peak.
    """
    row, col = np.unravel_index(np.nanargmax(image), image.shape)
    r0, r1 = max(row - box, 0), min(row + box + 1, image.shape[0])
    c0, c1 = max(col - box, 0), min(col + box + 1, image.shape[1])
    rows, cols = np.mgrid[r0:r1, c0:c1]
    stamp = np.nan_to_num(image[r0:r1, c0:c1]).astype(np.float64)
    return float((stamp * cols).sum() / stamp.sum()), float((stamp * rows).sum() / stamp.sum())


@pytest.mark.parametrize("roll", ROLLS)
def test_blob_lands_on_its_sky_position_at_every_roll(roll):
    cut, grid, wcs = _scene(roll, 6)
    for x_target, y_target in ((grid.cx, grid.cy), (20.0, 95.0), (101.5, 30.25)):
        ra, dec = pixel_to_sky(grid, x_target, y_target)
        synthetic_sci = _blob(cut, wcs, ra, dec)
        out = register(cut, synthetic_sci, grid)
        assert out.shape == (grid.n, grid.n) and out.dtype == np.float32
        x_expected, y_expected = sky_to_pixel(grid, ra, dec)
        assert (x_expected, y_expected) == pytest.approx((x_target, y_target), abs=1e-6)
        x_measured, y_measured = _centroid(out)
        assert abs(x_measured - x_expected) <= 0.5 and abs(y_measured - y_expected) <= 0.5  # the requirement
        assert math.hypot(x_measured - x_expected, y_measured - y_expected) < 0.05  # what is achieved
        # Surface brightness is preserved: four output pixels per native pixel carry the same mean value.
        assert float(np.nansum(out)) == pytest.approx(4.0 * float(synthetic_sci.sum()), rel=0.03)
        # Interpolation never overshoots the brightest native pixel.
        assert 0.75 < float(np.nanmax(out)) <= float(synthetic_sci.max()) + 1e-6


def test_north_is_up_and_east_is_left():
    cut, grid, wcs = _scene(200.0, 6)
    north_ra, north_dec = pixel_to_sky(grid, grid.cx, grid.cy - 20)  # 61.5 arcsec north of the centre
    assert north_dec == pytest.approx(grid.dec0 + 20 * PIXSCALE_ARCSEC / 3600.0, abs=1e-6)
    x, y = _centroid(register(cut, _blob(cut, wcs, north_ra, north_dec), grid))
    assert (x, y) == pytest.approx((grid.cx, grid.cy - 20), abs=0.05)  # north is towards row 0
    east_ra = grid.ra0 + 15 * PIXSCALE_ARCSEC / 3600.0 / math.cos(math.radians(grid.dec0))
    x, y = _centroid(register(cut, _blob(cut, wcs, east_ra, grid.dec0), grid))
    assert (x, y) == pytest.approx((grid.cx - 15, grid.cy), abs=0.05)  # east is towards column 0


def test_the_sip_terms_matter_and_are_applied():
    cut, grid, wcs = _scene(0.0, 6)
    ra, dec = pixel_to_sky(grid, 40.0, 70.0)
    synthetic_sci = _blob(cut, wcs, ra, dec)
    good = _centroid(register(cut, synthetic_sci, grid))
    assert math.hypot(good[0] - 40.0, good[1] - 70.0) < 0.05
    stripped = synthetic_header(0.0, sip=False)
    cut.wcs_header = _text(stripped)  # the same pixels read through a header without distortion
    wrong = _centroid(register(cut, synthetic_sci, grid))
    assert math.hypot(wrong[0] - 40.0, wrong[1] - 70.0) > 4.0  # several output pixels off


def test_header_without_its_sip_coefficients_is_refused():
    header = synthetic_header(0.0)
    for key in list(SYNTHETIC_SIP) + ["A_ORDER", "B_ORDER"]:
        del header[key]
    with pytest.raises(ValueError):
        celestial_wcs(_text(header))
    with pytest.raises(ValueError):
        celestial_wcs("SIMPLE  =                    T\nBITPIX  =                  -32")
    with_lookup = synthetic_header(0.0)
    with_lookup["CPDIS1"] = "LOOKUP"  # a distortion stored in another HDU: never silently ignored
    with pytest.raises(ValueError):
        celestial_wcs(_text(with_lookup))


def test_header_text_formats_and_extra_cards():
    header = synthetic_header(33.0)
    header["WCSNAMEA"] = (
        "0-based active pixel coordinates"  # alternate systems of the real header: ignored here
    )
    header["CTYPE1A"] = "LINEAR"
    header["CTYPE2A"] = "LINEAR"
    header["CTYPE1W"] = "WAVE-TAB"
    header["CTYPE2W"] = "WAVE-TAB"
    header["PS1_0W"] = "WCS-WAVE"
    reference = _astropy_wcs(synthetic_header(33.0))
    assert reference.sip is not None
    sky = reference.all_pix2world([[5.0, 7.0], [1020.0, 1020.0], [2030.0, 150.0]], 0)
    for text in (_text(header), header.tostring(sep="", endcard=True, padding=True)):
        wcs = celestial_wcs(text)
        assert wcs.sip is not None
        assert np.allclose(wcs.all_world2pix(sky, 0), reference.all_world2pix(sky, 0), atol=1e-9)


@pytest.mark.parametrize("roll", (*ROLLS, 33.0))
def test_lattice_mapping_agrees_with_direct_mapping_over_ten_arcmin(roll):
    cut, grid, _ = _scene(roll, 10)
    assert grid.n == 197
    x_fast, y_fast = native_coordinates(cut, grid)
    x_direct, y_direct = native_coordinates(cut, grid, direct=True)
    assert x_fast.shape == y_fast.shape == (197, 197)
    worst = max(float(np.abs(x_fast - x_direct).max()), float(np.abs(y_fast - y_direct).max()))
    assert worst < 0.02  # the limit of the brief, in native pixels
    assert worst < 1e-6  # what the bicubic lattice actually achieves
    # The whole field lies inside the window at this roll, with the margin the half-window formula promises.
    size = cut.image.shape[0]
    assert x_direct.min() >= 1.0 and y_direct.min() >= 1.0
    assert x_direct.max() <= size - 2.0 and y_direct.max() <= size - 2.0


def test_direct_and_lattice_registration_give_the_same_image():
    cut, grid, _ = _scene(200.0, 10)
    rng = np.random.default_rng(11)
    synthetic_sci = rng.normal(0.0, 1.0, size=cut.image.shape).astype(np.float32)
    fast = register(cut, synthetic_sci, grid)
    direct = register(cut, synthetic_sci, grid, direct=True)
    assert np.array_equal(np.isnan(fast), np.isnan(direct))
    assert np.nanmax(np.abs(fast - direct)) < 1e-4
    small_cut, small_grid, _ = _scene(200.0, 0.4)  # a 9-pixel grid takes the direct path
    assert small_grid.n < 17
    assert register(small_cut, small_cut.image, small_grid).shape == (small_grid.n, small_grid.n)


def test_nan_does_not_spread_and_is_never_counted_as_zero():
    cut, grid, _ = _scene(200.0, 6)
    synthetic_sci = np.full(cut.image.shape, 7.0, dtype=np.float32)
    hole_row, hole_col = 40, 47
    synthetic_sci[hole_row, hole_col] = np.nan
    out = register(cut, synthetic_sci, grid)
    finite = np.isfinite(out)
    assert np.allclose(out[finite], 7.0, atol=1e-5)  # neighbours of the hole are not diluted towards zero
    x, y = native_coordinates(cut, grid, direct=True)
    distance = np.maximum(np.abs(x - hole_col), np.abs(y - hole_row))
    assert np.all(np.isnan(out[distance < 0.25]))  # on the hole: no data
    assert np.all(finite[distance >= 1.0])  # one native pixel away: untouched
    assert 1 <= int((~finite).sum()) <= 9  # one native pixel is at most a few output pixels
    assert int((~finite).sum()) == int(np.isnan(out).sum())  # NaN, never infinity


def test_coverage_threshold_is_one_half():
    cut, grid, _ = _scene(0.0, 6)
    synthetic_sci = np.full(cut.image.shape, 3.0, dtype=np.float32)
    synthetic_sci[:, 50:] = np.nan  # everything right of native column 49.5 is missing
    out = register(cut, synthetic_sci, grid)
    x, _ = native_coordinates(cut, grid, direct=True)
    assert np.all(np.isfinite(out[x < 49.49])) and np.all(np.isnan(out[x > 49.51]))
    assert np.allclose(out[np.isfinite(out)], 3.0, atol=1e-5)


def test_saturated_block_stays_blank():
    cut, grid, wcs = _scene(90.0, 6)
    ra, dec = pixel_to_sky(grid, grid.cx, grid.cy)
    synthetic_sci = 50.0 * _blob(cut, wcs, ra, dec, sigma_px=2.0)
    x, y = (float(v) for v in wcs.all_world2pix(ra, dec, 0))
    col, row = round(x - cut.x0), round(y - cut.y0)
    synthetic_sci[row - 1 : row + 2, col - 1 : col + 2] = np.nan  # a 3 x 3 saturated core
    out = register(cut, synthetic_sci, grid)
    assert np.all(np.isnan(out[grid.cy - 1 : grid.cy + 2, grid.cx - 1 : grid.cx + 2]))  # never filled
    assert np.isfinite(out[grid.cy, grid.cx + 8]) and np.isfinite(out[grid.cy + 8, grid.cx])
    assert 9 <= int(np.isnan(out).sum()) <= 49


def test_outside_the_window_is_nan():
    cut, grid, _ = _scene(200.0, 6, half=12)  # a window much smaller than the field
    out = register(cut, np.ones(cut.image.shape, dtype=np.float32), grid)
    x, y = native_coordinates(cut, grid, direct=True)
    size = cut.image.shape[0]
    inside = (x >= 0.0) & (x <= size - 1.0) & (y >= 0.0) & (y <= size - 1.0)
    assert np.array_equal(np.isfinite(out), inside)
    assert 0.02 < inside.mean() < 0.2 and np.isfinite(out[grid.cy, grid.cx])
    assert np.allclose(out[inside], 1.0, atol=1e-6)
    assert np.all(np.isnan(register(cut, np.full(cut.image.shape, np.nan, dtype=np.float32), grid)))


def test_window_hanging_off_the_detector_keeps_its_offsets():
    cut, grid, wcs = _scene(0.0, 3)
    synthetic_sci = _blob(cut, wcs, grid.ra0, grid.dec0)
    reference = register(cut, synthetic_sci, grid)
    padded = np.full((cut.image.shape[0] + 30, cut.image.shape[1] + 40), np.nan, dtype=np.float32)
    padded[30:, 40:] = (
        synthetic_sci  # the same pixels in a larger window that starts 40 columns and 30 rows earlier
    )
    cut.image, cut.x0, cut.y0 = padded, cut.x0 - 40, cut.y0 - 30
    assert np.array_equal(register(cut, padded, grid), reference, equal_nan=True)


def test_shape_mismatch_is_refused():
    cut, grid, _ = _scene(0.0, 3)
    with pytest.raises(ValueError):
        register(cut, np.zeros((5, 5), dtype=np.float32), grid)


@pytest.mark.parametrize("roll", (0.0, 200.0))
def test_agrees_with_reproject_interp(roll):
    cut, grid, wcs = _scene(roll, 6)
    rows, cols = np.indices(cut.image.shape, dtype=np.float64)
    size = cut.image.shape[0]
    synthetic_sci = (
        2.0
        + 0.01 * cols
        - 0.006 * rows
        + 0.8 * np.sin(cols / 6.0) * np.cos(rows / 9.0)
        + 3.0 * np.exp(-0.5 * ((cols - 0.4 * size) ** 2 + (rows - 0.55 * size) ** 2) / 3.0**2)
    ).astype(np.float32)
    ours = register(cut, synthetic_sci, grid)

    window_wcs = wcs[cut.y0 : cut.y0 + size, cut.x0 : cut.x0 + size]  # the cutout's own WCS, SIP included
    target = WCS(naxis=2)  # a standard north-up TAN image: row 0 is SOUTH, so the result is flipped below
    target.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    target.wcs.crval = [grid.ra0, grid.dec0]
    target.wcs.crpix = [grid.cx + 1.0, grid.cy + 1.0]
    target.wcs.cdelt = [-PIXSCALE_ARCSEC / 3600.0, PIXSCALE_ARCSEC / 3600.0]
    theirs, _ = reproject_interp(
        (synthetic_sci.astype(np.float64), window_wcs), target, shape_out=grid.shape, order="bilinear"
    )
    theirs = theirs[::-1]  # row order matched to the contract: row 0 north

    interior = (slice(4, grid.n - 4), slice(4, grid.n - 4))
    assert np.all(np.isfinite(ours[interior])) and np.all(np.isfinite(theirs[interior]))
    relative = np.abs(ours[interior] / theirs[interior] - 1.0)
    assert float(relative.max()) < 1e-3
    assert float(relative.max()) < 1e-5  # in practice the two agree to float32 rounding
    assert float(np.abs(ours[interior] - theirs[interior][::-1]).max()) > 0.1  # and the flip is not a no-op
