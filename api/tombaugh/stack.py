"""Stacking: registered exposures to one plane per (time bin, wave bin).

Outliers (cosmic rays, satellite trails) are rejected only among exposures of the SAME time bin and detector.
Nothing is ever compared across time bins: that would erase exactly the moving and variable objects the
blink exists to show. Images are surface brightness in MJy/sr on the contract grid; weights are inverse
variances in (MJy/sr)^-2, one scalar per exposure.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from tombaugh.prepare import clipped_stats
from tombaugh.types import Exposure, StackedPlane

REJECT_MIN_EXPOSURES = 6  # a (time bin, detector) group needs this many exposures before anything is rejected
REJECT_NSIGMA = 5.0
REJECT_FRACTIONAL_FLOOR = 0.15  # tolerance for real spectral slope inside a detector, fraction of the median
REJECT_MAX_FRACTION = 0.10  # at most this share of a pixel's samples is rejected
EVENTS_MAX = 255


@dataclass
class Registered:
    """One exposure resampled onto the contract grid."""

    exposure: Exposure
    data: np.ndarray  # float32 (n, n), row 0 north, column 0 east, MJy/sr, NaN = no data
    weight: float  # inverse variance of the exposure, (MJy/sr)^-2
    lam: float  # wavelength at the field centre, micron
    mjd: float  # mid-exposure MJD (UTC), days
    time_bin: int
    wave_bin: int


def _usable(item: Registered) -> bool:
    return math.isfinite(item.weight) and item.weight > 0.0


def _median_over_samples(cube: np.ndarray, finite: np.ndarray) -> np.ndarray:
    """Per-pixel median of the finite samples along axis 0; NaN where a pixel has none."""
    count = finite.sum(axis=0)
    ordered = np.sort(np.where(finite, cube, np.nan), axis=0)  # NaN sorts to the end
    last = cube.shape[0] - 1
    lower = np.clip((count - 1) // 2, 0, last)[None]
    upper = np.clip(count // 2, 0, last)[None]
    median = 0.5 * (
        np.take_along_axis(ordered, lower, axis=0)[0] + np.take_along_axis(ordered, upper, axis=0)[0]
    )
    return np.where(count > 0, median, np.nan)


def reject_outliers(cube: np.ndarray, sigmas: np.ndarray) -> np.ndarray:
    """Boolean mask, shaped like ``cube``, of the samples to reject within one (time bin, detector) group.

    ``cube`` is (m, ny, nx) in MJy/sr with NaN for no data; ``sigmas`` holds the m per-exposure noise values
    in MJy/sr. A sample is a candidate when ``|d - median| > 5 * sqrt(sigma_i^2 + (0.15 * |median|)^2)``.
    Per pixel at most ``floor(0.10 * number of finite samples)`` candidates are rejected, largest deviations
    first, so a pixel needs 10 finite samples before it can lose one.
    """
    cube = np.asarray(cube, dtype=np.float64)
    finite = np.isfinite(cube)
    median = _median_over_samples(cube, finite)
    variance = np.asarray(sigmas, dtype=np.float64)[:, None, None] ** 2
    with np.errstate(invalid="ignore"):
        deviation = np.abs(cube - median)
        threshold = REJECT_NSIGMA * np.sqrt(variance + (REJECT_FRACTIONAL_FLOOR * np.abs(median)) ** 2)
        candidate = finite & (deviation > threshold)
    if not candidate.any():
        return candidate
    cap = np.floor(finite.sum(axis=0) * REJECT_MAX_FRACTION + 1e-9).astype(np.int64)
    rejected = candidate.copy()
    rows, cols = np.nonzero(candidate.sum(axis=0) > cap)
    if rows.size:
        ranked = np.where(candidate[:, rows, cols], deviation[:, rows, cols], -np.inf)
        order = np.argsort(-ranked, axis=0, kind="stable")
        rank = np.empty_like(order)
        np.put_along_axis(rank, order, np.arange(cube.shape[0])[:, None], axis=0)
        rejected[:, rows, cols] = candidate[:, rows, cols] & (rank < cap[rows, cols])
    return rejected


def _mean_plane(members: list[Registered], kept: list[np.ndarray]) -> StackedPlane | None:
    """Inverse-variance weighted mean of the kept samples of one (time bin, wave bin); None without data."""
    shape = members[0].data.shape
    total = np.zeros(shape, dtype=np.float64)
    weight_sum = np.zeros(shape, dtype=np.float64)
    used: list[Registered] = []
    for item, ok in zip(members, kept, strict=True):
        if not ok.any():
            continue
        weight = float(item.weight)
        total += weight * np.where(ok, item.data, 0.0).astype(np.float64)
        weight_sum += weight * ok
        used.append(item)
    if not used:
        return None
    with np.errstate(invalid="ignore", divide="ignore"):
        data = np.where(weight_sum > 0.0, total / weight_sum, np.nan).astype(np.float32)
    _, sigma, n_pixels = clipped_stats(data)
    if n_pixels == 0:
        return None
    weights = np.array([item.weight for item in used], dtype=np.float64)
    mjds = np.array([item.mjd for item in used], dtype=np.float64)
    lams = np.array([item.lam for item in used], dtype=np.float64)
    mjd_min, mjd_max = float(mjds.min()), float(mjds.max())
    return StackedPlane(
        time_bin=int(members[0].time_bin),
        wave_bin=int(members[0].wave_bin),
        data=data,
        n_exposures=len(used),
        sigma=float(sigma),
        lam_eff=float((weights * lams).sum() / weights.sum()),
        mjd_mid=0.5 * (mjd_min + mjd_max),
        mjd_min=mjd_min,
        mjd_max=mjd_max,
    )


def stack_planes(items: Iterable[Registered]) -> tuple[list[StackedPlane], dict[tuple[int, int], np.ndarray]]:
    """Stack registered exposures into planes and count rejected samples.

    Returns ``(planes, events)``. ``planes`` holds one ``StackedPlane`` per (time_bin, wave_bin) that has
    data, sorted by (time_bin, wave_bin). ``events`` maps every (time_bin, detector) present to a uint8
    (ny, nx) array: how many samples were rejected at each pixel (0 everywhere for groups of fewer than 6
    exposures, saturating at 255).

    Exposures with a weight that is not positive are ignored. Each plane is the weighted mean of the finite,
    non-rejected samples; pixels without any sample are NaN. ``sigma`` is 1.4826 x MAD of the finite pixels
    after iterative 3-sigma clipping; ``lam_eff`` is the weight-averaged wavelength; ``mjd_min`` and
    ``mjd_max`` span the contributing exposures and ``mjd_mid`` is their midpoint. The result does not depend
    on the order of ``items``.
    """
    usable = sorted(
        (item for item in items if _usable(item)),
        key=lambda item: (item.time_bin, item.wave_bin, item.mjd, item.exposure.uid),
    )
    if not usable:
        return [], {}
    shape = usable[0].data.shape
    for item in usable:
        if item.data.ndim != 2 or item.data.shape != shape:
            raise ValueError(f"registered images differ in shape: {item.data.shape} and {shape}")

    by_detector: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, item in enumerate(usable):
        by_detector[(int(item.time_bin), int(item.exposure.det))].append(i)

    kept: list[np.ndarray] = [np.zeros(0, dtype=bool)] * len(usable)
    events: dict[tuple[int, int], np.ndarray] = {}
    for key in sorted(by_detector):
        members = by_detector[key]
        cube = np.stack([usable[i].data for i in members])
        finite = np.isfinite(cube)
        if len(members) >= REJECT_MIN_EXPOSURES:
            sigmas = np.array([1.0 / math.sqrt(usable[i].weight) for i in members])
            rejected = reject_outliers(cube, sigmas)
        else:
            rejected = np.zeros(cube.shape, dtype=bool)
        events[key] = np.minimum(rejected.sum(axis=0), EVENTS_MAX).astype(np.uint8)
        for j, i in enumerate(members):
            kept[i] = finite[j] & ~rejected[j]

    by_plane: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, item in enumerate(usable):
        by_plane[(int(item.time_bin), int(item.wave_bin))].append(i)

    planes: list[StackedPlane] = []
    for key in sorted(by_plane):
        members = by_plane[key]
        plane = _mean_plane([usable[i] for i in members], [kept[i] for i in members])
        if plane is not None:
            planes.append(plane)
    return planes, events
