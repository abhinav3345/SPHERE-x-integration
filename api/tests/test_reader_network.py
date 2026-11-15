"""Live checks of discovery and the reader against IRSA and the public bucket.

Deselected by default (pyproject: -m 'not network'). Run by hand, from the `api` folder:

    uv run pytest -q -m network tests/test_reader_network.py -s
"""

from __future__ import annotations

import itertools
import time

import numpy as np
import pytest

from tombaugh import discovery, http
from tombaugh import remote_fits as rf
from tombaugh.types import Exposure

pytestmark = [pytest.mark.network, pytest.mark.filterwarnings("ignore::astropy.wcs.FITSFixedWarning")]

RA, DEC = 133.7599, -7.2418  # the contract's example field
HALF_PX = 20
DETECTOR_RANGES = {
    1: (0.73, 1.13),
    2: (1.08, 1.67),
    3: (1.61, 2.44),
    4: (2.39, 3.87),
    5: (3.79, 4.45),
    6: (4.40, 5.03),
}


def count_visits(exposures: list[Exposure], gap_days: float = 20.0) -> int:
    """Number of groups of exposures separated by more than `gap_days` (exposures sorted by time)."""
    times = [exposure.mjd for exposure in exposures]
    return 1 + sum(1 for earlier, later in itertools.pairwise(times) if later - earlier > gap_days)


@pytest.fixture(scope="module")
def exposures() -> list[Exposure]:
    before, started = http.stats(), time.perf_counter()
    found = discovery.discover(RA, DEC, deadline=http.Deadline(120.0))
    took, after = time.perf_counter() - started, http.stats()
    print(
        f"\ndiscover: {len(found)} exposures in {count_visits(found)} visits, {took:.2f} s, "
        f"{after['requests'] - before['requests']} requests, {after['retries'] - before['retries']} retries"
    )
    return found


def test_discover_finds_the_example_field(exposures: list[Exposure]) -> None:
    assert len(exposures) >= 200
    assert count_visits(exposures) >= 3
    assert len({exposure.uid for exposure in exposures}) == len(exposures)
    assert [(e.mjd, e.det) for e in exposures] == sorted((e.mjd, e.det) for e in exposures)
    assert {exposure.det for exposure in exposures} == {1, 2, 3, 4, 5, 6}
    assert {exposure.collection for exposure in exposures} <= set(discovery.COLLECTIONS)
    for exposure in exposures:
        assert http.check_url(exposure.url) == "nasa-irsa-spherex.s3.us-east-1.amazonaws.com"


def timed_read(exposures: list[Exposure], label: str) -> tuple[list, list]:
    before, started = http.stats(), time.perf_counter()
    cutouts, failures = rf.read_windows(exposures, RA, DEC, HALF_PX, deadline=http.Deadline(120.0))
    took, after = time.perf_counter() - started, http.stats()
    requests = after["requests"] - before["requests"]
    print(
        f"{label}: {len(cutouts)} windows of {len(exposures)} exposures in {took:.2f} s, {requests} requests "
        f"= {requests / len(exposures):.2f} per exposure, {after['retries'] - before['retries']} retries, "
        f"{(after['bytes'] - before['bytes']) / 1e6:.1f} MB; not read: {[reason for _, reason in failures]}"
    )
    return cutouts, failures


def test_first_twelve_windows(exposures: list[Exposure]) -> None:
    first = exposures[:12]
    rf.clear_cache()
    cutouts, failures = timed_read(first, "cold")
    assert all(reason == rf.OFF_DETECTOR for _, reason in failures), failures
    assert len(cutouts) + len(failures) == 12 and len(cutouts) >= 6
    side = 2 * HALF_PX + 1
    for cutout in cutouts:
        exposure = cutout.exposure
        low, high = DETECTOR_RANGES[exposure.det]
        assert cutout.image.shape == cutout.flags.shape == (side, side)
        assert cutout.image.dtype == np.float32 and cutout.flags.dtype == np.int32
        assert np.isfinite(cutout.image).mean() > 0.5
        assert 0 <= cutout.x0 + HALF_PX < rf.NX and 0 <= cutout.y0 + HALF_PX < rf.NY
        assert low < cutout.lam < high and 0.01 < cutout.dlam < 0.12
        assert abs(cutout.mjd - exposure.mjd) < 1e-3
        assert 3.0 < cutout.psf_fwhm < 20.0
        assert cutout.zodi_level is not None and cutout.zodi_level > 0
        assert cutout.sky_var is not None and cutout.sky_var > 0
        assert cutout.version.startswith("l2b-v")
    again, _ = timed_read(first, "warm")
    assert len(again) == len(cutouts)
    for cold, warm in zip(cutouts, again, strict=True):
        assert np.array_equal(cold.image, warm.image, equal_nan=True) and np.array_equal(
            cold.flags, warm.flags
        )
        assert (cold.lam, cold.zodi_level, cold.sky_var) == (warm.lam, warm.zodi_level, warm.sky_var)
