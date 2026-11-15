"""Golden tests on the two recorded REAL fields in ``cache/fixtures`` (Contract v1.0, section 8).

The fixtures are SPHEREx data as the production pipeline built them (``python -m tombaugh.tools.make_fixture``);
nothing here is simulated. Since pipeline 0.3.0 each also holds five older-survey ("legacy") planes,
AllWISE W1 and W2 and 2MASS J, H and Ks, after its SPHEREx planes (Contract section 5). Displayed frames are
formed exactly as the contract says a client forms them:

    frame(t) = sum_b w_b P(t, b) / sum_b w_b      over the selected wave bins b with a finite pixel
    sigma    = sqrt(sum_b w_b^2 sigma_b^2) / sum_b w_b            with uniform weights, w_b = 1

What these tests prove end to end: the frame file is the one the manifest describes; catalogue stars fall on
the pixels the grid predicts (registration, orientation and pixel convention); the cold brown dwarf is there in
the 4-5 micron frames and nowhere else to hide, and the 2010 W2 plane shows a source where it was in 2010 and
none at the centre; Barnard's Star moves north between visits.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np
import pytest
from scipy import ndimage

from tombaugh import presets
from tombaugh.frames import decode_planes
from tombaugh.grid import Grid, sky_to_pixel
from tombaugh.models import Manifest
from tombaugh.prepare import clipped_stats
from tombaugh.timebins import assign_time_bins, mjd_to_date
from tombaugh.tools import make_fixture

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "cache" / "fixtures"
NAMES = ("wise0855", "barnard")
FULL_BIN_EXPOSURES = 15  # a "full" time bin: a whole visit, not a stray pass of one or two detectors
STAR_SEARCH_RADIUS_PX = 6.0  # 18.5 arcsec: inside the 20 arcsec isolation of a fixture star
STAR_TOLERANCE_PX = 3.0
CENTRE_TOLERANCE_PX = 3.0
BARNARD_APERTURE_PX = 12.0
# Contract section 5: missions and bands of the legacy planes, in the order they follow the SPHEREx planes
LEGACY_PLANES = (("AllWISE", "W1"), ("AllWISE", "W2"), ("2MASS", "J"), ("2MASS", "H"), ("2MASS", "Ks"))
# WISE 0855: the challenge's coordinates (08h55m10.831s -07d14m42.53s), where it was in 2010, and its place at
# epoch_ref 2026.0, the centre of the recorded field
WISE0855_2010 = (133.795129, -7.245147)
WISE0855_2026 = (133.7598, -7.2422)


class Field:
    """A recorded field: its manifest and its planes, decoded to float32 (n_planes, ny, nx)."""

    def __init__(self, name: str) -> None:
        folder = FIXTURES_DIR / name
        self.name = name
        self.raw_manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.manifest = Manifest.model_validate(self.raw_manifest)
        self.frames = (folder / "frames.bin").read_bytes()
        grid = self.manifest.grid
        self.grid = Grid(self.manifest.centre.ra, self.manifest.centre.dec, grid.nx)
        self.planes = decode_planes(self.frames, len(self.manifest.planes), grid.ny, grid.nx)

    def frame(self, time_bin: int, wave_bins: list[int]) -> tuple[np.ndarray, float, int]:
        """(frame in MJy/sr, its sigma, exposures in it) for one time bin and a set of wave bins."""
        chosen = [p for p in self.manifest.planes if p.time_bin == time_bin and p.wave_bin in wave_bins]
        if not chosen:
            return np.full(self.grid.shape, np.nan, dtype=np.float32), math.nan, 0
        stack = np.stack([self.planes[p.index] for p in chosen]).astype(np.float64)
        finite = np.isfinite(stack)
        count = finite.sum(axis=0)
        with np.errstate(invalid="ignore"):
            frame = np.where(
                count > 0, np.where(finite, stack, 0.0).sum(axis=0) / np.maximum(count, 1), np.nan
            )
        sigma = math.sqrt(sum(p.sigma**2 for p in chosen)) / len(chosen)
        return frame, sigma, sum(p.n_exposures for p in chosen)

    def full_time_bins(self) -> list[int]:
        return [b.id for b in self.manifest.time_bins if b.n_exposures >= FULL_BIN_EXPOSURES]

    def best_covered_time_bin(self) -> int:
        """The time bin with the most wave bins, then the most exposures."""

        def coverage(time_bin) -> tuple[int, int]:
            return (sum(p.time_bin == time_bin.id for p in self.manifest.planes), time_bin.n_exposures)

        return max(self.manifest.time_bins, key=coverage).id


@pytest.fixture(scope="module", params=NAMES)
def field(request) -> Field:
    return Field(request.param)


@pytest.fixture(scope="module")
def wise0855() -> Field:
    return Field("wise0855")


@pytest.fixture(scope="module")
def barnard() -> Field:
    return Field("barnard")


def _disc(shape: tuple[int, int], x: float, y: float, radius: float) -> np.ndarray:
    rows, cols = np.indices(shape, dtype=np.float64)
    return np.hypot(cols - x, rows - y) <= radius


# ------------------------------------------------------------------------------------ file and manifest
def test_frames_size_and_sha256(field):
    manifest = field.manifest
    assert manifest.frames is not None
    assert len(field.frames) == manifest.frames.nbytes
    assert len(field.frames) == len(manifest.planes) * manifest.grid.ny * manifest.grid.nx * 2
    assert hashlib.sha256(field.frames).hexdigest() == manifest.frames.sha256
    assert manifest.frames.dtype == "float16" and manifest.frames.byteorder == "little"
    assert manifest.frames.url == f"/api/fields/{manifest.key}/frames.bin?v={manifest.frames.sha256[:16]}"


def test_manifest_is_a_complete_contract_manifest(field):
    manifest = field.manifest
    assert json.loads(manifest.model_dump_json()) == field.raw_manifest  # no key lost or invented
    assert manifest.contract == "1.0" and manifest.status == "ready" and manifest.epoch_ref == 2026.0
    assert manifest.request.fov_arcmin == 6
    assert manifest.grid.model_dump() == {
        "nx": 119, "ny": 119, "cx": 59, "cy": 59, "pixscale_arcsec": 3.075,
        "projection": "TAN", "row0": "north", "col0": "east",
    }  # fmt: skip
    assert (manifest.centre.ra, manifest.centre.dec) == (
        round(manifest.centre.ra, 4),
        round(manifest.centre.dec, 4),
    )
    assert [w.model_dump() for w in manifest.wave_bins] == [w.model_dump() for w in presets.wave_bins()]
    assert manifest.provenance.data_dois == ["10.26131/IRSA678", "10.26131/IRSA662"]
    assert manifest.provenance.pipeline_version == "0.3.0"
    text = json.dumps(field.raw_manifest)
    local_folders = ["/" + name + "/" for name in ("Users", "home", "private")]
    assert (
        not any(folder in text for folder in local_folders) and "@" not in text
    )  # no local path, no address


def test_planes_are_ordered_and_consistent_with_the_time_bins(field):
    manifest = field.manifest
    science = [p for p in manifest.planes if p.kind == "sci"]
    older = [p for p in manifest.planes if p.kind != "sci"]
    assert manifest.planes == science + older  # Contract section 5: legacy planes follow every SPHEREx plane
    order = [(p.time_bin, p.wave_bin) for p in science]
    assert order == sorted(set(order))
    wave_bins = {w.id: w for w in manifest.wave_bins}
    for index, plane in enumerate(manifest.planes):
        assert plane.index == index and plane.offset == index * 119 * 119 * 2
        assert plane.lam_min - 0.02 <= plane.lam_eff <= plane.lam_max + 0.02
        assert plane.n_exposures >= 1 and 0.0 < plane.sigma < 1.0
        assert np.isfinite(field.planes[index]).any()
    for plane in science:
        assert (plane.kind, plane.mission, plane.band) == ("sci", "SPHEREx", None)
        assert (plane.lam_min, plane.lam_max) == (
            wave_bins[plane.wave_bin].lam_min,
            wave_bins[plane.wave_bin].lam_max,
        )
    # Contract section 5: each legacy plane has a mission and a band, in the band order W1, W2, J, H, Ks (a
    # band that could not be made is left out), no time bin or wave bin, its own dates, "scaled" "field_stars"
    named = [(p.mission, p.band) for p in older]
    assert len(set(named)) == len(named) and named == [pair for pair in LEGACY_PLANES if pair in named]
    for plane in older:
        assert plane.kind == "legacy" and (plane.time_bin, plane.wave_bin) == (None, None)
        assert plane.scaled == "field_stars"
        assert plane.date_start <= mjd_to_date(plane.mjd_mid) <= plane.date_end
    assert [b.id for b in manifest.time_bins] == list(range(len(manifest.time_bins)))
    for time_bin in manifest.time_bins:
        mine = [p for p in manifest.planes if p.time_bin == time_bin.id]
        assert sum(p.n_exposures for p in mine) == time_bin.n_exposures
        assert sorted({p.wave_bin // 4 + 1 for p in mine}) == time_bin.detectors
        assert (
            time_bin.mjd_start <= min(p.mjd_mid for p in mine)
            and max(p.mjd_mid for p in mine) <= time_bin.mjd_end
        )
        assert time_bin.mjd_mid == pytest.approx(0.5 * (time_bin.mjd_start + time_bin.mjd_end), abs=2e-5)
    assert manifest.exposures.used == sum(b.n_exposures for b in manifest.time_bins)
    assert manifest.exposures.used <= manifest.exposures.found <= 600 and not manifest.exposures.sampled
    assert sum(manifest.exposures.collections.values()) == manifest.exposures.used
    assert manifest.exposures.newest_mjd == max(b.mjd_end for b in manifest.time_bins)


def test_time_bins_follow_the_contract_rule(field):
    """Visits are separated by more than 20 days; no bin is longer than the 60-day limit."""
    bins = field.manifest.time_bins
    for earlier, later in itertools.pairwise(bins):
        assert later.mjd_start - earlier.mjd_end > 20.0
    assert all(b.mjd_end - b.mjd_start <= 60.0 for b in bins)
    mids = [0.5 * (b.mjd_start + b.mjd_end) for b in bins]
    assert list(assign_time_bins(mids)) == list(range(len(bins)))


def test_planes_hold_finite_values_or_nan_only(field):
    assert not np.isinf(field.planes).any()
    assert np.isfinite(field.planes).mean() > 0.9  # the fields are covered: NaN marks gaps and blank cores


def test_recorded_time_bins(wise0855, barnard):
    """The visits found on 14 Nov 2026. A new data release changes these: record the fixtures again."""
    assert [(b.date_start, b.date_end, b.n_exposures) for b in wise0855.manifest.time_bins] == [
        ("2025-05-05", "2025-05-06", 29),
        ("2025-10-31", "2025-11-14", 107),
        ("2025-12-11", "2025-12-13", 18),
        ("2026-04-21", "2026-05-14", 100),
    ]
    assert [(b.date_start, b.date_end, b.n_exposures) for b in barnard.manifest.time_bins] == [
        ("2025-08-15", "2025-09-05", 104),
        ("2025-09-30", "2025-10-01", 9),
        ("2026-03-11", "2026-04-10", 111),
        ("2026-05-04", "2026-05-05", 8),
        ("2026-08-16", "2026-09-22", 116),
    ]
    assert wise0855.manifest.exposures.model_dump() == {
        "found": 258, "used": 254, "sampled": False, "collections": {"spherex_dr1": 254},
        "newest_mjd": 61174.28788, "newest_date": "2026-05-14",
    }  # fmt: skip
    assert (barnard.manifest.exposures.found, barnard.manifest.exposures.used) == (364, 348)


def test_recorded_legacy_planes(wise0855, barnard):
    """The older-survey planes recorded on 14 Nov 2026 (pipeline 0.3.0): five bands per field, after its
    SPHEREx planes, with the dates of the archive images and the field-star scaling the notes describe.
    AllWISE W1 and W2 are coadds of the 2010 passes over the field; 2MASS J, H and Ks are from one night."""
    recorded = {
        "wise0855": [
            ("AllWISE", "W1", "2010-05-03", "2010-11-13", 26),
            ("AllWISE", "W2", "2010-05-03", "2010-11-13", 26),
            ("2MASS", "J", "1998-12-28", "1998-12-28", 6),
            ("2MASS", "H", "1998-12-28", "1998-12-28", 6),
            ("2MASS", "Ks", "1998-12-28", "1998-12-28", 6),
        ],
        "barnard": [
            ("AllWISE", "W1", "2010-03-18", "2010-09-19", 30),
            ("AllWISE", "W2", "2010-03-18", "2010-09-19", 30),
            ("2MASS", "J", "2000-05-28", "2000-05-28", 6),
            ("2MASS", "H", "2000-05-28", "2000-05-28", 6),
            ("2MASS", "Ks", "2000-05-28", "2000-05-28", 6),
        ],
    }
    spherex_planes = {"wise0855": 68, "barnard": 82}
    for field in (wise0855, barnard):
        planes = field.manifest.planes
        older = [p for p in planes if p.kind == "legacy"]
        found = [(p.mission, p.band, p.date_start, p.date_end, p.n_exposures) for p in older]
        assert found == recorded[field.name]
        assert len(planes) == spherex_planes[field.name] + 5 and planes[-5:] == older
        first_visit = field.manifest.time_bins[0].date_start
        notes = field.manifest.provenance.notes
        for plane in older:
            assert plane.date_end < first_visit
            label = f"{plane.mission} {plane.band}: "
            assert any(n.startswith(label) and f"{plane.date_start} to {plane.date_end}" in n for n in notes)
            assert any(n.startswith(label + "brightness matched to the paired SPHEREx frame") for n in notes)
            data = field.planes[plane.index]
            assert np.isfinite(data).all()  # the archive images cover the whole field
            # sigma is the plane's own robust noise, on the scale of its values (measured: equal within 0.04%)
            assert clipped_stats(data)[1] == pytest.approx(plane.sigma, rel=0.01)


def test_exposures_left_out_for_the_foreground_at_1083_nm_are_accounted_for(wise0855, barnard):
    """Every listed exposure is used or named as left out. The band of 4 exposures of WISE 0855 and of 10 of
    Barnard covers the bright foreground at 1.083 micron; they were left out of planes that have other
    exposures, and no plane was lost for it."""
    notes = wise0855.manifest.provenance.notes
    assert any(note.startswith("4 exposures left out: the band covers 1.083 micron") for note in notes)
    assert any(note.startswith("1 plane near 1.08 micron made only of exposures") for note in notes)
    assert wise0855.manifest.exposures.found - wise0855.manifest.exposures.used == 4
    notes = barnard.manifest.provenance.notes
    assert any(note.startswith("10 exposures left out: the band covers 1.083 micron") for note in notes)
    assert not any("made only of exposures" in note for note in notes)
    # 364 listed = 348 used + 10 left out + 4 off the detector + 2 unusable
    assert "4 listed exposures left out: the field centre is off the detector" in notes
    assert "2 exposures could not be used (no valid pixel or unknown noise)" in barnard.manifest.warnings
    for field in (wise0855, barnard):
        full = [b.id for b in field.manifest.time_bins if b.n_exposures >= 100]
        assert len(full) >= 2
        for time_bin in full:  # every full visit still has all 24 wave bins: no frame turned "partial"
            assert sorted(p.wave_bin for p in field.manifest.planes if p.time_bin == time_bin) == list(
                range(24)
            )


# ------------------------------------------------------------------- nothing that is not the sky
def test_no_plane_holds_a_pixel_far_below_the_sky(field):
    """Regression. The first recording kept single pixels that no flag marked: -481.75 MJy/sr in one plane
    of WISE 0855 (16,868 times its noise), -3.63 MJy/sr in one of Barnard. Nothing in the sky is darker
    than the sky around it, so no plane may hold a pixel 10 times its noise below zero."""
    for plane, data in zip(field.manifest.planes, field.planes, strict=True):
        lowest = float(np.nanmin(data))
        assert lowest > -10.0 * plane.sigma, (
            f"plane {plane.index} (time bin {plane.time_bin}, wave bin {plane.wave_bin}, "
            f"{plane.n_exposures} exposures): {lowest:.3f} MJy/sr is {lowest / plane.sigma:.0f} sigma"
        )


@pytest.mark.parametrize("preset", ["cold", "all"])
def test_frames_of_few_exposures_add_no_hole_and_no_source_of_their_own(field, preset):
    """Regression. In a blink comparator an artefact of one exposure reads as something that appeared or
    vanished. The first recording had, in frames of 1 to 5 exposures per plane, holes thousands of sigma
    deep and a ring as bright as WISE 0855 around a hot pixel. Now, in every frame of both presets:

    * no pixel lies more than 8 sigma below zero;
    * every pixel more than 8 sigma above zero is within 3 pixels of something a full visit (100 exposures
      or more) shows above 5 sigma: the frames of few exposures add no source of their own.
    """
    wave_bins = presets.preset_wave_bins(preset)
    frames = {b.id: field.frame(b.id, wave_bins) for b in field.manifest.time_bins}
    frames = {time_bin: (frame / sigma) for time_bin, (frame, sigma, count) in frames.items() if count > 0}
    full = [b.id for b in field.manifest.time_bins if b.n_exposures >= 100 and b.id in frames]
    assert len(full) >= 2 and len(frames) > len(full)  # there are frames of few exposures to check
    seen = np.zeros(field.grid.shape, dtype=bool)
    for time_bin in full:
        seen |= np.nan_to_num(frames[time_bin], nan=0.0) > 5.0
    seen = ndimage.binary_dilation(seen, iterations=3)
    for time_bin, snr in frames.items():
        assert float(np.nanmin(snr)) > -8.0, f"time bin {time_bin}: a pixel at {np.nanmin(snr):.0f} sigma"
        alone = np.isfinite(snr) & (snr > 8.0) & ~seen
        rows, cols = np.nonzero(alone)
        assert not alone.any(), f"time bin {time_bin}: unmatched pixels at (x, y) {list(zip(cols, rows))[:5]}"


# ------------------------------------------------------------------------------------- fixture stars
def test_fixture_stars_map_to_their_recorded_pixels(field):
    """Contract section 8: each star's sky position gives its recorded pixel within 0.5 px (here: 0.001)."""
    stars = field.manifest.fixture_stars
    assert stars is not None and len(stars) == 3
    assert len({star.source_id for star in stars}) == 3 and all(star.source_id.isdigit() for star in stars)
    for star in stars:
        x, y = sky_to_pixel(field.grid, star.ra, star.dec)
        assert math.hypot(x - star.x, y - star.y) < 1e-3
        assert 10.0 <= star.x <= 108.0 and 10.0 <= star.y <= 108.0


def test_fixture_stars_are_where_the_grid_says(field):
    """The brightest pixel near each Gaia star, in the all-band frame of the best-covered time bin, lies
    within 3 output pixels of the position the grid predicts. A flipped axis, a transposed array, a dropped
    distortion term or an off-by-one in the pixel convention would each move it by far more."""
    time_bin = field.best_covered_time_bin()
    frame, sigma, n_exposures = field.frame(time_bin, presets.preset_wave_bins("all"))
    assert n_exposures >= 100
    for star in field.manifest.fixture_stars:
        near = _disc(frame.shape, star.x, star.y, STAR_SEARCH_RADIUS_PX) & np.isfinite(frame)
        assert near.sum() > 100
        row, col = np.unravel_index(np.argmax(np.where(near, frame, -np.inf)), frame.shape)
        offset = math.hypot(col - star.x, row - star.y)
        assert frame[row, col] > 20.0 * sigma, f"star {star.source_id} is not clearly detected"
        assert offset <= STAR_TOLERANCE_PX, f"star {star.source_id}: brightest pixel {offset:.2f} px away"


def test_fixture_star_check_fails_on_a_mirrored_or_transposed_frame(field):
    """The check above has teeth: on the same frame flipped east-west, flipped north-south or transposed,
    at least one of the three stars is no longer within 3 px of where the grid says."""
    time_bin = field.best_covered_time_bin()
    frame, _, _ = field.frame(time_bin, presets.preset_wave_bins("all"))
    for wrong in (frame[:, ::-1], frame[::-1, :], frame.T):
        missed = 0
        for star in field.manifest.fixture_stars:
            near = _disc(wrong.shape, star.x, star.y, STAR_SEARCH_RADIUS_PX) & np.isfinite(wrong)
            row, col = np.unravel_index(np.argmax(np.where(near, wrong, -np.inf)), wrong.shape)
            missed += math.hypot(col - star.x, row - star.y) > STAR_TOLERANCE_PX
        assert missed >= 1


# ----------------------------------------------------------------------------------------- WISE 0855
def _local_maxima_near(frame: np.ndarray, x: float, y: float, radius: float) -> list[tuple[float, float]]:
    """(value, distance from (x, y) in px) of every local maximum within `radius` px of (x, y)."""
    filled = np.where(np.isfinite(frame), frame, -np.inf)
    peaks = (filled == ndimage.maximum_filter(filled, size=3, mode="nearest")) & np.isfinite(frame)
    peaks &= _disc(frame.shape, x, y, radius)
    rows, cols = np.nonzero(peaks)
    return [(float(frame[r, c]), math.hypot(c - x, r - y)) for r, c in zip(rows, cols, strict=True)]


def _local_maxima_near_centre(frame: np.ndarray, grid: Grid, radius: float) -> list[tuple[float, float]]:
    """(value, distance from the centre in px) of every local maximum within `radius` px of the centre."""
    return _local_maxima_near(frame, grid.cx, grid.cy, radius)


def test_wise0855_is_at_the_centre_of_every_full_cold_frame(wise0855):
    """WISE 0855-0714 at its 2026.0 position: a local maximum above 5 sigma within 3 px of the centre in the
    "cold" (4-5 micron) frame of every time bin with at least 15 exposures."""
    cold = presets.preset_wave_bins("cold")
    full = wise0855.full_time_bins()
    assert len(full) >= 3
    for time_bin in full:
        frame, sigma, n_exposures = wise0855.frame(time_bin, cold)
        assert n_exposures >= 5 and sigma > 0.0
        peaks = _local_maxima_near_centre(frame, wise0855.grid, CENTRE_TOLERANCE_PX)
        best = max(peaks, default=(0.0, math.nan))
        assert best[0] > 5.0 * sigma, f"time bin {time_bin}: brightest peak {best[0] / sigma:.1f} sigma"


def test_wise0855_peaks_at_the_centre_only_in_the_cold_frames(wise0855):
    """In the two long visits the 4-5 micron frame has its peak within 1.5 px of the centre, and the
    0.75-2.4 micron frame has no peak there at all: its only peak within 3 px is the catalogued background
    star about 2.2 px away (the "blended neighbour" of Contract section 8). A star at the centre would peak
    in both; this is what the "cold" preset exists to show."""
    cold = presets.preset_wave_bins("cold")
    warm = [b for d in ("d1", "d2", "d3") for b in presets.preset_wave_bins(d)]
    long_visits = [b.id for b in wise0855.manifest.time_bins if b.n_exposures >= 100]
    assert len(long_visits) == 2
    for time_bin in long_visits:
        cold_frame, cold_sigma, _ = wise0855.frame(time_bin, cold)
        warm_frame, _, _ = wise0855.frame(time_bin, warm)
        cold_peak = max(_local_maxima_near_centre(cold_frame, wise0855.grid, CENTRE_TOLERANCE_PX))
        assert cold_peak[0] > 15.0 * cold_sigma and cold_peak[1] <= 1.5
        warm_peaks = _local_maxima_near_centre(warm_frame, wise0855.grid, CENTRE_TOLERANCE_PX)
        assert warm_peaks and all(distance > 1.5 for _, distance in warm_peaks)


def test_wise0855_w2_plane_shows_a_source_at_the_2010_position_and_none_at_the_centre(wise0855):
    """Then and Now on the recording. The AllWISE W2 plane (passes of 2010-05-03 to 2010-11-13) has a source
    at the challenge's coordinates, where WISE 0855 was in 2010, about 127 arcsec east of the field centre,
    and nothing comparable at the centre, where the SPHEREx 4-5 micron frames of 2025-26 show the dwarf (the
    two tests above). Near the centre the 2010 plane peaks only on the catalogued background star about 2.2
    px away (the "blended neighbour" of Contract section 8). The values in the comments were measured on this
    recording."""
    w2 = next(p for p in wise0855.manifest.planes if p.kind == "legacy" and p.band == "W2")
    plane = wise0855.planes[w2.index]
    then_x, then_y = (float(v) for v in sky_to_pixel(wise0855.grid, *WISE0855_2010))  # (17.97, 62.46)
    now_x, now_y = (float(v) for v in sky_to_pixel(wise0855.grid, *WISE0855_2026))  # (59, 59)
    then_value, then_offset = max(_local_maxima_near(plane, then_x, then_y, 2.0), default=(0.0, math.inf))
    # measured: 0.207 MJy/sr, 30.3 times the plane's sigma (0.00682), at pixel (18, 62), 0.46 px away
    assert then_value > 15.0 * w2.sigma and then_offset <= 1.5
    # measured: no local maximum within 1.5 px of the centre (the nearest, the neighbour, is 2.24 px away at
    # 8.8 sigma), and the brightest of the 3 x 3 pixels there is 6.8 sigma, 0.23 times the 2010 source
    assert _local_maxima_near(plane, now_x, now_y, 1.5) == []
    near_now = _disc(plane.shape, now_x, now_y, 1.5)
    assert near_now.sum() == 9 and np.isfinite(plane[near_now]).all()
    assert float(plane[near_now].max()) < then_value / 3.0


# ---------------------------------------------------------------------------------------- Barnard's Star
def _centroid_y(frame: np.ndarray, grid: Grid, radius: float) -> tuple[float, float]:
    """Flux-weighted centroid (x, y) of the finite pixels within `radius` px of the centre."""
    use = _disc(frame.shape, grid.cx, grid.cy, radius) & np.isfinite(frame)
    rows, cols = np.indices(frame.shape, dtype=np.float64)
    flux = np.where(use, frame, 0.0)
    return float((flux * cols).sum() / flux.sum()), float((flux * rows).sum() / flux.sum())


def test_barnard_moves_north_between_the_first_and_last_full_time_bin(barnard):
    """Barnard's Star moves 10.4 arcsec (3.4 output pixels) north per year. The flux-weighted centroid of
    the D5 and D6 frames (finite pixels within 12 px of the centre) moves to smaller y by 2 to 5 pixels
    between the first and the last full time bin, about one year apart, and hardly at all east-west."""
    red = presets.preset_wave_bins("d5") + presets.preset_wave_bins("d6")
    full = barnard.full_time_bins()
    first, last = full[0], full[-1]
    bins = {b.id: b for b in barnard.manifest.time_bins}
    years = (bins[last].mjd_mid - bins[first].mjd_mid) / 365.25
    assert 0.9 < years < 1.2
    x_first, y_first = _centroid_y(barnard.frame(first, red)[0], barnard.grid, BARNARD_APERTURE_PX)
    x_last, y_last = _centroid_y(barnard.frame(last, red)[0], barnard.grid, BARNARD_APERTURE_PX)
    moved_north = y_first - y_last
    assert 2.0 <= moved_north <= 5.0, f"moved {moved_north:.2f} px north in {years:.2f} years"
    assert abs(x_last - x_first) < 1.5
    # the field centre is the 2026.0 position: the star is south of it before, north of it after
    assert y_first > barnard.grid.cy > y_last


def test_barnard_core_is_saturated_and_says_so(barnard):
    """The saturated core is NaN in the SPHEREx planes of the frame file (never zero), and the manifest warns
    about it. The legacy planes do not show this core (in 2010 the star was about 161 arcsec south of the
    centre, in 2000 off the field), and their single pixels of exactly 0.0 are values: the background median
    subtracted (ENGINE_NOTES known limit 16)."""
    assert any("saturated core within 15 arcsec of the centre" in w for w in barnard.manifest.warnings)
    centre = _disc(barnard.grid.shape, barnard.grid.cx, barnard.grid.cy, 6.0)
    science = [barnard.planes[p.index] for p in barnard.manifest.planes if p.kind == "sci"]
    blank = [int(np.isnan(plane[centre]).sum()) for plane in science]
    assert sum(count > 0 for count in blank) >= len(blank) // 4  # many planes have a blank core ...
    assert all(not (plane[centre] == 0.0).any() for plane in science)  # ... and none fakes it with zeros


# ------------------------------------------------------------------ how the fixtures are made (no network)
def test_fixtures_are_centred_where_the_objects_are_at_epoch_ref(wise0855, barnard):
    """The centres are computed from published astrometry, not typed in."""
    assert make_fixture.target_centre("wise0855") == (
        wise0855.manifest.centre.ra,
        wise0855.manifest.centre.dec,
    )
    assert make_fixture.target_centre("barnard") == (barnard.manifest.centre.ra, barnard.manifest.centre.dec)
    assert make_fixture.target_centre("wise0855") == (133.7598, -7.2422)
    assert make_fixture.target_centre("barnard") == (269.4463, 4.7682)
    # WISE 0855 has moved about 127 arcsec from the challenge's 2010 coordinates: outside nothing, but far
    x, y = sky_to_pixel(wise0855.grid, 133.795129, -7.245147)
    assert 120.0 < math.hypot(x - 59, y - 59) * 3.075 < 135.0


def test_propagation_by_proper_motion():
    barnard = make_fixture.TARGETS["barnard"]
    ra, dec = make_fixture.propagate(barnard.ra, barnard.dec, barnard.pmra, barnard.pmdec, 2016.0, 2026.0)
    assert (dec - barnard.dec) * 3600.0 == pytest.approx(103.62394, abs=2e-3)  # 10 years of +10362.394 mas/yr
    west = (barnard.ra - ra) * 3600.0 * math.cos(math.radians(0.5 * (dec + barnard.dec)))
    assert west == pytest.approx(8.01551, abs=2e-3)  # 10 years of -801.551 mas/yr
    assert make_fixture.propagate(10.0, 20.0, 0.0, 0.0, 2016.0) == pytest.approx((10.0, 20.0), abs=1e-12)
    assert make_fixture.propagate(ra, dec, barnard.pmra, barnard.pmdec, 2026.0, 2016.0) == pytest.approx(
        (barnard.ra, barnard.dec), abs=1e-6
    )


def test_gaia_csv_is_parsed_and_moved_to_epoch_ref():
    synthetic_csv = (
        "source_id,ra,dec,pmra,pmdec,phot_g_mean_mag\r\n"
        "4472832130942575872,269.44850253,4.73942005,-801.551,10362.394,8.19\r\n"
        "111,269.5,4.7,,,20.5\r\n"
        "222,269.6,4.8,1.0,-1.0,\r\n"
        "bad,269.6,4.8,1.0,-1.0,12.0\r\n"
        "333,,4.8,1.0,-1.0,12.0\r\n"
    )
    stars = make_fixture.parse_gaia_csv(synthetic_csv)
    assert [star.source_id for star in stars] == ["4472832130942575872", "111", "222"]
    assert (round(stars[0].ra, 4), round(stars[0].dec, 4)) == (269.4463, 4.7682) and stars[0].g == 8.19
    assert (stars[1].ra, stars[1].dec, stars[1].g) == (269.5, 4.7, 20.5)  # no proper motion: left in place
    assert stars[2].g is None


def test_fixture_star_choice_follows_the_written_rules():
    """Synthetic catalogue positions on a real grid: isolated stars first, then nearly isolated, brightest first."""
    grid = Grid.for_field(100.0, 0.0, 6)
    arcsec = 1.0 / 3600.0

    def star(source_id: str, east: float, north: float, g: float | None) -> make_fixture.GaiaStar:
        return make_fixture.GaiaStar(source_id, 100.0 + east * arcsec, north * arcsec, g)

    synthetic_catalogue = [
        star("1", 0.0, 0.0, 9.0),  # too bright itself, and makes its surroundings unusable
        star("2", 40.0, 0.0, 13.0),  # within 60 arcsec of the bright one
        star("3", 100.0, 100.0, 14.0),  # isolated
        star("4", -100.0, 100.0, 12.5),  # a neighbour 3.5 mag fainter at 10 arcsec: second choice
        star("5", -100.0, 110.0, 16.0),
        star("6", -100.0, -100.0, 13.5),  # a neighbour only 2 mag fainter: never
        star("7", -110.0, -100.0, 15.5),
        star("8", 100.0, -100.0, 15.4),  # isolated, faint
        star("9", 175.0, 0.0, 12.0),  # isolated but 5 arcsec from the edge
        star("10", 0.0, 130.0, 11.5),  # brighter than the range
        star("11", 0.0, -130.0, 15.6),  # fainter than the range
        star("12", 60.0, -140.0, None),  # no magnitude
        star("13", -150.0, 20.0, 14.5),  # a neighbour without a magnitude within 20 arcsec
        star("14", -150.0, 30.0, None),
    ]
    chosen = make_fixture.choose_fixture_stars(synthetic_catalogue, grid, count=5)
    assert [s.source_id for s in chosen] == ["3", "8", "4"]
    assert [s.source_id for s in make_fixture.choose_fixture_stars(synthetic_catalogue, grid)] == [
        "3",
        "8",
        "4",
    ]
    assert [s.source_id for s in make_fixture.choose_fixture_stars(synthetic_catalogue[::-1], grid)] == [
        "3",
        "8",
        "4",
    ]
    assert make_fixture.choose_fixture_stars([], grid) == []
    models = make_fixture.fixture_star_models(chosen, grid)
    assert [(m.source_id, m.x, m.y) for m in models] == [
        ("3", pytest.approx(59 - 100 / 3.075, abs=0.01), pytest.approx(59 - 100 / 3.075, abs=0.01)),
        ("8", pytest.approx(59 - 100 / 3.075, abs=0.01), pytest.approx(59 + 100 / 3.075, abs=0.01)),
        ("4", pytest.approx(59 + 100 / 3.075, abs=0.01), pytest.approx(59 - 100 / 3.075, abs=0.01)),
    ]


def test_recorded_fixture_stars_are_apart_from_each_other_and_from_the_centre(field):
    """What can be checked without the catalogue: three distinct stars, apart from each other and from the
    field centre, where the fixture's own object sits."""
    stars = field.manifest.fixture_stars
    for one, other in itertools.combinations(stars, 2):
        assert math.hypot(one.x - other.x, one.y - other.y) * 3.075 > 20.0
    for star in stars:
        assert math.hypot(star.x - 59, star.y - 59) * 3.075 > 60.0
