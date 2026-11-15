"""Stacking and outlier rejection. Arrays are synthetic noise fields used to test the arithmetic."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tombaugh.stack import Registered, reject_outliers, stack_planes
from tombaugh.types import Exposure, StackedPlane

N = 15  # pixels a side
NOISE = 0.01  # MJy/sr per exposure
WEIGHT = 1.0 / NOISE**2


def _item(
    data, *, det=6, time_bin=0, wave_bin=None, weight=WEIGHT, lam=4.5, mjd=61000.0, tag=0
) -> Registered:
    exposure = Exposure(
        obs_id=f"synthetic_{tag:04d}",
        det=det,
        mjd=mjd,
        collection="synthetic",
        bucket="b",
        region="r",
        key="k",
    )
    wave_bin = (det - 1) * 4 if wave_bin is None else wave_bin
    return Registered(
        exposure=exposure,
        data=np.asarray(data, dtype=np.float32),
        weight=weight,
        lam=lam,
        mjd=mjd,
        time_bin=time_bin,
        wave_bin=wave_bin,
    )


def _synthetic_group(count, *, level=1.0, seed=0, **kwargs) -> list[Registered]:
    rng = np.random.default_rng(seed)
    return [
        _item(
            level + rng.normal(0.0, NOISE, size=(N, N)), mjd=61000.0 + 0.1 * i, tag=1000 * seed + i, **kwargs
        )
        for i in range(count)
    ]


def test_weighted_mean_and_plane_metadata():
    synthetic_a = np.full((N, N), 1.0)
    synthetic_b = np.full((N, N), 2.0)
    items = [
        _item(synthetic_a, weight=1.0, lam=4.42, mjd=61000.0, tag=1),
        _item(synthetic_b, weight=3.0, lam=4.50, mjd=61004.0, tag=2),
    ]
    planes, events = stack_planes(items)
    assert len(planes) == 1
    plane = planes[0]
    assert isinstance(plane, StackedPlane)
    assert (plane.time_bin, plane.wave_bin, plane.n_exposures) == (0, 20, 2)
    assert plane.data.dtype == np.float32 and plane.data.shape == (N, N)
    assert np.allclose(plane.data, 1.75)  # (1 * 1 + 3 * 2) / 4
    assert plane.lam_eff == pytest.approx((1.0 * 4.42 + 3.0 * 4.50) / 4.0)
    assert (plane.mjd_min, plane.mjd_max, plane.mjd_mid) == (61000.0, 61004.0, 61002.0)
    assert plane.sigma == 0.0
    assert list(events) == [(0, 6)]
    assert events[(0, 6)].dtype == np.uint8 and events[(0, 6)].shape == (N, N) and not events[(0, 6)].any()


def test_pixels_use_whatever_samples_are_finite():
    synthetic_a = np.full((N, N), 1.0)
    synthetic_b = np.full((N, N), 2.0)
    synthetic_a[0, 0] = np.nan
    synthetic_a[1, 1] = np.nan
    synthetic_b[1, 1] = np.nan
    planes, _ = stack_planes([_item(synthetic_a, weight=1.0, tag=1), _item(synthetic_b, weight=3.0, tag=2)])
    data = planes[0].data
    assert data[0, 0] == 2.0  # only the second exposure saw this pixel
    assert np.isnan(data[1, 1])  # nobody did: no data, never zero
    assert data[5, 5] == pytest.approx(1.75)
    assert int(np.isnan(data).sum()) == 1


def test_planes_are_sorted_and_independent_of_input_order():
    items = []
    for time_bin in (0, 1, 2):
        for det, wave_bin in ((1, 0), (1, 3), (6, 20), (6, 23)):
            items += _synthetic_group(
                7, seed=100 * time_bin + wave_bin, det=det, time_bin=time_bin, wave_bin=wave_bin
            )
    planes, events = stack_planes(items)
    keys = [(p.time_bin, p.wave_bin) for p in planes]
    assert keys == sorted(keys) and len(keys) == 12
    assert sorted(events) == [(t, d) for t in (0, 1, 2) for d in (1, 6)]
    shuffled = [items[i] for i in np.random.default_rng(1).permutation(len(items))]
    planes_again, events_again = stack_planes(shuffled)
    assert [(p.time_bin, p.wave_bin) for p in planes_again] == keys
    for first, second in zip(planes, planes_again, strict=True):
        assert np.array_equal(first.data, second.data, equal_nan=True)
        assert (first.sigma, first.lam_eff, first.mjd_mid, first.n_exposures) == (
            second.sigma,
            second.lam_eff,
            second.mjd_mid,
            second.n_exposures,
        )
    assert all(np.array_equal(events[k], events_again[k]) for k in events)


def test_a_cosmic_ray_is_rejected_in_a_group_of_twelve():
    items = _synthetic_group(12)
    items[4].data[3, 7] += 2.0  # 200 sigma in one exposure
    planes, events = stack_planes(items)
    assert events[(0, 6)][3, 7] == 1 and int(events[(0, 6)].sum()) == 1
    others = np.mean([item.data[3, 7] for i, item in enumerate(items) if i != 4])
    assert planes[0].data[3, 7] == pytest.approx(others, abs=1e-6)
    assert abs(planes[0].data[3, 7] - 1.0) < 5 * NOISE / math.sqrt(11)
    assert planes[0].n_exposures == 12  # the exposure still contributes everywhere else


def test_no_rejection_below_six_exposures():
    items = _synthetic_group(5)
    items[2].data[3, 7] += 2.0
    planes, events = stack_planes(items)
    assert not events[(0, 6)].any()
    assert planes[0].data[3, 7] == pytest.approx(1.0 + 2.0 / 5.0, abs=0.02)  # the hit is still in the mean


@pytest.mark.parametrize("count, expected_rejections", [(6, 0), (9, 0), (10, 1), (19, 1), (20, 2)])
def test_at_most_ten_percent_of_a_pixels_samples_are_rejected(count, expected_rejections):
    items = _synthetic_group(count)
    hits = (5.0, 4.0, 3.0, 2.5)  # four exposures hit the same pixel, by different amounts
    for i, amount in enumerate(hits):
        items[i].data[8, 8] += amount
    planes, events = stack_planes(items)
    assert int(events[(0, 6)][8, 8]) == expected_rejections
    assert int(events[(0, 6)].sum()) == expected_rejections
    kept = [item.data[8, 8] for item in items[expected_rejections:]]  # the largest deviations go first
    assert planes[0].data[8, 8] == pytest.approx(float(np.mean(kept)), abs=1e-5)


def test_cap_counts_finite_samples_per_pixel():
    items = _synthetic_group(12)
    items[0].data[2, 2] += 3.0
    for item in items[6:]:
        item.data[2, 2] = np.nan  # only 6 finite samples at this pixel: floor(0.6) = 0 rejections
    items[1].data[9, 9] += 3.0  # 12 finite samples here: one rejection
    _, events = stack_planes(items)
    assert events[(0, 6)][2, 2] == 0 and events[(0, 6)][9, 9] == 1


def test_fifteen_percent_floor_tolerates_real_spectral_slope():
    rng = np.random.default_rng(3)
    synthetic_cube = 100.0 + rng.normal(0.0, 0.01, size=(12, N, N))
    synthetic_cube[0, 4, 4] = 110.0  # 1000 sigma of noise but only 10 percent of the signal: kept
    synthetic_cube[1, 6, 6] = 200.0  # twice the signal: rejected
    synthetic_cube[2, 8, 8] = 10.0  # a dropout to a tenth of the signal: rejected
    rejected = reject_outliers(synthetic_cube, np.full(12, 0.01))
    assert not rejected[0, 4, 4]
    assert rejected[1, 6, 6] and rejected[2, 8, 8]
    assert int(rejected.sum()) == 2
    threshold = 5.0 * math.sqrt(0.01**2 + (0.15 * 100.0) ** 2)  # 75 MJy/sr: 5 x 15 percent of the median
    assert 10.0 < threshold < 90.0


def test_threshold_uses_each_exposures_own_noise():
    rng = np.random.default_rng(4)
    sigmas = np.array([0.01] * 11 + [0.2])
    synthetic_cube = rng.normal(0.0, 1.0, size=(12, N, N)) * sigmas[:, None, None]
    synthetic_cube[3, 5, 5] = 0.5  # 50 sigma for a quiet exposure
    synthetic_cube[11, 6, 6] = 0.5  # 2.5 sigma for the noisy one
    rejected = reject_outliers(synthetic_cube, sigmas)
    assert rejected[3, 5, 5] and not rejected[11, 6, 6]
    assert int(rejected.sum()) == 1


def test_rejection_runs_per_detector_across_its_wave_bins():
    items = []
    for wave_bin in (20, 21, 22, 23):  # three exposures in each of the four bins of detector 6
        items += _synthetic_group(3, seed=wave_bin, det=6, wave_bin=wave_bin)
    items[0].data[1, 1] += 2.0
    planes, events = stack_planes(items)
    assert [p.wave_bin for p in planes] == [20, 21, 22, 23] and all(p.n_exposures == 3 for p in planes)
    assert list(events) == [(0, 6)] and events[(0, 6)][1, 1] == 1
    assert abs(planes[0].data[1, 1] - 1.0) < 0.05  # mean of the two samples that are left
    # The same twelve exposures spread over two detectors are two groups of six: nothing can be rejected.
    for item in items[6:]:
        item.exposure = Exposure(
            obs_id=item.exposure.obs_id,
            det=5,
            mjd=item.mjd,
            collection="synthetic",
            bucket="b",
            region="r",
            key="k",
        )
    _, events = stack_planes(items)
    assert sorted(events) == [(0, 5), (0, 6)] and not any(e.any() for e in events.values())


def test_nothing_is_rejected_across_time_bins():
    # A moving source: at pixel (4, 4) throughout a long visit, at (4, 9) in a short later visit of three
    # exposures (WISE 0855 has two such short visits).
    long_visit = _synthetic_group(27, level=0.0, seed=1, time_bin=0)
    short_visit = _synthetic_group(3, level=0.0, seed=2, time_bin=1)
    for item in long_visit:
        item.data[4, 4] += 5.0
    for item in short_visit:
        item.data[4, 9] += 5.0
    planes, events = stack_planes(long_visit + short_visit)
    assert [(p.time_bin, p.wave_bin, p.n_exposures) for p in planes] == [(0, 20, 27), (1, 20, 3)]
    assert planes[0].data[4, 4] == pytest.approx(5.0, abs=0.02) and abs(planes[0].data[4, 9]) < 0.02
    assert planes[1].data[4, 9] == pytest.approx(5.0, abs=0.03) and abs(planes[1].data[4, 4]) < 0.03
    assert not events[(0, 6)].any() and not events[(1, 6)].any()
    # Had the 30 exposures been compared as one group, the three samples of the short visit would all have
    # been thrown out at the mover's new position: the source would vanish from that frame.
    merged = np.stack([item.data for item in long_visit + short_visit])
    as_one_group = reject_outliers(merged, np.full(30, NOISE))
    assert as_one_group[27:, 4, 9].all() and not as_one_group[:27, 4, 9].any()


def test_noise_of_the_plane_is_robust():
    items = _synthetic_group(16, level=0.0)
    for item in items:
        item.data[7, 7] += 40.0  # a star in every exposure
        item.data[2:4, 2:4] += 15.0
    planes, _ = stack_planes(items)
    assert planes[0].sigma == pytest.approx(NOISE / math.sqrt(16), rel=0.15)
    assert planes[0].sigma < 0.1 * float(
        np.std(planes[0].data)
    )  # a plain standard deviation would see the stars


def test_exposures_without_weight_or_data_do_not_count():
    good = _synthetic_group(3)
    weightless = [
        _item(np.full((N, N), 50.0), weight=w, tag=90 + i) for i, w in enumerate((0.0, -1.0, float("nan")))
    ]
    blank = _item(np.full((N, N), np.nan), tag=99)
    planes, _ = stack_planes(good + weightless + [blank])
    assert len(planes) == 1 and planes[0].n_exposures == 3
    assert abs(float(np.mean(planes[0].data)) - 1.0) < 0.01
    assert planes[0].mjd_max == max(item.mjd for item in good)
    only_blank, blank_events = stack_planes([_item(np.full((N, N), np.nan), det=2, time_bin=3, tag=5)])
    assert only_blank == [] and list(blank_events) == [(3, 2)]  # a plane without data is not shipped
    assert stack_planes([]) == ([], {})
    assert stack_planes(weightless) == ([], {})


def test_shapes_must_agree():
    with pytest.raises(ValueError):
        stack_planes([_item(np.zeros((N, N)), tag=1), _item(np.zeros((N, N + 2)), tag=2)])


def test_events_saturate_at_255():
    synthetic_cube = np.zeros((3000, 1, 2))
    synthetic_cube[:290, 0, 0] = 9.0  # 290 of 3000 samples deviate at one pixel: under the 10 percent cap
    rejected = reject_outliers(synthetic_cube, np.full(3000, NOISE))
    assert int(rejected[:, 0, 0].sum()) == 290 and int(rejected[:, 0, 1].sum()) == 0
    _, events = stack_planes([_item(synthetic_cube[i], tag=i) for i in range(3000)])
    assert events[(0, 6)].dtype == np.uint8 and events[(0, 6)].tolist() == [[255, 0]]


@pytest.mark.parametrize(
    ("with_feature", "true_mean", "stacked"),
    [
        (1, 2.25, 1.0),  # 1 of 18 exposures: the feature is rejected in full
        (2, 3.5, 8.0 / 3.0),  # 2 of 18: one of the two samples is rejected, the plane reads low
    ],
)
def test_a_feature_few_exposures_of_a_detector_see_is_rejected_as_the_manifest_says(
    with_feature, true_mean, stacked
):
    """The known cost of comparing all exposures of a detector, which see a source at different wavelengths:
    a spectral feature present in one in ten of them or fewer is taken for an outlier. The manifest says so
    in its provenance (`build.NOTE_REJECTION`); whether to reject within one wave bin instead, where small
    groups could then reject nothing, is the science owner's decision. This test pins what the note says."""
    synthetic_continuum, synthetic_feature = 1.0, 6.0
    items = []
    for wave_bin, count in ((20, 5), (21, 5), (22, 4), (23, 4)):  # 18 exposures of detector 6
        for i in range(count):
            synthetic_data = np.full((N, N), synthetic_continuum)
            if wave_bin == 22 and i < with_feature:
                synthetic_data[7, 7] = synthetic_feature  # an emission line that only this wave bin sees
            items.append(
                _item(synthetic_data, det=6, wave_bin=wave_bin, mjd=61000.0 + i, tag=100 * wave_bin + i)
            )
    planes, events = stack_planes(items)
    plane = next(p for p in planes if p.wave_bin == 22)
    assert int(events[(0, 6)][7, 7]) == 1  # floor(0.10 * 18): one sample per pixel may go
    assert plane.data[7, 7] == pytest.approx(stacked) and stacked < true_mean
    assert plane.data[3, 3] == pytest.approx(synthetic_continuum)
