"""The build pipeline: sampling, the content key, manifest assembly and the order of the stages.

No network and no sky data: exposure lists, planes and cutouts are synthetic (named ``synthetic_*``) and
exist only to exercise the arithmetic and the bookkeeping. The real pipeline output is checked by
``test_fixtures_golden.py``.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import random
import time

import numpy as np
import pytest

from tombaugh import build, http, legacy, main, presets, remote_fits, stack
from tombaugh import spectrum as spectra
from tombaugh.build import (
    AlreadyBuilt,
    BuildStats,
    assemble_manifest,
    build_field,
    build_field_with_stats,
    field_key,
    frames_url,
    frames_version,
    leave_out_helium,
    sample_exposures,
    sees_helium_line,
)
from tombaugh.cache import REQUEST_TTL_S, FieldCache, request_id
from tombaugh.frames import decode_planes, sha256_hex
from tombaugh.grid import NATIVE_PIXSCALE_ARCSEC, Grid, native_half_window
from tombaugh.main import Builder
from tombaugh.models import Manifest
from tombaugh.prepare import OVERFLOW, bit_mask
from tombaugh.stack import Registered
from tombaugh.types import Cutout, Exposure, StackedPlane

RA, DEC = 133.7598, -7.2422


def synthetic_exposure(obs_id: str, det: int, mjd: float, collection: str = "spherex_dr1") -> Exposure:
    key = f"dr1/level2/2025W19_1B/l2b-v27-2026-197/{det}/level2_{obs_id}D{det}_spx_l2b-v27-2026-197.fits"
    return Exposure(
        obs_id=obs_id,
        det=det,
        mjd=mjd,
        collection=collection,
        bucket="nasa-irsa-spherex",
        region="us-east-1",
        key=key,
    )


def synthetic_exposures(per_group: dict[tuple[int, int], int]) -> list[Exposure]:
    """Exposures for {(visit, detector): count}; visits are 100 days apart, far more than the 20-day gap."""
    out: list[Exposure] = []
    for (visit, det), count in sorted(per_group.items()):
        for i in range(count):
            mjd = 60800.0 + 100.0 * visit + 0.01 * i + 0.001 * det
            out.append(synthetic_exposure(f"V{visit}_{i:04d}", det, mjd))
    return out


def _group_counts(exposures: list[Exposure]) -> dict[tuple[int, int], int]:
    counts: dict[tuple[int, int], int] = {}
    for exposure in exposures:
        visit = int(exposure.obs_id[1 : exposure.obs_id.index("_")])
        counts[(visit, exposure.det)] = counts.get((visit, exposure.det), 0) + 1
    return counts


# ------------------------------------------------------------------------------------------- sampling
def test_sampling_keeps_everything_under_the_limit():
    synthetic = synthetic_exposures({(0, 1): 3, (0, 2): 4, (1, 6): 2})
    shuffled = synthetic[:]
    random.Random(1).shuffle(shuffled)
    chosen = sample_exposures(shuffled, 600)
    assert chosen == sorted(synthetic, key=lambda e: (e.mjd, e.det, e.obs_id))
    assert sample_exposures(synthetic, len(synthetic)) == chosen


def test_sampling_returns_exactly_the_limit_and_only_listed_exposures():
    synthetic = synthetic_exposures({(v, d): 40 + 7 * d + 3 * v for v in range(4) for d in range(1, 7)})
    assert len(synthetic) > 600
    chosen = sample_exposures(synthetic, 600)
    assert len(chosen) == 600
    assert len({e.uid for e in chosen}) == 600
    assert {e.uid for e in chosen} <= {e.uid for e in synthetic}
    assert chosen == sorted(chosen, key=lambda e: (e.mjd, e.det, e.obs_id))


def test_sampling_does_not_depend_on_the_input_order():
    synthetic = synthetic_exposures({(v, d): 55 for v in range(3) for d in range(1, 7)})
    reference = sample_exposures(synthetic, 200)
    for seed in range(5):
        shuffled = synthetic[:]
        random.Random(seed).shuffle(shuffled)
        assert sample_exposures(shuffled, 200) == reference
    assert sample_exposures(synthetic + synthetic[:50], 200) == reference  # repeated rows change nothing


def test_sampling_is_even_per_time_bin_and_detector():
    sizes = {(0, 1): 5, (0, 2): 300, (1, 2): 200, (1, 5): 90, (2, 6): 400}
    chosen = _group_counts(sample_exposures(synthetic_exposures(sizes), 300))
    assert sum(chosen.values()) == 300
    assert chosen[(0, 1)] == 5  # a group smaller than its share is kept whole
    cut = [chosen[key] for key in sizes if chosen[key] < sizes[key]]
    assert len(cut) == 4 and max(cut) - min(cut) <= 1  # the groups that lost members end up equal


def test_sampling_spreads_over_a_group_in_obs_id_order():
    synthetic = synthetic_exposures({(0, 3): 100})
    chosen = sample_exposures(synthetic, 10)
    picked = [int(e.obs_id.split("_")[1]) for e in chosen]
    assert picked == [5, 15, 25, 35, 45, 55, 65, 75, 85, 95]


def test_sampling_edge_limits():
    synthetic = synthetic_exposures({(0, 1): 4})
    assert sample_exposures(synthetic, 0) == []
    assert sample_exposures([], 600) == []
    assert len(sample_exposures(synthetic, 1)) == 1


@pytest.mark.parametrize("limit", [1, 7, 24, 100, 599])
def test_fair_quotas_use_every_place(limit):
    sizes = {(v, d): 10 + 13 * v + 5 * d for v in range(4) for d in range(1, 7)}
    quotas = build._fair_quotas(sizes, limit)
    assert sum(quotas.values()) == limit
    assert all(0 <= quotas[key] <= sizes[key] for key in sizes)


@pytest.mark.parametrize(("count", "wanted"), [(10, 3), (100, 10), (7, 7), (7, 9), (600, 599), (5, 1)])
def test_spread_gives_distinct_increasing_indices(count, wanted):
    picked = build._spread(count, wanted)
    assert len(picked) == min(count, wanted)
    assert picked == sorted(set(picked))
    assert 0 <= picked[0] and picked[-1] < count


# ------------------------------------------------------------------------------------------------ key
def test_key_is_sixteen_hex_characters_and_ignores_uid_order():
    uids = [f"2025W19_1B_{i:04d}_1/D{1 + i % 6}" for i in range(30)]
    key = field_key(RA, DEC, 6, uids)
    assert len(key) == 16 and set(key) <= set("0123456789abcdef")
    assert field_key(RA, DEC, 6, list(reversed(uids))) == key
    assert field_key(RA, DEC, 6, uids + uids[:3]) == key


def test_key_follows_the_documented_recipe(monkeypatch):
    monkeypatch.setattr(build, "PIPELINE_VERSION", "0.1.0")
    uids = ["b/D2", "a/D1"]
    document = {
        "centre": ["133.7598", "-7.2422"],
        "contract": "1.0",
        "epoch_ref": 2026.0,
        "exposures": ["a/D1", "b/D2"],
        "fov_arcmin": 6,
        "pipeline_version": "0.1.0",
    }
    text = json.dumps(document, sort_keys=True, separators=(",", ":"))
    assert field_key(RA, DEC, 6, uids) == hashlib.sha256(text.encode("ascii")).hexdigest()[:16]
    assert field_key(RA, DEC, 6, uids) == "9b1e65ec1725257d"  # recorded: a change here empties every cache


def test_key_changes_with_every_ingredient(monkeypatch):
    uids = ["a/D1", "b/D2"]
    base = field_key(RA, DEC, 6, uids)
    assert field_key(RA + 0.0001, DEC, 6, uids) != base
    assert field_key(RA, DEC - 0.0001, 6, uids) != base
    assert field_key(RA, DEC, 8, uids) != base
    assert field_key(RA, DEC, 6, uids + ["c/D3"]) != base
    assert field_key(RA, DEC, 6, []) != base
    assert field_key(RA + 0.00001, DEC, 6, uids) == base  # below the 4-decimal snap: the same field
    monkeypatch.setattr(build, "PIPELINE_VERSION", "9.9.9")
    assert field_key(RA, DEC, 6, uids) != base


# ------------------------------------------------------------------------------------------- manifest
def synthetic_plane(
    grid: Grid, time_bin: int, wave_bin: int, level: float, n_exposures: int = 3
) -> StackedPlane:
    synthetic_data = (level + 0.001 * np.arange(grid.n * grid.n, dtype=np.float32)).reshape(grid.shape)
    synthetic_data[0, 0] = np.nan
    mjd_min = 60800.25 + 100.0 * time_bin
    return StackedPlane(
        time_bin=time_bin,
        wave_bin=wave_bin,
        data=synthetic_data,
        n_exposures=n_exposures,
        sigma=0.0125 + 0.001 * wave_bin,
        lam_eff=4.4912345 if wave_bin == 20 else 1.0,
        mjd_mid=mjd_min + 1.0,
        mjd_min=mjd_min,
        mjd_max=mjd_min + 2.0,
    )


def synthetic_item(grid: Grid, obs_id: str, det: int, mjd: float, time_bin: int, wave_bin: int) -> Registered:
    return Registered(
        exposure=synthetic_exposure(obs_id, det, mjd, "spherex_dr1" if det < 6 else "spherex_qr3"),
        data=np.zeros(grid.shape, dtype=np.float32),
        weight=1.0,
        lam=1.0,
        mjd=mjd,
        time_bin=time_bin,
        wave_bin=wave_bin,
    )


def _synthetic_field():
    grid = Grid.for_field(RA, DEC, 3)
    synthetic_planes = [
        synthetic_plane(grid, 1, 3, 3.0),
        synthetic_plane(grid, 0, 20, 1.0),
        synthetic_plane(grid, 1, 20, 2.0),
    ]
    synthetic_items = [
        synthetic_item(grid, "A_0001", 6, 60800.25, 0, 20),
        synthetic_item(grid, "A_0002", 6, 60801.25, 0, 20),
        synthetic_item(grid, "A_0003", 6, 60802.25, 0, 20),
        synthetic_item(grid, "B_0001", 1, 60900.25, 1, 3),
        synthetic_item(grid, "B_0002", 6, 60902.75, 1, 20),
    ]
    return grid, synthetic_planes, synthetic_items


def test_manifest_assembled_from_synthetic_planes():
    grid, synthetic_planes, synthetic_items = _synthetic_field()
    manifest, frames = assemble_manifest(
        RA + 0.00002,
        DEC,
        3,
        grid,
        synthetic_planes,
        synthetic_items,
        found=7,
        built_at="2026-11-14T12:30:00Z",
    )
    assert manifest.contract == "1.0" and manifest.status == "ready" and manifest.epoch_ref == 2026.0
    assert manifest.request.model_dump() == {"ra": RA + 0.00002, "dec": DEC, "fov_arcmin": 3}
    assert manifest.centre.model_dump() == {"ra": RA, "dec": DEC}
    assert manifest.grid.model_dump() == {
        "nx": 59, "ny": 59, "cx": 29, "cy": 29, "pixscale_arcsec": 3.075,
        "projection": "TAN", "row0": "north", "col0": "east",
    }  # fmt: skip
    assert manifest.time_binning.model_dump() == {"gap_days": 20, "max_span_days": 60, "sub_span_days": 30}
    assert [w.model_dump() for w in manifest.wave_bins] == [w.model_dump() for w in presets.wave_bins()]

    # planes in (time_bin, wave_bin) order, whatever order they were given in
    assert [(p.time_bin, p.wave_bin) for p in manifest.planes] == [(0, 20), (1, 3), (1, 20)]
    assert [p.index for p in manifest.planes] == [0, 1, 2]
    assert [p.offset for p in manifest.planes] == [0, 59 * 59 * 2, 2 * 59 * 59 * 2]
    first = manifest.planes[0]
    assert (first.kind, first.mission, first.band) == ("sci", "SPHEREx", None)
    assert (first.lam_min, first.lam_max) == (4.412, 4.5595)
    assert first.lam_eff == 4.49123 and first.n_exposures == 3 and first.sigma == pytest.approx(0.0325)
    assert (first.mjd_mid, first.date_start, first.date_end) == (60801.25, "2025-05-05", "2025-05-07")

    # frames.bin: the planes in index order, float16, NaN kept
    assert manifest.frames is not None
    assert manifest.frames.model_dump() == {
        "url": f"/api/fields/{manifest.key}/frames.bin?v={sha256_hex(frames)[:16]}",
        "dtype": "float16",
        "byteorder": "little",
        "nbytes": 3 * 59 * 59 * 2,
        "sha256": sha256_hex(frames),
    }
    decoded = decode_planes(frames, 3, 59, 59)
    ordered = sorted(synthetic_planes, key=lambda p: (p.time_bin, p.wave_bin))
    for plane, got in zip(ordered, decoded, strict=True):
        assert np.isnan(got[0, 0])
        np.testing.assert_allclose(got[1:], plane.data[1:], rtol=1e-3)

    assert manifest.key == field_key(RA, DEC, 3, [item.exposure.uid for item in synthetic_items])
    assert manifest.exposures.model_dump() == {
        "found": 7,
        "used": 5,
        "sampled": False,
        "collections": {"spherex_dr1": 1, "spherex_qr3": 4},
        "newest_mjd": 60902.75,
        "newest_date": "2025-08-15",
    }
    assert [b.model_dump() for b in manifest.time_bins] == [
        {"id": 0, "mjd_start": 60800.25, "mjd_end": 60802.25, "mjd_mid": 60801.25,
         "date_start": "2025-05-05", "date_end": "2025-05-07", "n_exposures": 3, "detectors": [6]},
        {"id": 1, "mjd_start": 60900.25, "mjd_end": 60902.75, "mjd_mid": 60901.5,
         "date_start": "2025-08-13", "date_end": "2025-08-15", "n_exposures": 2, "detectors": [1, 6]},
    ]  # fmt: skip
    assert manifest.provenance.pipeline_version == build.PIPELINE_VERSION
    assert manifest.provenance.built_at == "2026-11-14T12:30:00Z"
    assert manifest.provenance.data_dois == ["10.26131/IRSA678", "10.26131/IRSA662"]
    assert manifest.provenance.notes[0] == 'resampled to 3.075"/px; native pixel 6.15"; resolution about 10"'
    assert manifest.provenance.notes[1:] == [build.NOTE_STACKS, build.NOTE_REJECTION]
    # the note states the cost of `stack.REJECT_MAX_FRACTION`; the two must change together
    assert "one in ten of them or fewer" in build.NOTE_REJECTION and stack.REJECT_MAX_FRACTION == 0.10
    assert manifest.warnings == []

    # what goes over the wire is a valid manifest and has no fixture_stars key
    wire = json.loads(manifest.model_dump_json())
    assert "fixture_stars" not in wire
    assert Manifest.model_validate(wire).model_dump() == manifest.model_dump()


def test_frame_url_names_the_bytes_and_not_only_the_exposures():
    """The key hashes the exposure names, not their pixels: a reprocessed archive file or a pipeline change
    without a version bump gives other bytes under the same key. The file is answered as immutable, so its
    URL must change with its bytes."""
    grid, synthetic_planes, synthetic_items = _synthetic_field()
    first, frames = assemble_manifest(RA, DEC, 3, grid, synthetic_planes, synthetic_items, found=5)
    synthetic_planes[0].data[5, 5] += 1.0  # the same exposures, other pixels
    second, other_frames = assemble_manifest(RA, DEC, 3, grid, synthetic_planes, synthetic_items, found=5)
    assert second.key == first.key and other_frames != frames
    assert second.frames.url != first.frames.url
    assert first.frames.url == frames_url(first.key, first.frames.sha256)
    assert first.frames.url.split("?v=") == [f"/api/fields/{first.key}/frames.bin", first.frames.sha256[:16]]
    assert frames_version(first.frames.sha256) == first.frames.sha256[:16]
    assert len(frames_version(sha256_hex(b""))) == 16


def test_manifest_is_the_same_for_any_plane_order():
    grid, synthetic_planes, synthetic_items = _synthetic_field()
    stamp = "2026-11-14T12:30:00Z"
    first = assemble_manifest(RA, DEC, 3, grid, synthetic_planes, synthetic_items, found=5, built_at=stamp)
    second = assemble_manifest(
        RA, DEC, 3, grid, synthetic_planes[::-1], synthetic_items[::-1], found=5, built_at=stamp
    )
    assert first[1] == second[1]
    assert first[0].model_dump() == second[0].model_dump()


def test_manifest_status_partial_and_sampled_flags():
    grid, synthetic_planes, synthetic_items = _synthetic_field()
    manifest, _ = assemble_manifest(
        RA, DEC, 3, grid, synthetic_planes, synthetic_items, found=900, sampled=True, partial=True,
        warnings=["build stopped"], notes=["extra note"],
    )  # fmt: skip
    assert manifest.status == "partial"
    assert manifest.exposures.found == 900 and manifest.exposures.sampled is True
    assert manifest.warnings == ["build stopped"]
    assert manifest.provenance.notes[-1] == "extra note"
    assert manifest.provenance.built_at.endswith("Z") and len(manifest.provenance.built_at) == 20


def test_manifest_without_planes_is_empty():
    grid = Grid.for_field(RA, DEC, 6)
    manifest, frames = assemble_manifest(RA, DEC, 6, grid, [], [], found=0)
    assert frames == b""
    assert manifest.status == "empty" and manifest.planes == [] and manifest.frames is None
    assert manifest.time_bins == [] and len(manifest.wave_bins) == 24
    assert manifest.exposures.model_dump() == {
        "found": 0, "used": 0, "sampled": False, "collections": {}, "newest_mjd": None, "newest_date": None,
    }  # fmt: skip
    assert manifest.key == field_key(RA, DEC, 6, [])
    wire = json.loads(manifest.model_dump_json())
    assert wire["frames"] is None and wire["planes"] == []
    Manifest.model_validate(wire)


# ------------------------------------------------------------------------------------------- warnings
def test_warning_texts():
    """Visits are named by their dates, never by an id from 0; a blank (saturated) core and an overflowing
    but measured one (indicative only) are told apart, in words the page can show."""
    stats = BuildStats(selected=258, read=250, failed=3, timed_out=5, unusable=1)
    grid, synthetic_planes, synthetic_items = _synthetic_field()
    manifest, _ = assemble_manifest(RA, DEC, 3, grid, synthetic_planes, synthetic_items, found=258)
    cores = {build.CORE_BLANK: 12, build.CORE_OVERFLOW: 7}
    assert build._warnings(stats, cores, 120.0, manifest.time_bins) == [
        "build stopped at the 120 s deadline: 250 of 258 exposures were read",
        "3 exposures failed to download",
        "1 exposure could not be used (no valid pixel or unknown noise)",
        (
            "saturated core within 15 arcsec of the centre in 12 of 250 exposures: those pixels have no "
            "value, so no brightness can be read there"
        ),
        (
            "bright core within 15 arcsec of the centre flagged as overflowing in 7 of 250 exposures, but "
            "measured: brightness there is indicative only"
        ),
        "the visit of 2025-05-05 to 2025-05-07 has only 3 exposures",
        "the visit of 2025-08-13 to 2025-08-15 has only 2 exposures",
    ]
    assert not any(
        "time bin" in warning for warning in build._warnings(stats, cores, 120.0, manifest.time_bins)
    )
    overflow_only = build._warnings(BuildStats(read=30), {build.CORE_OVERFLOW: 2}, 120.0, [])
    assert overflow_only == [
        (
            "bright core within 15 arcsec of the centre flagged as overflowing in 2 of 30 exposures, but "
            "measured: brightness there is indicative only"
        )
    ]
    assert not any("saturated" in warning for warning in overflow_only)
    assert build._warnings(BuildStats(selected=30, read=30), {}, 120.0, []) == []


def test_a_visit_of_one_day_is_named_by_that_day():
    grid, synthetic_planes, synthetic_items = _synthetic_field()
    manifest, _ = assemble_manifest(RA, DEC, 3, grid, synthetic_planes, synthetic_items, found=5)
    one_day = manifest.time_bins[0].model_copy(update={"date_end": manifest.time_bins[0].date_start})
    assert build.visit_label(one_day) == "the visit of 2025-05-05"
    assert build.visit_label(manifest.time_bins[1]) == "the visit of 2025-08-13 to 2025-08-15"


def test_notes_say_what_the_helium_line_cost():
    assert build._notes(BuildStats(), []) == []
    assert build._notes(BuildStats(off_detector=1, helium_left_out=4, helium_planes=1), []) == [
        "1 listed exposure left out: the field centre is off the detector",
        (
            "4 exposures left out: the band covers 1.083 micron, where a bright foreground is not flat "
            "across the field"
        ),
        (
            "1 plane near 1.08 micron made only of exposures whose band covers the bright foreground at "
            "1.083 micron: the background there is not flat"
        ),
    ]


def test_core_near_centre_looks_only_within_fifteen_arcsec_and_tells_blank_from_overflow():
    """A blank core (no value) is "saturated"; OVERFLOW on pixels that have values is "indicative only"
    (regression: the warning fired as "saturated" on the OVERFLOW flag alone, also where no pixel was
    blank, as for RW Aur)."""
    half = 20
    synthetic_image = np.ones((2 * half + 1, 2 * half + 1), dtype=np.float32)
    synthetic_flags = np.zeros(synthetic_image.shape, dtype=np.int32)

    def cut(flags, image=synthetic_image):
        return Cutout(
            exposure=synthetic_exposure("A_0001", 5, 60800.0), image=image, flags=flags, x0=0, y0=0,
            wcs_header="", lam=4.0, dlam=0.04, mjd=60800.0, psf_fwhm=8.0,
        )  # fmt: skip

    assert build._core_near_centre(cut(None)) is None
    assert build._core_near_centre(cut(synthetic_flags)) is None
    radius_px = 15.0 / NATIVE_PIXSCALE_ARCSEC  # 2.44 native pixels
    for offset, near in [
        ((0, 0), True),
        ((2, 1), True),
        ((0, 2), True),
        ((2, 2), False),
        ((0, 3), False),
    ]:
        assert (math.hypot(*offset) <= radius_px) is near
        row, col = half + offset[0], half + offset[1]
        flags = synthetic_flags.copy()
        flags[row, col] = bit_mask(OVERFLOW)
        # OVERFLOW on a pixel that has a value: measured, indicative only
        assert build._core_near_centre(cut(flags)) == (build.CORE_OVERFLOW if near else None)
        # the same core with its pixel blank: saturated
        synthetic_blank = synthetic_image.copy()
        synthetic_blank[row, col] = np.nan
        assert build._core_near_centre(cut(flags, synthetic_blank)) == (build.CORE_BLANK if near else None)
    # a blank core outside the radius and an overflowing pixel inside it: indicative only, not saturated
    flags = synthetic_flags.copy()
    flags[half, half + 3] = flags[half, half] = bit_mask(OVERFLOW)
    synthetic_blank = synthetic_image.copy()
    synthetic_blank[half, half + 3] = np.nan
    assert build._core_near_centre(cut(flags, synthetic_blank)) == build.CORE_OVERFLOW
    # a pixel without a value and without any flag is not a saturated core (off the detector, for example)
    synthetic_hole = synthetic_image.copy()
    synthetic_hole[half, half] = np.nan
    assert build._core_near_centre(cut(synthetic_flags, synthetic_hole)) is None


# ---------------------------------------------------------------------------- the stages, no network
SYNTHETIC_HEADER = "\n".join(
    [
        "NAXIS   =                    2",
        "NAXIS1  =                 2040",
        "NAXIS2  =                 2040",
        "WCSAXES =                    2",
        "CTYPE1  = 'RA---TAN'",
        "CTYPE2  = 'DEC--TAN'",
        "CRPIX1  =               1000.0",
        "CRPIX2  =               1000.0",
        f"CRVAL1  = {RA!r}",
        f"CRVAL2  = {DEC!r}",
        "CUNIT1  = 'deg'",
        "CUNIT2  = 'deg'",
        f"CD1_1   = {-NATIVE_PIXSCALE_ARCSEC / 3600.0!r}",
        "CD1_2   =                  0.0",
        "CD2_1   =                  0.0",
        f"CD2_2   = {NATIVE_PIXSCALE_ARCSEC / 3600.0!r}",
    ]
)


def synthetic_cutout(exposure: Exposure, half: int, lam: float) -> Cutout:
    """A window centred on the field centre: flat sky plus noise and one blob on the centre."""
    side = 2 * half + 1
    rng = np.random.default_rng(abs(hash(exposure.uid)) % (2**32))
    rows, cols = np.indices((side, side), dtype=np.float64)
    synthetic_blob = 2.0 * np.exp(-((rows - half) ** 2 + (cols - half) ** 2) / (2 * 1.2**2))
    synthetic_image = (0.3 + rng.normal(0.0, 0.01, (side, side)) + synthetic_blob).astype(np.float32)
    return Cutout(
        exposure=exposure,
        image=synthetic_image,
        flags=np.zeros((side, side), dtype=np.int32),
        x0=999 - half,  # FITS pixel 1000 is 0-based detector pixel 999: the field centre
        y0=999 - half,
        wcs_header=SYNTHETIC_HEADER,
        lam=lam,
        dlam=0.04,
        mjd=exposure.mjd,
        psf_fwhm=8.0,
        zodi_level=0.3,
        sky_var=1e-4,
        version="l2b-v27-2026-197",
    )


SYNTHETIC_LAM = {1: 0.9, 2: 1.3, 3: 2.0, 4: 3.0, 5: 4.1, 6: 4.7}


def _patch_archive(monkeypatch, exposures, *, fail=(), late=(), off=()):
    """Replace discovery and the reader of the build module by ones that serve synthetic cutouts."""
    calls = {"discover": [], "read": []}

    def fake_discover(ra, dec, *, deadline=None, **_):
        calls["discover"].append((ra, dec))
        return list(exposures)

    def fake_read_windows(exps, ra, dec, half_px, *, workers, deadline=None, progress=None, **_):
        exps = list(exps)
        calls["read"].append((len(exps), ra, dec, half_px, workers))
        cutouts, failures = [], []
        for done, exposure in enumerate(exps, start=1):
            if exposure.uid in fail:
                failures.append((exposure, "upstream: gave up after 8 attempts"))
            elif exposure.uid in late:
                failures.append((exposure, remote_fits.DEADLINE))
            elif exposure.uid in off:
                failures.append((exposure, remote_fits.OFF_DETECTOR))
            else:
                cutouts.append(synthetic_cutout(exposure, half_px, SYNTHETIC_LAM[exposure.det]))
            if progress is not None:
                progress(done, len(exps))
        return cutouts, failures

    monkeypatch.setattr(build, "discover", fake_discover)
    monkeypatch.setattr(build.remote_fits, "read_windows", fake_read_windows)
    return calls


def test_build_runs_the_stages_in_order(monkeypatch):
    synthetic = synthetic_exposures({(0, 5): 8, (0, 6): 8, (1, 5): 9, (1, 6): 9})
    calls = _patch_archive(monkeypatch, synthetic)
    seen: list[tuple[str, int, int]] = []
    manifest, frames, stats = build_field_with_stats(
        RA + 0.00003, DEC, 3, progress=lambda *step: seen.append(step)
    )

    assert calls["discover"] == [(RA, DEC)]  # the snapped centre, not the raw request
    assert calls["read"] == [(34, RA, DEC, native_half_window(3), 16)]
    stages = [stage for stage, _, _ in seen]
    assert stages == sorted(stages, key=["discover", "fetch", "stack"].index)
    assert seen[0] == ("discover", 0, 1) and ("fetch", 34, 34) in seen and seen[-1] == ("stack", 34, 34)

    assert manifest.status == "ready" and manifest.warnings == []
    assert manifest.exposures.found == 34 and manifest.exposures.used == 34 and not manifest.exposures.sampled
    assert [(b.id, b.n_exposures, b.detectors) for b in manifest.time_bins] == [
        (0, 16, [5, 6]),
        (1, 18, [5, 6]),
    ]
    wave_bins = {presets.wave_bin_for(5, 4.1), presets.wave_bin_for(6, 4.7)}
    assert {(p.time_bin, p.wave_bin) for p in manifest.planes} == {(t, w) for t in (0, 1) for w in wave_bins}
    assert sum(p.n_exposures for p in manifest.planes) == 34
    assert manifest.key == field_key(RA, DEC, 3, [e.uid for e in synthetic])
    assert manifest.frames.nbytes == len(frames) == 4 * 59 * 59 * 2
    assert manifest.frames.sha256 == sha256_hex(frames)
    assert "SPHEREx Level-2 processing: l2b-v27" in manifest.provenance.notes

    # the synthetic blob sits on the centre pixel of every plane: registration put it where the grid says
    for plane in decode_planes(frames, 4, 59, 59):
        assert np.unravel_index(np.nanargmax(plane), plane.shape) == (29, 29)

    assert (stats.found, stats.selected, stats.read, stats.used, stats.planes) == (34, 34, 34, 34, 4)
    assert stats.key == manifest.key and stats.status == "ready"
    assert set(stats.seconds) == {"discover", "fetch", "stack", "total"}
    assert stats.newest_found_mjd == max(e.mjd for e in synthetic)

    # the same exposures again give the same key and the same bytes
    again, frames_again = build_field(RA, DEC, 3)
    assert again.key == manifest.key and frames_again == frames


def test_build_of_an_uncovered_position_is_empty(monkeypatch):
    _patch_archive(monkeypatch, [])
    manifest, frames = build_field(10.0, 20.0, 6)
    assert manifest.status == "empty" and frames == b""
    assert manifest.planes == [] and manifest.frames is None and manifest.exposures.found == 0
    assert manifest.centre.model_dump() == {"ra": 10.0, "dec": 20.0}


def test_build_samples_beyond_the_limit(monkeypatch):
    synthetic = synthetic_exposures({(0, 5): 20, (0, 6): 20, (1, 5): 20})
    calls = _patch_archive(monkeypatch, synthetic)
    manifest, _ = build_field(RA, DEC, 3, max_exposures=30)
    assert calls["read"][0][0] == 30
    assert manifest.exposures.model_dump() | {"newest_mjd": 0, "newest_date": ""} == {
        "found": 60, "used": 30, "sampled": True, "collections": {"spherex_dr1": 30},
        "newest_mjd": 0, "newest_date": "",
    }  # fmt: skip
    assert [b.n_exposures for b in manifest.time_bins] == [20, 10]


def test_build_reports_failed_downloads_and_exposures_off_the_detector(monkeypatch):
    synthetic = synthetic_exposures({(0, 5): 10, (0, 6): 10})
    fail = {synthetic[0].uid, synthetic[1].uid, synthetic[2].uid}
    off = {synthetic[3].uid}
    _patch_archive(monkeypatch, synthetic, fail=fail, off=off)
    manifest, _, stats = build_field_with_stats(RA, DEC, 3)
    assert manifest.status == "ready"
    assert manifest.exposures.found == 20 and manifest.exposures.used == 16
    assert manifest.warnings[0] == "3 exposures failed to download"
    assert "1 listed exposure left out: the field centre is off the detector" in manifest.provenance.notes
    assert (stats.failed, stats.off_detector, stats.timed_out) == (3, 1, 0)
    used = [e.uid for e in synthetic if e.uid not in fail | off]
    assert manifest.key == field_key(RA, DEC, 3, used)  # the key names what is in the frames


def test_build_past_the_deadline_is_partial(monkeypatch):
    synthetic = synthetic_exposures({(0, 5): 10, (0, 6): 10})
    late = {e.uid for e in synthetic[12:]}
    _patch_archive(monkeypatch, synthetic, late=late)
    manifest, frames, stats = build_field_with_stats(RA, DEC, 3, deadline_s=120.0)
    assert manifest.status == "partial" and len(frames) > 0
    assert manifest.warnings[0] == "build stopped at the 120 s deadline: 12 of 20 exposures were read"
    assert manifest.exposures.used == 12 and stats.timed_out == 8


def _blank(cut: Cutout) -> Cutout:
    """The same synthetic cutout with every pixel flagged as a non-functional one: nothing usable in it."""
    cut.flags = np.full(cut.image.shape, bit_mask(6), dtype=np.int32)  # bit 6 is NONFUNC
    return cut


def test_time_bins_come_from_every_exposure_that_was_read():
    """An exposure that is read but unusable still holds its visit together (Contract section 3)."""
    grid = Grid.for_field(RA, DEC, 3)
    half = native_half_window(3)
    synthetic_first = synthetic_cutout(synthetic_exposure("A_0001", 5, 60800.0), half, 4.1)
    synthetic_bridge = _blank(synthetic_cutout(synthetic_exposure("A_0002", 5, 60815.0), half, 4.1))
    synthetic_last = synthetic_cutout(synthetic_exposure("A_0003", 5, 60830.0), half, 4.1)

    items, unusable, saturated = build.register_cutouts(
        [synthetic_first, synthetic_bridge, synthetic_last], grid
    )
    assert (len(items), unusable, saturated) == (2, 1, 0)
    assert [item.time_bin for item in items] == [0, 0]  # 15-day steps: one visit, although 30 days apart

    items, unusable, _ = build.register_cutouts([synthetic_first, synthetic_last], grid)
    assert [item.time_bin for item in items] == [0, 1] and unusable == 0  # without the bridge: two visits


def test_time_bins_without_a_usable_exposure_are_dropped_and_renumbered():
    grid = Grid.for_field(RA, DEC, 3)
    half = native_half_window(3)
    synthetic_cutouts = [
        synthetic_cutout(synthetic_exposure("A_0001", 5, 60800.0), half, 4.1),
        _blank(
            synthetic_cutout(synthetic_exposure("B_0001", 5, 60900.0), half, 4.1)
        ),  # a visit with nothing usable
        synthetic_cutout(synthetic_exposure("C_0001", 6, 61000.0), half, 4.7),
    ]
    seen: list[tuple[str, int, int]] = []
    items, unusable, _ = build.register_cutouts(synthetic_cutouts, grid, lambda *step: seen.append(step))
    assert [item.time_bin for item in items] == [0, 1] and unusable == 1
    assert [item.exposure.obs_id for item in items] == ["A_0001", "C_0001"]
    assert seen == [("stack", 3, 3)]
    assert build.register_cutouts([], grid) == ([], 0, 0)


# ------------------------------------------------------------------------------- the helium line
def test_the_helium_line_is_seen_within_one_bandwidth():
    """Wavelengths and bandwidths (micron) of real exposures of the WISE 0855 field, with what was measured
    in them: a foreground changing by 23 to 128 times the noise across the window, or a flat one."""
    structured = [(1.064, 0.028), (1.065, 0.029), (1.089, 0.029), (1.091, 0.029), (1.101, 0.025)]
    flat = [(1.039, 0.028), (1.041, 0.028), (1.115, 0.029), (1.111, 0.026), (1.127, 0.026), (1.137, 0.027)]
    assert all(sees_helium_line(lam, dlam) for lam, dlam in structured)
    assert not any(sees_helium_line(lam, dlam) for lam, dlam in flat)
    assert not sees_helium_line(4.5, 0.04) and not sees_helium_line(1.08, float("nan"))


def _helium_case():
    """Cutouts of detector 1 in two visits; every one falls in wave bin 3 (1.023 to 1.116 micron)."""
    half = native_half_window(3)
    synthetic_cutouts = []
    for obs_id, mjd, lam in [
        ("A_0001", 60800.0, 1.041),
        ("A_0002", 60800.1, 1.065),  # sees the line
        ("A_0003", 60800.2, 1.089),  # sees the line
        ("B_0001", 60900.0, 1.091),  # sees the line, and is all this visit has in the wave bin
        ("B_0002", 60900.1, 0.900),  # another wave bin of the same visit
    ]:
        cut = synthetic_cutout(synthetic_exposure(obs_id, 1, mjd), half, lam)
        cut.dlam = 0.029
        synthetic_cutouts.append(cut)
    return synthetic_cutouts


def test_exposures_that_see_the_helium_line_are_left_out_where_the_plane_has_others():
    grid = Grid.for_field(RA, DEC, 3)
    synthetic_cutouts = _helium_case()
    items, unusable, _ = build.register_cutouts(synthetic_cutouts, grid)
    assert unusable == 0 and [(i.time_bin, i.wave_bin) for i in items] == [
        (0, 3),
        (0, 3),
        (0, 3),
        (1, 3),
        (1, 1),
    ]
    kept, left_out, alone = leave_out_helium(items, synthetic_cutouts)
    assert [item.exposure.obs_id for item in kept] == ["A_0001", "B_0001", "B_0002"]
    assert (left_out, alone) == (2, 1)
    # no plane is lost: the wave bins of a time bin are what they were, so no frame turns "partial"
    assert {(i.time_bin, i.wave_bin) for i in kept} == {(i.time_bin, i.wave_bin) for i in items}
    assert leave_out_helium([], []) == ([], 0, 0)
    assert leave_out_helium(items[4:], synthetic_cutouts) == (items[4:], 0, 0)


def test_build_leaves_out_helium_exposures_and_says_so(monkeypatch):
    synthetic_cutouts = _helium_case()
    exposures = [cut.exposure for cut in synthetic_cutouts]
    monkeypatch.setattr(build, "discover", lambda ra, dec, **_: list(exposures))
    monkeypatch.setattr(
        build.remote_fits, "read_windows", lambda exps, *args, **kwargs: (list(synthetic_cutouts), [])
    )
    manifest, _, stats = build_field_with_stats(RA, DEC, 3)
    assert (stats.read, stats.used, stats.helium_left_out, stats.helium_planes) == (5, 3, 2, 1)
    assert manifest.exposures.found == 5 and manifest.exposures.used == 3
    assert [(p.time_bin, p.wave_bin, p.n_exposures) for p in manifest.planes] == [
        (0, 3, 1),
        (1, 1, 1),
        (1, 3, 1),
    ]
    assert manifest.key == field_key(RA, DEC, 3, ["A_0001/D1", "B_0001/D1", "B_0002/D1"])
    assert manifest.provenance.notes[-2].startswith("2 exposures left out: the band covers 1.083 micron")
    assert manifest.provenance.notes[-1].startswith("1 plane near 1.08 micron made only of exposures")


def test_build_with_nothing_readable_is_an_upstream_error(monkeypatch):
    synthetic = synthetic_exposures({(0, 5): 4})
    _patch_archive(monkeypatch, synthetic, fail={e.uid for e in synthetic})
    with pytest.raises(http.UpstreamError, match="none of the 4 exposures could be read"):
        build_field(RA, DEC, 3)


def test_build_with_every_exposure_off_the_detector_is_empty(monkeypatch):
    synthetic = synthetic_exposures({(0, 5): 4})
    _patch_archive(monkeypatch, synthetic, off={e.uid for e in synthetic})
    manifest, frames = build_field(RA, DEC, 3)
    assert manifest.status == "empty" and frames == b""
    assert manifest.exposures.found == 4 and manifest.exposures.used == 0


def test_build_stops_before_reading_when_the_field_is_already_known(monkeypatch):
    synthetic = synthetic_exposures({(0, 5): 6})
    calls = _patch_archive(monkeypatch, synthetic)
    expected = field_key(RA, DEC, 3, [e.uid for e in synthetic])
    asked: list[str] = []
    with pytest.raises(AlreadyBuilt) as raised:
        build_field(RA, DEC, 3, known=lambda key: asked.append(key) or True)
    assert raised.value.key == expected and asked == [expected]
    assert calls["read"] == []
    manifest, _ = build_field(RA, DEC, 3, known=lambda key: False)
    assert manifest.key == expected and len(calls["read"]) == 1


def test_listing_key_is_over_the_selected_exposures_and_the_key_over_those_used(monkeypatch):
    synthetic = synthetic_exposures({(0, 5): 8, (0, 6): 8})
    off = {synthetic[3].uid}
    _patch_archive(monkeypatch, synthetic, off=off)
    asked: list[str] = []
    manifest, _, stats = build_field_with_stats(RA, DEC, 3, known=lambda key: asked.append(key) or False)
    assert stats.listing_key == field_key(RA, DEC, 3, [e.uid for e in synthetic]) and asked == [
        stats.listing_key
    ]
    assert manifest.key == field_key(RA, DEC, 3, [e.uid for e in synthetic if e.uid not in off])
    assert manifest.key != stats.listing_key  # which is why a stored key cannot answer `known`


def _run_to_the_end(builder: Builder, name: str) -> None:
    """Start the build of a request on the queue and poll it until the queue is empty."""
    assert builder.start(name, RA, DEC, 3) is not None
    for _ in range(4000):
        if builder.counts() == (0, 0):
            return
        builder.poll(name)
        time.sleep(0.005)
    raise AssertionError("the build did not finish")


def test_an_expired_field_with_an_unused_listed_exposure_is_not_read_again(monkeypatch, tmp_path):
    """Regression: 16 listed exposures, 1 off the detector. After the 24-hour expiry of the request index
    the archive lists the same 16; the 15 usable ones must not be downloaded and stacked a second time."""
    synthetic = synthetic_exposures({(0, 5): 8, (0, 6): 8})
    calls = _patch_archive(monkeypatch, synthetic, off={synthetic[3].uid})
    now = [1_000_000.0]
    cache = FieldCache(tmp_path / "cache", max_mb=50, clock=lambda: now[0])
    builder = Builder(lambda: cache, build_field_with_stats)
    name = request_id(RA, DEC, 3)

    _run_to_the_end(builder, name)
    key = cache.lookup(RA, DEC, 3)
    assert key is not None and calls["read"] == [(16, RA, DEC, native_half_window(3), 16)]
    assert json.loads(cache.get_manifest(key))["exposures"]["used"] == 15

    now[0] += REQUEST_TTL_S + 1.0
    assert cache.lookup(RA, DEC, 3) is None  # expired: the next request asks the archive again
    _run_to_the_end(builder, name)
    assert len(calls["discover"]) == 2 and len(calls["read"]) == 1  # listed again, nothing read again
    assert cache.lookup(RA, DEC, 3) == key  # the same field answers for another 24 hours

    # a seventeenth exposure in the listing is another listing: now the field is built again
    newer = synthetic + [synthetic_exposure("V0_9999", 6, 60800.5)]
    monkeypatch.setattr(build, "discover", lambda ra, dec, **_: list(newer))
    now[0] += REQUEST_TTL_S + 1.0
    _run_to_the_end(builder, name)
    assert len(calls["read"]) == 2 and calls["read"][1][0] == 17
    assert cache.lookup(RA, DEC, 3) not in (None, key)


def test_a_build_with_a_failed_download_does_not_stop_the_next_one(monkeypatch, tmp_path):
    """The shortcut is for complete builds only: a listing that was not read whole is read again."""
    synthetic = synthetic_exposures({(0, 5): 8, (0, 6): 8})
    calls = _patch_archive(monkeypatch, synthetic, fail={synthetic[5].uid})
    now = [1_000_000.0]
    cache = FieldCache(tmp_path / "cache", max_mb=50, clock=lambda: now[0])
    builder = Builder(lambda: cache, build_field_with_stats)
    name = request_id(RA, DEC, 3)
    _run_to_the_end(builder, name)
    assert len(calls["read"]) == 1 and cache.lookup(RA, DEC, 3) is not None
    now[0] += REQUEST_TTL_S + 1.0
    _run_to_the_end(builder, name)
    assert len(calls["read"]) == 2  # not skipped: the failed exposure deserves another try


def test_build_is_cancelled_by_an_exception_from_progress(monkeypatch):
    synthetic = synthetic_exposures({(0, 5): 6})
    _patch_archive(monkeypatch, synthetic)

    class Stop(Exception):
        pass

    def progress(stage, done, total):
        if stage == "fetch" and done == 3:
            raise Stop

    with pytest.raises(Stop):
        build_field(RA, DEC, 3, progress=progress)


@pytest.mark.parametrize("fov", [7, 0, 6.5, 12, -3])
def test_build_refuses_a_field_of_view_outside_the_allowed_set(fov):
    with pytest.raises(ValueError, match="fov_arcmin"):
        build_field(RA, DEC, fov)


def test_build_refuses_a_position_out_of_range():
    with pytest.raises(ValueError):
        build_field(10.0, 91.0, 6)
    with pytest.raises(ValueError):
        build_field(math.nan, 0.0, 6)


# ------------------------------------------------------------------- older-survey (legacy) planes, no network
def synthetic_legacy_plane(grid: Grid, band: str, gain: float | None, level: float) -> legacy.LegacyPlane:
    """A legacy plane as tombaugh.legacy returns one, with synthetic pixels (the real ones need IRSA)."""
    synthetic_data = np.full(grid.shape, level, dtype=np.float32)
    synthetic_data[0, :] = np.nan  # a strip the survey does not cover
    mission = legacy.mission_of(band)
    label = f"{mission} {band}"
    warnings = [] if gain is not None else [
        f"{label}: not scaled on field stars (3 usable field stars in common, 5 needed); values in DN."
    ]  # fmt: skip
    return legacy.LegacyPlane(
        mission=mission, band=band, data=synthetic_data, unit="DN" if gain is None else "MJy/sr (matched)",
        native_unit="DN", gain=gain, n_stars=0 if gain is None else 7, sigma=0.02, lam_min=4.10, lam_max=5.16,
        lam_eff=4.618, n_exposures=26, mjd_min=55319.5, mjd_max=55513.5, coverage=0.99,
        images=["1342m076_ac51"], resolution_arcsec=6.4, notes=[f"{label}: a note"], warnings=warnings,
    )  # fmt: skip


class SyntheticOlderSurveys:
    """Stands in for legacy.build_legacy_planes: records what it was given, returns `planes` and `warnings`."""

    def __init__(self, planes=(), warnings=(), error: Exception | None = None, hang: bool = False):
        self.planes, self.warnings, self.error, self.hang = list(planes), list(warnings), error, hang
        self.calls: list[tuple] = []
        self.references: dict[str, np.ndarray | None] = {}

    def __call__(self, grid, bands, *, references=None, deadline=None):
        self.calls.append((grid, tuple(bands)))
        if self.hang:  # an archive that never answers: wait until the build gives up on us
            while not deadline.expired:
                time.sleep(0.01)
        if self.error is not None:
            raise self.error
        for plane in self.planes:
            self.references[plane.band] = references(plane.band)
        result_warnings = self.warnings + [w for plane in self.planes for w in plane.warnings]
        return legacy.LegacyResult(
            planes=self.planes, warnings=result_warnings, seconds=0.5, bytes_downloaded=0, requests=0
        )


def test_build_appends_scaled_legacy_planes_after_the_spherex_planes(monkeypatch):
    synthetic = synthetic_exposures({(0, 5): 8, (0, 6): 8, (1, 5): 9, (1, 6): 9})
    _patch_archive(monkeypatch, synthetic)
    grid = Grid.for_field(RA, DEC, 3)
    older = SyntheticOlderSurveys(
        [synthetic_legacy_plane(grid, "W2", 0.07, 0.25), synthetic_legacy_plane(grid, "Ks", None, 9.0)]
    )
    monkeypatch.setattr(build.legacy, "build_legacy_planes", older)
    manifest, frames, stats = build_field_with_stats(RA, DEC, 3, legacy_bands=("W2", "Ks"))

    assert older.calls == [(grid, ("W2", "Ks"))]
    # the paired SPHEREx frame (presets.json legacy_pairs) was handed over once the stacks existed
    assert older.references["W2"] is not None and older.references["W2"].shape == grid.shape
    assert np.isfinite(older.references["W2"]).any()

    sci = [p for p in manifest.planes if p.kind == "sci"]
    assert len(sci) == 4 and [p.index for p in sci] == [0, 1, 2, 3]
    [w2] = [p for p in manifest.planes if p.kind == "legacy"]  # Ks could not be scaled: left out
    assert w2.model_dump() == {
        "index": 4, "kind": "legacy", "mission": "AllWISE", "time_bin": None, "wave_bin": None, "band": "W2",
        "lam_min": 4.1, "lam_max": 5.16, "lam_eff": 4.618, "n_exposures": 26, "sigma": 0.02,
        "mjd_mid": 55416.5, "date_start": "2010-05-03", "date_end": "2010-11-13", "offset": 4 * 59 * 59 * 2,
        "scaled": "field_stars",
    }  # fmt: skip
    assert manifest.frames.nbytes == len(frames) == 5 * 59 * 59 * 2
    decoded = decode_planes(frames, 5, 59, 59)
    assert np.isnan(decoded[4][0]).all() and np.allclose(decoded[4][1:], 0.25, atol=1e-3)
    assert manifest.key == field_key(RA, DEC, 3, [e.uid for e in synthetic])  # legacy planes never enter it
    assert "2MASS Ks: plane left out: its brightness could not be matched to SPHEREx on field stars." in (
        manifest.warnings
    )
    assert not any("values in DN" in warning for warning in manifest.warnings)
    assert "AllWISE W2: a note" in manifest.provenance.notes
    assert "2MASS Ks: a note" not in manifest.provenance.notes
    assert (stats.legacy_planes, stats.legacy_left_out, stats.legacy_incomplete) == (1, 1, False)
    assert stats.seconds["legacy"] == 0.5
    Manifest.model_validate(json.loads(manifest.model_dump_json()))
    assert "exposures" not in stats.as_log() and len(stats.exposures) == 34


def test_a_failing_legacy_step_never_fails_the_field(monkeypatch):
    synthetic = synthetic_exposures({(0, 5): 8, (0, 6): 8})
    _patch_archive(monkeypatch, synthetic)
    monkeypatch.setattr(build.legacy, "build_legacy_planes", SyntheticOlderSurveys(error=RuntimeError("bug")))
    manifest, frames, stats = build_field_with_stats(RA, DEC, 3, legacy_bands=legacy.LEGACY_BANDS)
    assert manifest.status == "ready" and all(p.kind == "sci" for p in manifest.planes)
    assert len(frames) == len(manifest.planes) * 59 * 59 * 2
    assert "older-survey planes (AllWISE, 2MASS) could not be made (RuntimeError)" in manifest.warnings
    assert stats.legacy_incomplete and stats.legacy_planes == 0


@pytest.mark.parametrize(
    ("warning", "incomplete"),
    [
        ("AllWISE: archive unavailable (UpstreamError: gave up after 6 attempts: HTTP 502); no AllWISE plane.", True),
        ("2MASS Ks: 1 image(s) not read (ki0940209: UpstreamError: HTTP 503).", True),
        ("2MASS Ks: no image of the archive covers this field.", False),
        ("AllWISE W1: 12% of the field has no data from the survey.", False),
    ],
)  # fmt: skip
def test_only_an_upstream_failure_of_the_older_surveys_asks_for_an_early_rebuild(
    monkeypatch, warning, incomplete
):
    synthetic = synthetic_exposures({(0, 5): 8, (0, 6): 8})
    _patch_archive(monkeypatch, synthetic)
    monkeypatch.setattr(build.legacy, "build_legacy_planes", SyntheticOlderSurveys(warnings=[warning]))
    manifest, _, stats = build_field_with_stats(RA, DEC, 3, legacy_bands=("W1", "Ks"))
    assert warning in manifest.warnings and stats.legacy_incomplete is incomplete


def test_older_surveys_are_not_waited_for_past_the_build_deadline(monkeypatch):
    synthetic = synthetic_exposures({(0, 5): 8, (0, 6): 8})
    _patch_archive(monkeypatch, synthetic)
    older = SyntheticOlderSurveys(hang=True)
    monkeypatch.setattr(build.legacy, "build_legacy_planes", older)
    started = time.monotonic()
    manifest, _, stats = build_field_with_stats(RA, DEC, 3, deadline_s=6.0, legacy_bands=("W2",))
    assert time.monotonic() - started < 4.0
    assert manifest.status == "ready" and stats.legacy_incomplete
    assert (
        "older-survey planes (AllWISE, 2MASS) were not ready before the build's deadline" in manifest.warnings
    )


def test_legacy_bands_are_checked_before_anything_is_sent(monkeypatch):
    calls = _patch_archive(monkeypatch, synthetic_exposures({(0, 5): 8}))
    with pytest.raises(KeyError):
        build_field_with_stats(RA, DEC, 3, legacy_bands=("W3",))
    assert calls["discover"] == []


def test_an_uncovered_field_asks_no_older_survey(monkeypatch):
    _patch_archive(monkeypatch, [])
    older = SyntheticOlderSurveys()
    monkeypatch.setattr(build.legacy, "build_legacy_planes", older)
    manifest, frames, _ = build_field_with_stats(10.0, 20.0, 6, legacy_bands=legacy.LEGACY_BANDS)
    assert manifest.status == "empty" and frames == b"" and older.calls == []


def test_a_legacy_plane_that_cannot_be_described_is_left_out():
    grid = Grid.for_field(RA, DEC, 3)
    synthetic_broken = synthetic_legacy_plane(grid, "W1", 0.05, 0.3)
    synthetic_broken.sigma = float("nan")
    result = legacy.LegacyResult([synthetic_broken], [], 0.1, 0, 0)
    outcome = build.keep_legacy_planes(result, grid)
    assert outcome.planes == [] and outcome.left_out == 1
    assert outcome.warnings == ["AllWISE W1: plane left out: its description is not valid (ValidationError)."]


def test_the_service_build_asks_for_every_legacy_band(monkeypatch):
    seen = {}
    monkeypatch.setattr(build, "build_field_with_stats", lambda *a, **k: seen.update(k) or "built")
    assert build.build_field_for_service(RA, DEC, 3, deadline_s=10.0) == "built"
    assert seen == {"legacy_bands": legacy.LEGACY_BANDS, "deadline_s": 10.0}
    assert legacy.LEGACY_BANDS == ("W1", "W2", "J", "H", "Ks")


def test_the_builder_keeps_the_exposure_list_and_rebuilds_soon_after_an_older_survey_failure(
    monkeypatch, tmp_path
):
    synthetic = synthetic_exposures({(0, 5): 8, (0, 6): 8})
    _patch_archive(monkeypatch, synthetic)
    monkeypatch.setattr(
        build.legacy,
        "build_legacy_planes",
        SyntheticOlderSurveys(
            warnings=["AllWISE: archive unavailable (UpstreamError: x); no AllWISE plane."]
        ),
    )
    now = [1_000_000.0]
    cache = FieldCache(tmp_path / "cache", max_mb=50, clock=lambda: now[0])
    builder = Builder(lambda: cache, build.build_field_for_service)
    _run_to_the_end(builder, request_id(RA, DEC, 3))
    key = cache.lookup(RA, DEC, 3)
    assert key is not None
    stored = spectra.exposures_from_json(gzip.decompress(cache.get_derived(key, main.EXPOSURES_NAME)))
    assert [e.uid for e in stored] == [
        e.uid for e in sorted(synthetic, key=lambda e: (e.mjd, e.det, e.obs_id))
    ]
    entry = cache._requests[request_id(RA, DEC, 3)]
    assert "listing" not in entry  # incomplete: the next request after 10 minutes builds again
    assert now[0] - entry["at"] == pytest.approx(REQUEST_TTL_S - main.RETRY_INCOMPLETE_S)


def test_legacy_planes_are_scaled_even_when_the_spherex_reads_outlast_their_request_deadline(monkeypatch):
    """Regression (live, RW Aur field, 14 Nov 2026): the SPHEREx reads took 55 s, longer than the older
    surveys' 60 s request deadline, so their wait for the paired frames timed out and all five planes were
    left out as unscaled. The wait is now bounded by the build's deadline."""
    synthetic = synthetic_exposures({(0, 5): 8, (0, 6): 8})
    _patch_archive(monkeypatch, synthetic)
    reader = build.remote_fits.read_windows

    def slow_read_windows(*args, **kwargs):
        time.sleep(1.0)  # longer than the request deadline below
        return reader(*args, **kwargs)

    monkeypatch.setattr(build.remote_fits, "read_windows", slow_read_windows)
    monkeypatch.setattr(build, "LEGACY_DEADLINE_S", 0.3)
    grid = Grid.for_field(RA, DEC, 3)
    older = SyntheticOlderSurveys([synthetic_legacy_plane(grid, "W2", 0.07, 0.25)])
    monkeypatch.setattr(build.legacy, "build_legacy_planes", older)
    manifest, _, stats = build_field_with_stats(RA, DEC, 3, legacy_bands=("W2",))
    assert older.references["W2"] is not None
    assert stats.legacy_planes == 1 and [p.band for p in manifest.planes if p.kind == "legacy"] == ["W2"]
