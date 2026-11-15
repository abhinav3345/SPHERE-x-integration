"""Per-exposure preparation. All arrays are synthetic noise fields used to test the arithmetic."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tombaugh import prepare as P
from tombaugh.prepare import (
    MASK_BKG,
    MASK_PHOT,
    MASK_STACK,
    Prepared,
    bit_mask,
    clipped_stats,
    core_mask,
    estimate_background,
    hole_mask,
    prepare,
    ring_mask,
    spike_mask,
    spill_mask,
)
from tombaugh.types import Cutout, Exposure

HALF = 24
SIZE = 2 * HALF + 1
LEVEL = 0.42  # MJy/sr, a zodiacal-light-like pedestal
NOISE = 0.01  # MJy/sr


def _cutout(image, flags=None, **extra) -> Cutout:
    exposure = Exposure(
        obs_id="synthetic_obs", det=6, mjd=61000.0, collection="synthetic", bucket="b", region="r", key="k"
    )
    return Cutout(
        exposure=exposure,
        image=image,
        flags=flags,
        x0=100,
        y0=200,
        wcs_header="",
        lam=4.5,
        dlam=0.04,
        mjd=61000.0,
        psf_fwhm=8.5,
        **extra,
    )


def _synthetic_sky(seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (LEVEL + rng.normal(0.0, NOISE, size=(SIZE, SIZE))).astype(np.float32)


def _no_flags() -> np.ndarray:
    return np.zeros((SIZE, SIZE), dtype=np.int32)


def test_mask_values_and_bit_numbers():
    assert (MASK_STACK, MASK_PHOT, MASK_BKG) == (0x3FD2CEC5, 0x3C028E44, 0x3C2A8E47)
    assert P.FLAG_BITS == {
        "TRANSIENT": 0,
        "OVERFLOW": 1,
        "SUR_ERROR": 2,
        "NONFUNC": 6,
        "DICHROIC": 7,
        "MISSING_DATA": 9,
        "HOT": 10,
        "COLD": 11,
        "NONLINEAR": 15,
        "PERSIST": 17,
        "OUTLIER": 19,
        "SOURCE": 21,
        "BLOOM": 26,
        "SNOWBALL": 27,
        "HALO": 28,
        "SATELLITE_HALO": 29,
    }
    for name, number in P.FLAG_BITS.items():
        assert getattr(P, name) == number
    assert bit_mask() == 0 and bit_mask(0, 1, 26) == 0x4000003


def test_source_is_never_a_reason_to_reject_from_a_stack():
    assert MASK_STACK & bit_mask(P.SOURCE) == 0
    assert MASK_PHOT & bit_mask(P.SOURCE) == 0
    assert MASK_BKG & bit_mask(P.SOURCE) != 0  # but sources are kept out of the background sample
    assert MASK_PHOT & ~MASK_BKG == 0
    for name in (
        "TRANSIENT",
        "SUR_ERROR",
        "NONFUNC",
        "DICHROIC",
        "MISSING_DATA",
        "HOT",
        "COLD",
        "NONLINEAR",
        "PERSIST",
        "BLOOM",
        "SNOWBALL",
        "HALO",
        "SATELLITE_HALO",
    ):
        assert MASK_STACK & bit_mask(P.FLAG_BITS[name]), name
    assert MASK_STACK & bit_mask(P.OVERFLOW) == 0  # a saturated core is handled by the core rule, not blanked


def test_clipped_stats():
    rng = np.random.default_rng(5)
    synthetic_values = rng.normal(3.0, 0.2, size=4000)
    synthetic_values[:60] = 50.0  # outliers
    synthetic_values[60:70] = np.nan
    median, sigma, kept = clipped_stats(synthetic_values)
    assert median == pytest.approx(3.0, abs=0.02)
    assert sigma == pytest.approx(0.2, rel=0.1)
    assert 3800 < kept < 3931
    assert clipped_stats([])[2] == 0 and math.isnan(clipped_stats([np.nan, np.inf])[0])
    assert clipped_stats([7.0, 7.0, 7.0, 7.0]) == (7.0, 0.0, 4)


def test_ring_is_everything_beyond_60_percent_of_the_half_width():
    ring = ring_mask((SIZE, SIZE))
    rows, cols = np.indices((SIZE, SIZE))
    radius = np.hypot(cols - HALF, rows - HALF)
    assert np.array_equal(ring, radius > 0.6 * HALF)
    assert not ring[HALF, HALF] and not ring[HALF, HALF + 14] and ring[HALF, HALF + 15]
    assert ring[0, 0] and ring[0, HALF] and ring[SIZE - 1, SIZE - 1]
    assert not ring.flags.writeable


def test_background_is_the_clipped_median_of_the_clean_ring():
    synthetic_image = _synthetic_sky()
    rows, cols = np.indices(synthetic_image.shape)
    synthetic_image += (5.0 * np.exp(-0.5 * ((cols - HALF) ** 2 + (rows - HALF) ** 2) / 2.0**2)).astype(
        np.float32
    )
    result = prepare(_cutout(synthetic_image, _no_flags(), sky_var=NOISE**2))
    assert isinstance(result, Prepared)
    n_ring = int(ring_mask(synthetic_image.shape).sum())
    assert result.background == pytest.approx(LEVEL, abs=5 * NOISE / math.sqrt(n_ring))
    assert result.sci.dtype == np.float32 and result.sci.shape == synthetic_image.shape
    assert np.allclose(result.sci, synthetic_image.astype(np.float64) - result.background, atol=1e-6)
    assert result.sci[HALF, HALF] == pytest.approx(5.0, abs=0.05)  # the source survives, on a zero background
    assert abs(float(np.median(result.sci[ring_mask(synthetic_image.shape)]))) < 0.002


def test_only_the_ring_sets_the_background():
    synthetic_image = _synthetic_sky()
    reference = prepare(_cutout(synthetic_image.copy(), _no_flags())).background
    inner = ~ring_mask(synthetic_image.shape)
    synthetic_image[inner] += 3.0  # an extended bright object filling the inner 60 percent
    assert prepare(_cutout(synthetic_image, _no_flags())).background == reference


def test_flagged_ring_pixels_do_not_enter_the_background():
    synthetic_image = _synthetic_sky()
    flags = _no_flags()
    reference = prepare(_cutout(synthetic_image.copy(), flags.copy())).background
    ring_rows, ring_cols = np.nonzero(ring_mask(synthetic_image.shape))
    pick = np.random.default_rng(2).choice(ring_rows.size, size=ring_rows.size // 4, replace=False)
    synthetic_image[ring_rows[pick], ring_cols[pick]] += 0.5  # a quarter of the ring is stars...
    flags[ring_rows[pick], ring_cols[pick]] = bit_mask(P.SOURCE)  # ...and flagged as such
    flagged = prepare(_cutout(synthetic_image, flags))
    assert flagged.background == pytest.approx(reference, abs=0.002)
    assert np.all(np.isfinite(flagged.sci))  # SOURCE pixels are kept in the image
    for bit in (P.TRANSIENT, P.OVERFLOW, P.HOT, P.OUTLIER, P.SNOWBALL):
        other = _no_flags()
        other[ring_rows[pick], ring_cols[pick]] = bit_mask(bit)
        assert prepare(_cutout(synthetic_image, other)).background == pytest.approx(reference, abs=0.002)


def test_crowded_ring_falls_back_to_the_25th_percentile():
    synthetic_image = _synthetic_sky()
    flags = _no_flags()
    ring = ring_mask(synthetic_image.shape)
    ring_rows, ring_cols = np.nonzero(ring)
    rng = np.random.default_rng(4)
    crowded = rng.choice(ring_rows.size, size=int(0.75 * ring_rows.size), replace=False)
    synthetic_image[ring_rows[crowded], ring_cols[crowded]] += rng.exponential(0.3, size=crowded.size).astype(
        np.float32
    )
    flags[ring_rows[crowded], ring_cols[crowded]] = bit_mask(P.SOURCE)
    hot = crowded[:25]
    synthetic_image[ring_rows[hot], ring_cols[hot]] = 900.0
    flags[ring_rows[hot], ring_cols[hot]] |= bit_mask(P.HOT)
    usable = ring & ((flags & P.MASK_HARD) == 0)
    expected = float(np.percentile(synthetic_image[usable].astype(np.float64), 25.0))
    result = prepare(_cutout(synthetic_image, flags))
    assert result.background == pytest.approx(expected, abs=1e-6)
    assert (
        LEVEL - 3 * NOISE < result.background < LEVEL + 0.1
    )  # near the sky, far below the median of the stars
    assert result.background < float(np.median(synthetic_image[usable]))
    # With 31 percent of the ring clean the clipped median is used again.
    flags[
        ring_rows[crowded[: int(0.07 * ring_rows.size)]], ring_cols[crowded[: int(0.07 * ring_rows.size)]]
    ] = 0
    clean = ring & ((flags & MASK_BKG) == 0)
    assert clean.sum() >= 0.3 * ring.sum()
    assert prepare(_cutout(synthetic_image, flags)).background == pytest.approx(
        clipped_stats(synthetic_image[clean])[0]
    )


def test_without_flags_the_clipped_median_of_the_ring_is_used():
    synthetic_image = _synthetic_sky()
    synthetic_image[2, 3] = 80.0  # a cosmic ray in the ring: clipped
    synthetic_image[5:9, 40:44] = np.nan
    result = prepare(_cutout(synthetic_image, None, sky_var=NOISE**2))
    ring = ring_mask(synthetic_image.shape)
    assert result.background == pytest.approx(clipped_stats(synthetic_image[ring])[0])
    assert result.background == pytest.approx(LEVEL, abs=0.002)
    assert result.n_saturated == 0
    assert np.array_equal(np.isnan(result.sci), np.isnan(synthetic_image))  # nothing rejected, nothing filled


def test_zodi_level_is_only_the_last_resort():
    synthetic_image = _synthetic_sky()
    assert prepare(_cutout(synthetic_image.copy(), _no_flags(), zodi_level=99.0)).background == pytest.approx(
        LEVEL, abs=0.002
    )
    synthetic_image[ring_mask(synthetic_image.shape)] = np.nan  # the ring fell off the detector
    assert prepare(_cutout(synthetic_image.copy(), _no_flags(), zodi_level=0.4)).background == 0.4
    no_zodi = prepare(_cutout(synthetic_image.copy(), _no_flags()))
    assert no_zodi.background == pytest.approx(LEVEL, abs=0.005)  # the finite pixels that are left
    assert no_zodi.weight == 0.0  # no variance and no ring: the exposure cannot be weighed
    empty = prepare(_cutout(np.full((SIZE, SIZE), np.nan, dtype=np.float32), _no_flags()))
    assert math.isnan(empty.background) and empty.weight == 0.0 and np.all(np.isnan(empty.sci))


def test_ring_of_hard_defects_counts_as_empty():
    synthetic_image = _synthetic_sky()
    flags = _no_flags()
    flags[ring_mask(synthetic_image.shape)] = bit_mask(P.NONFUNC)
    background, variance = estimate_background(synthetic_image, flags, zodi_level=0.37)
    assert background == 0.37 and math.isnan(variance)


def test_strict_mask_away_from_any_core():
    synthetic_image = _synthetic_sky()
    flags = _no_flags()
    rejected_bits = [
        P.TRANSIENT,
        P.SUR_ERROR,
        P.NONFUNC,
        P.DICHROIC,
        P.MISSING_DATA,
        P.HOT,
        P.COLD,
        P.NONLINEAR,
        P.PERSIST,
        P.SNOWBALL,
        P.HALO,
        P.SATELLITE_HALO,
    ]
    kept_bits = [P.SOURCE, P.OUTLIER, 12]
    for i, bit in enumerate(rejected_bits):
        flags[HALF, 4 + 2 * i] = bit_mask(bit)
    for i, bit in enumerate(kept_bits):
        flags[HALF + 5, 4 + 2 * i] = bit_mask(bit)
    flags[HALF + 9, 10] = bit_mask(P.SOURCE, P.HOT)
    result = prepare(_cutout(synthetic_image, flags))
    for i in range(len(rejected_bits)):
        assert np.isnan(result.sci[HALF, 4 + 2 * i]), rejected_bits[i]
        assert np.isfinite(result.sci[HALF, 5 + 2 * i])  # the neighbour is untouched
    for i in range(len(kept_bits)):
        assert np.isfinite(result.sci[HALF + 5, 4 + 2 * i]), kept_bits[i]
    assert np.isnan(result.sci[HALF + 9, 10])
    assert result.n_saturated == 0
    assert int(np.isnan(result.sci).sum()) == len(rejected_bits) + 1


def test_saturated_core_rule_keeps_a_bright_star():
    synthetic_image = _synthetic_sky()
    rows, cols = np.indices(synthetic_image.shape)
    synthetic_image += (400.0 * np.exp(-0.5 * ((cols - HALF) ** 2 + (rows - HALF) ** 2) / 1.6**2)).astype(
        np.float32
    )
    flags = _no_flags()
    near = np.hypot(cols - HALF, rows - HALF) <= 4.5
    flags[near] = bit_mask(P.TRANSIENT, P.SUR_ERROR, P.HALO, P.SOURCE)  # what a strict mask would erase
    flags[HALF, HALF] |= bit_mask(P.OVERFLOW)
    flags[HALF, HALF + 1] |= bit_mask(P.BLOOM)
    flags[HALF + 2, HALF] |= bit_mask(P.HOT)  # a real defect right next to the core
    synthetic_image[HALF + 1, HALF] = np.nan  # blank, touching the OVERFLOW pixel: part of the core
    synthetic_image[HALF + 10, HALF + 10] = np.nan  # blank, far from any flagged pixel: not core
    result = prepare(_cutout(synthetic_image, flags))

    core = core_mask(synthetic_image, flags.astype(np.int64))
    assert sorted(zip(*np.nonzero(core))) == [(HALF, HALF), (HALF, HALF + 1), (HALF + 1, HALF)]
    assert result.n_saturated == 3
    distance = np.min([np.hypot(cols - c, rows - r) for r, c in zip(*np.nonzero(core))], axis=0)
    kept_zone = near & (distance <= 3.0)
    kept_zone[HALF + 2, HALF] = False
    kept_zone[HALF + 1, HALF] = False
    assert kept_zone.sum() > 25
    assert np.all(
        np.isfinite(result.sci[kept_zone])
    )  # TRANSIENT, SUR_ERROR, BLOOM, HALO waived near the core
    assert np.all(np.isnan(result.sci[near & (distance > 3.0)]))  # strict again beyond 3 pixels
    assert np.isnan(result.sci[HALF + 2, HALF])  # HOT is never waived
    assert np.isnan(result.sci[HALF + 1, HALF]) and np.isnan(
        result.sci[HALF + 10, HALF + 10]
    )  # NaN is never filled
    assert result.sci[HALF, HALF] == pytest.approx(
        400.0 + LEVEL - result.background, abs=0.1
    )  # the peak is kept


def test_core_distance_is_euclidean_three_pixels():
    synthetic_image = _synthetic_sky()
    flags = np.full((SIZE, SIZE), bit_mask(P.TRANSIENT), dtype=np.int32)
    flags[HALF, HALF] |= bit_mask(P.OVERFLOW)
    result = prepare(_cutout(synthetic_image, flags))
    rows, cols = np.indices(synthetic_image.shape)
    assert np.array_equal(np.isfinite(result.sci), np.hypot(cols - HALF, rows - HALF) <= 3.0)
    assert np.isfinite(result.sci[HALF, HALF + 3]) and np.isnan(result.sci[HALF + 1, HALF + 3])
    assert int(np.isfinite(result.sci).sum()) == 29
    assert result.n_saturated == 1


def test_weight_from_the_variance_image_or_else_from_the_ring():
    synthetic_image = _synthetic_sky()
    assert prepare(_cutout(synthetic_image, _no_flags(), sky_var=2.5e-4)).weight == pytest.approx(4000.0)
    from_ring = [
        prepare(_cutout(synthetic_image, _no_flags(), sky_var=v)).weight
        for v in (None, 0.0, -1.0, float("nan"))
    ]
    assert len(set(from_ring)) == 1
    assert from_ring[0] == pytest.approx(1.0 / NOISE**2, rel=0.15)
    assert prepare(_cutout(synthetic_image, None)).weight == pytest.approx(1.0 / NOISE**2, rel=0.15)


def test_input_is_not_modified_and_shapes_are_checked():
    synthetic_image = _synthetic_sky()
    flags = _no_flags()
    flags[3, 3] = bit_mask(P.HOT)
    image_before, flags_before = synthetic_image.copy(), flags.copy()
    result = prepare(_cutout(synthetic_image, flags))
    assert np.array_equal(synthetic_image, image_before) and np.array_equal(flags, flags_before)
    assert result.sci is not synthetic_image
    with pytest.raises(ValueError):
        prepare(_cutout(synthetic_image, np.zeros((SIZE, SIZE + 1), dtype=np.int32)))
    with pytest.raises(ValueError):
        prepare(_cutout(synthetic_image.ravel(), None))


def test_flags_of_other_integer_types_work():
    synthetic_image = _synthetic_sky()
    for dtype in (np.int32, np.uint32, np.int64):
        flags = np.zeros((SIZE, SIZE), dtype=dtype)
        flags[7, 7] = bit_mask(P.SATELLITE_HALO)
        assert np.isnan(prepare(_cutout(synthetic_image, flags)).sci[7, 7])


# ------------------------------------------------------------------ pixels the flags miss
def _blanked(result: Prepared) -> list[tuple[int, int]]:
    """(row, column) of every NaN pixel of a prepared image."""
    return sorted((int(r), int(c)) for r, c in zip(*np.nonzero(np.isnan(result.sci)), strict=True))


def _block(row: int, col: int) -> list[tuple[int, int]]:
    """The 3 x 3 block of pixels centred on (row, col)."""
    return sorted((row + dr, col + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1))


@pytest.mark.parametrize(
    "bits",
    [
        (),
        (P.OUTLIER,),
        (P.OVERFLOW,),
        (P.OVERFLOW, P.TRANSIENT),
        (P.OVERFLOW, P.SUR_ERROR),
        (P.BLOOM,),
        (P.SOURCE,),
    ],
)
def test_a_pixel_far_below_the_sky_is_blanked_whatever_its_flags(bits):
    """Real exposures hold pixels thousands of sigma below the sky (-1445 MJy/sr and deeper) that carry no
    bit of the stack mask. Before the hole rule every one of these flag sets kept such a pixel."""
    synthetic_image = _synthetic_sky()
    synthetic_image[10, 30] = LEVEL - 1445.0
    flags = _no_flags()
    flags[10, 30] = bit_mask(*bits)
    result = prepare(_cutout(synthetic_image, flags, sky_var=NOISE**2))
    assert _blanked(result) == _block(10, 30)  # the hole and the eight neighbours that share its charge
    assert result.background == pytest.approx(LEVEL, abs=0.002)
    assert float(np.nanmin(result.sci)) > -6 * NOISE


def test_holes_are_found_at_ten_sigma_next_to_each_other_and_without_flags():
    synthetic_image = _synthetic_sky()
    synthetic_image[10, 30] = LEVEL - 14 * NOISE  # shallow, but nothing in the sky is 14 sigma dark
    synthetic_image[40, 8] = LEVEL - 300 * NOISE  # two holes side by side: each still stands out
    synthetic_image[40, 9] = LEVEL - 200 * NOISE
    synthetic_image[30, 20] = LEVEL - 7 * NOISE  # within the noise tail the rule tolerates: kept
    expected = sorted(set(_block(10, 30)) | set(_block(40, 8)) | set(_block(40, 9)))
    assert _blanked(prepare(_cutout(synthetic_image, _no_flags(), sky_var=NOISE**2))) == expected
    assert _blanked(prepare(_cutout(synthetic_image, None, sky_var=NOISE**2))) == expected  # no flags needed
    at_the_edge = _synthetic_sky()
    at_the_edge[0, 0] = LEVEL - 50 * NOISE
    assert _blanked(prepare(_cutout(at_the_edge, _no_flags(), sky_var=NOISE**2))) == [
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
    ]


def test_a_hole_with_no_valid_neighbour_is_blanked():
    synthetic_sci = np.full((5, 5), np.nan, dtype=np.float32)
    synthetic_sci[2, 2] = -1.0
    assert hole_mask(synthetic_sci, NOISE)[2, 2]
    synthetic_sci[2, 2] = -0.05  # 5 sigma: not a hole
    assert not hole_mask(synthetic_sci, NOISE).any()


def test_a_background_that_is_dark_as_a_whole_is_not_a_hole():
    """Exposures near the 1.083 micron helium line slope by tens of sigma across the window: the constant
    background leaves half of them far below zero. Those pixels are sky, badly modelled, not defects."""
    rows, _ = np.indices((SIZE, SIZE), dtype=np.float64)
    synthetic_slope = (80.0 * NOISE) * (rows - HALF) / HALF  # -80 to +80 sigma from top to bottom
    synthetic_image = _synthetic_sky() + synthetic_slope.astype(np.float32)
    result = prepare(_cutout(synthetic_image, _no_flags(), sky_var=NOISE**2))
    assert int((result.sci < -10 * NOISE).sum()) > 900  # far below the sky, and many
    assert np.all(np.isfinite(result.sci))  # none of them blanked
    synthetic_image[5, 40] -= 30 * NOISE  # a real hole inside the dark half is still found
    assert _blanked(prepare(_cutout(synthetic_image, _no_flags(), sky_var=NOISE**2))) == _block(5, 40)


def test_a_lone_spike_off_any_source_is_blanked():
    synthetic_image = _synthetic_sky()
    synthetic_image[12, 12] += 121 * NOISE  # a hot pixel seen in real exposures: 121 sigma, neighbours at 1
    synthetic_image[30, 40] += 30 * NOISE
    synthetic_image[44, 20] += 12 * NOISE  # below 15 sigma: left to the comparison between exposures
    flags = _no_flags()
    flags[12, 12] = bit_mask(P.OUTLIER)  # the archive's own outlier bit is not in MASK_STACK
    result = prepare(_cutout(synthetic_image, flags, sky_var=NOISE**2))
    assert _blanked(result) == [(12, 12), (30, 40)]  # the spikes alone: their neighbours hold sky
    flags[12, 12] |= bit_mask(P.SOURCE)
    flags[30, 40] = bit_mask(P.SOURCE)
    assert _blanked(prepare(_cutout(synthetic_image, flags, sky_var=NOISE**2))) == []  # catalogued: kept
    assert _blanked(prepare(_cutout(synthetic_image, None, sky_var=NOISE**2))) == []  # no flags: not judged


def test_a_point_source_is_never_a_spike():
    """The sharpest point-spread function in the headers is 7.4 arcsec wide (1.2 native pixels). Even
    centred on a pixel, where it is sharpest, a source leaves more than 5 percent of its peak next door."""
    sigma_px = 7.4 / 6.15 / 2.3548
    rows, cols = np.indices((SIZE, SIZE), dtype=np.float64)
    for peak in (20.0, 60.0, 500.0, 20000.0):  # in units of the noise
        for row0, col0 in ((20.0, 20.0), (20.5, 20.0), (20.5, 20.5), (20.3, 20.1)):
            synthetic_star = np.exp(-0.5 * ((rows - row0) ** 2 + (cols - col0) ** 2) / sigma_px**2)
            synthetic_image = _synthetic_sky() + (peak * NOISE * synthetic_star).astype(np.float32)
            result = prepare(_cutout(synthetic_image, _no_flags(), sky_var=NOISE**2))
            assert np.all(np.isfinite(result.sci)), (peak, row0, col0)


def test_a_spike_is_judged_only_with_four_valid_neighbours():
    synthetic_image = _synthetic_sky()
    synthetic_image[0, 10] += 50 * NOISE  # on the edge of the window
    synthetic_image[30, 30] += 50 * NOISE  # next to a missing pixel
    synthetic_image[30, 31] = np.nan
    synthetic_image[45, 45] += 50 * NOISE  # next to a rejected pixel
    flags = _no_flags()
    flags[44, 45] = bit_mask(P.HOT)
    result = prepare(_cutout(synthetic_image, flags, sky_var=NOISE**2))
    assert _blanked(result) == [(30, 31), (44, 45)]
    synthetic_sci = np.zeros((5, 5), dtype=np.float32)
    synthetic_sci[2, 2] = 1.0
    assert (
        spike_mask(synthetic_sci, np.zeros((5, 5), dtype=np.int64), NOISE).tolist()
        == (np.arange(25).reshape(5, 5) == 12).tolist()
    )
    synthetic_sci[2, 3] = 0.06  # one neighbour holds 6 percent of it: a source can do that
    assert not spike_mask(synthetic_sci, np.zeros((5, 5), dtype=np.int64), NOISE).any()


def test_the_neighbours_of_a_very_bright_rejected_pixel_are_blanked():
    """Seen in a real exposure: a PERSIST pixel 3,235 sigma above the sky and, around it, four pixels at
    11 to 15 sigma that carry only the OUTLIER bit. Stacked alone they drew a ring as bright as the target."""
    synthetic_image = _synthetic_sky()
    flags = _no_flags()
    synthetic_image[20, 20] += 3235 * NOISE
    flags[20, 20] = bit_mask(P.PERSIST, P.OUTLIER)
    for row, col in ((19, 20), (21, 20), (20, 19), (20, 21)):
        synthetic_image[row, col] += 14 * NOISE
        flags[row, col] = bit_mask(P.OUTLIER)
    synthetic_image[40, 40] += 60 * NOISE  # rejected and bright, but under 100 sigma: nothing spills
    flags[40, 40] = bit_mask(P.HOT)
    result = prepare(_cutout(synthetic_image, flags, sky_var=NOISE**2))
    assert _blanked(result) == [(19, 20), (20, 19), (20, 20), (20, 21), (21, 20), (40, 40)]

    flags[20, 20] |= bit_mask(P.SOURCE)  # on a catalogued source the neighbours hold starlight: kept
    assert _blanked(prepare(_cutout(synthetic_image, flags, sky_var=NOISE**2))) == [(20, 20), (40, 40)]


def test_nothing_spills_next_to_a_saturated_core():
    synthetic_image = _synthetic_sky()
    flags = _no_flags()
    synthetic_image[20, 20] += 5000 * NOISE
    flags[20, 20] = bit_mask(P.OVERFLOW)  # a saturated core: kept, and lenient for 3 pixels around
    synthetic_image[20, 22] += 400 * NOISE
    flags[20, 22] = bit_mask(P.PERSIST)  # rejected, bright, 2 pixels from the core
    synthetic_image[20, 23] += 100 * NOISE  # its neighbours are part of the bright star
    synthetic_image[20, 21] += 900 * NOISE
    result = prepare(_cutout(synthetic_image, flags, sky_var=NOISE**2))
    assert _blanked(result) == [(20, 22)]
    assert result.n_saturated == 1
    core = core_mask(synthetic_image, flags.astype(np.int64))
    rejected = np.zeros((SIZE, SIZE), dtype=bool)
    rejected[20, 22] = True
    assert not spill_mask(result.sci, flags.astype(np.int64), rejected, core, NOISE).any()


def test_without_a_known_noise_only_the_flags_reject():
    synthetic_image = _synthetic_sky()
    synthetic_image[ring_mask(synthetic_image.shape)] = np.nan  # no ring and no variance: weight 0.0
    synthetic_image[HALF, HALF] = LEVEL - 1445.0
    synthetic_image[HALF + 4, HALF] = LEVEL + 1445.0
    result = prepare(_cutout(synthetic_image, _no_flags()))
    assert result.weight == 0.0
    assert np.array_equal(np.isnan(result.sci), np.isnan(synthetic_image))
