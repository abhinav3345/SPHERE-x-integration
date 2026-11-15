"""Tests of tombaugh.photometry: quick-look spectrophotometry (Contract v1.0, section 7.1).

The offline tests replay real windows recorded by tests/data/photometry/record_samples.py (see the README there).
Tests of pure maths use small synthetic arrays named synthetic_*. Tests that need the archive carry "network".
"""

from __future__ import annotations

import json
import math
import zlib
from pathlib import Path

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.wcs import WCS

from tombaugh import http, presets
from tombaugh import photometry as ph
from tombaugh.models import SnappedTo, SpectrumResponse, TimeBin
from tombaugh.tools.make_fixture import propagate
from tombaugh.types import Cutout, Exposure

DATA = Path(__file__).parent / "data" / "photometry"


# --------------------------------------------------------------------------------------------- recorded data
@pytest.fixture(scope="module")
def recorded() -> dict[str, list[Cutout]]:
    meta = json.loads((DATA / "windows.json").read_text())
    arrays = np.load(DATA / "windows.npz")
    sets: dict[str, list[Cutout]] = {}
    for i, m in enumerate(meta):
        header = zlib.decompress(arrays[f"header_{i}"].tobytes()).decode("ascii")
        cut = Cutout(
            exposure=Exposure(**m["exposure"]),
            image=arrays[f"image_{i}"],
            flags=arrays[f"flags_{i}"],
            x0=m["x0"],
            y0=m["y0"],
            wcs_header=header,
            lam=m["lam"],
            dlam=m["dlam"],
            mjd=m["mjd"],
            psf_fwhm=m["psf_fwhm"],
            zodi_level=m["zodi_level"],
            sky_var=m["sky_var"],
            version=m["version"],
        )
        sets.setdefault(m["set"], []).append(cut)
    return sets


@pytest.fixture(scope="module")
def library(recorded) -> ph.PsfLibrary:
    psf = np.load(DATA / "psf.npz")
    lib = ph.PsfLibrary(fetch=None)
    tables = {}
    for name in psf.files:
        if name.startswith("zones_"):
            det = int(name.split("_")[1])
            stamps = np.full((len(psf[f"xcenter_{det}"]), ph.PSF_SIDE, ph.PSF_SIDE), np.nan)
            stamps[psf[f"zones_{det}"]] = psf[f"stamps_{det}"]
            tables[det] = ph.PsfTable(
                det=det,
                xcenter=psf[f"xcenter_{det}"],
                ycenter=psf[f"ycenter_{det}"],
                cwave=psf[f"cwave_{det}"],
                stamps=stamps,
            )
    for cuts in recorded.values():
        for cut in cuts:
            lib.put(ph.psf_key(cut.exposure), tables[cut.exposure.det])
    return lib


@pytest.fixture(scope="module")
def sets() -> dict:
    return json.loads((DATA / "sets.json").read_text())


def _source(entry: dict) -> ph.Source:
    keys = ("ra", "dec", "epoch", "pmra", "pmdec", "parallax", "catalog", "id")
    return ph.Source(**{k: entry[k] for k in keys if k in entry})


def _target(sets: dict, name: str) -> ph.Source:
    return _source(sets[name]["target"])


def _neighbours(sets: dict, name: str) -> list[ph.Source]:
    return [_source(n) for n in sets[name]["neighbours"]]


def _weighted_mean(points) -> tuple[float, float]:
    w = np.array([1.0 / p.err_ujy**2 for p in points])
    f = np.array([p.flux_ujy for p in points])
    return float((w * f).sum() / w.sum()), math.sqrt(1.0 / w.sum())


# ------------------------------------------------------------------------------------- science on real data
def test_wise0855_joint_fit_separates_the_neighbour(recorded, library, sets):
    response = ph.measure_cutouts(
        recorded["wise0855"],
        _target(sets, "wise0855"),
        neighbours=_neighbours(sets, "wise0855"),
        psf=library,
    )
    assert response.state == "ok"
    assert response.method.kind == "joint_psf"
    [neighbour] = response.neighbours
    assert neighbour.fitted and neighbour.id == "J085501.95-071428.2"
    assert 4.0 <= neighbour.sep_arcsec <= 11.0  # the plan's E6: 4 to 11 arcsec over the visits
    cold = [p for p in response.points if p.lam >= 4.4]
    warm = [p for p in response.points if p.lam < 2.5]
    assert len(cold) == 4 and len(warm) == 3
    flux, err = _weighted_mean(cold)
    assert 300.0 < flux < 800.0 and flux > 5.0 * err  # E7: about 600 microjansky at 4.4-4.8 micron
    for point in warm:  # below 3.8 micron only the neighbour shines; the target is consistent with zero
        # A point the photometry mask flags (here one with SUR_ERROR and HALO in the aperture, -239 +- 77) is
        # shown as flagged and kept out of `binned`; the good ones must agree with zero.
        assert abs(point.flux_ujy) < 3.0 * point.err_ujy or point.quality == "flagged"
    assert sum(p.quality == "good" for p in warm) >= 2


def test_wise0855_without_the_neighbour_fit_reports_its_light(recorded, library, sets):
    response = ph.measure_cutouts(recorded["wise0855"], _target(sets, "wise0855"), psf=library)
    assert response.state == "ok" and response.method.kind == "aperture"
    warm = [p for p in response.points if p.lam < 2.5]
    assert all(p.flux_ujy > 5.0 * p.err_ujy for p in warm)  # the star's light in the aperture


def test_close_neighbour_cannot_be_fitted_and_is_flagged(recorded, library, sets):
    target = _target(sets, "empty")
    close = ph.Source(ra=target.ra, dec=target.dec + 1.5 / 3600.0, catalog="catwise", id="synthetic_close")
    response = ph.measure_cutouts(recorded["empty"], target, neighbours=[close], psf=library)
    assert response.state == "contaminated"
    assert response.method.kind == "aperture"
    [neighbour] = response.neighbours
    assert not neighbour.fitted and neighbour.sep_arcsec == pytest.approx(1.5, abs=0.01)


def test_far_neighbours_are_ignored(recorded, library, sets):
    target = _target(sets, "empty")
    far = ph.Source(ra=target.ra, dec=target.dec + 20.0 / 3600.0, catalog="catwise", id="synthetic_far")
    response = ph.measure_cutouts(recorded["empty"], target, neighbours=[far], psf=library)
    assert response.neighbours == [] and response.method.kind == "aperture"


def test_barnard_saturated_core_gives_no_flux(recorded, library, sets):
    stats = ph.SpectrumStats()
    response = ph.measure_cutouts(recorded["barnard"], _target(sets, "barnard"), psf=library, stats=stats)
    assert response.state == "saturated"
    assert response.points == [] and response.binned == [] and response.time_span is None
    assert stats.skipped.get(ph.BLANK_CORE, 0) > len(recorded["barnard"]) / 2


def test_empty_sky_is_consistent_with_zero(recorded, library, sets):
    response = ph.measure_cutouts(recorded["empty"], _target(sets, "empty"), psf=library)
    assert response.state == "ok" and response.method.kind == "aperture"
    assert len(response.points) == 4
    for point in response.points:
        assert abs(point.flux_ujy) < 3.0 * point.err_ujy
        assert 0.0 < point.err_ujy < 500.0


def test_no_window_is_no_data(sets):
    response = ph.measure_cutouts([], _target(sets, "empty"), psf=ph.PsfLibrary(fetch=None))
    assert response.state == "no_data"
    assert response.points == [] and response.binned == [] and response.time_span is None


def test_points_follow_the_contract(recorded, library, sets):
    snapped = SnappedTo(catalog="catwise", id="J085510.74-071442.5", sep_arcsec=0.4)
    response = ph.measure_cutouts(
        recorded["wise0855"],
        _target(sets, "wise0855"),
        neighbours=_neighbours(sets, "wise0855"),
        snapped_to=snapped,
        psf=library,
    )
    assert response.target.snapped_to == snapped
    assert response.target.pmra == pytest.approx(-8123.7) and response.target.epoch == 2000.0
    assert response.method.radius_px == 2.0 and tuple(response.method.annulus_px) == (5.0, 9.0)
    assert response.method.systematic_floor == 0.03 and 0.9 < response.method.encircled_energy < 1.0
    for point in response.points:
        assert point.err_ujy >= 0.03 * abs(point.flux_ujy) - 0.01  # the floor is in quadrature
        assert point.quality in ("good", "flagged", "saturated")
        assert 0.7 < point.lam < 5.1 and point.dlam > 0.0
        assert point.det in (1, 2, 3, 6)
    mjds = [p.mjd for p in response.points]
    assert response.time_span.mjd_min == pytest.approx(min(mjds)) and response.time_span.mjd_max == max(mjds)
    text = response.model_dump_json()
    assert "NaN" not in text and SpectrumResponse.model_validate_json(text) == response


def test_binned_combines_good_points_per_visit_and_wave_bin(recorded, library, sets):
    response = ph.measure_cutouts(
        recorded["wise0855"],
        _target(sets, "wise0855"),
        neighbours=_neighbours(sets, "wise0855"),
        psf=library,
    )
    edges = {b.id: b for b in presets.wave_bins()}
    groups: dict[tuple[int, int], list] = {}
    for p in response.points:
        if p.quality == "good":
            groups.setdefault((p.time_bin, presets.wave_bin_for(p.det, p.lam)), []).append(p)
    assert len(response.binned) == len(groups)
    for b in response.binned:
        wave_bin = next(i for (t, i) in groups if t == b.time_bin and edges[i].lam_min == b.lam_min)
        members = groups[(b.time_bin, wave_bin)]
        assert b.n == len(members) and b.lam_max == edges[wave_bin].lam_max
        assert min(p.lam for p in members) <= b.lam <= max(p.lam for p in members)


def test_manifest_time_bins_name_the_points(recorded, library, sets):
    cuts = recorded["wise0855"]
    mjds = sorted(c.mjd for c in cuts)
    split = next(i for i in range(1, len(mjds)) if mjds[i] - mjds[i - 1] > 20.0)
    bins = [
        TimeBin(
            id=7,
            mjd_start=mjds[0],
            mjd_end=mjds[split - 1],
            mjd_mid=mjds[0],
            date_start="x",
            date_end="x",
            n_exposures=split,
            detectors=[1],
        ),
        TimeBin(
            id=9,
            mjd_start=mjds[split],
            mjd_end=mjds[-1],
            mjd_mid=mjds[-1],
            date_start="x",
            date_end="x",
            n_exposures=len(mjds) - split,
            detectors=[1],
        ),
    ]
    response = ph.measure_cutouts(cuts, _target(sets, "wise0855"), psf=library, time_bins=bins)
    middle = 0.5 * (mjds[split - 1] + mjds[split])
    assert {p.time_bin for p in response.points} == {7, 9}
    for point in response.points:
        assert point.time_bin == (7 if point.mjd < middle else 9)


def test_without_point_spread_function_nothing_is_offered(recorded, sets):
    stats = ph.SpectrumStats()
    response = ph.measure_cutouts(
        recorded["empty"], _target(sets, "empty"), psf=ph.PsfLibrary(fetch=None), stats=stats
    )
    assert response.points == [] and stats.skipped == {ph.NO_PSF: len(recorded["empty"])}


def test_offline_library_reports_what_it_lacks(recorded):
    lib = ph.PsfLibrary(fetch=None)
    missing = lib.ensure([cut.exposure for cut in recorded["empty"]])
    assert missing and all(reason == "not available offline" for reason in missing.values())


def test_a_header_that_is_not_epsf_is_refused(recorded):
    header = recorded["empty"][0].wcs_header  # a real IMAGE header: not an EPSF table
    raw = "".join(f"{line:<80}" for line in header.split("\n")).encode("ascii")
    raw += b" " * (-len(raw) % 2880)
    with pytest.raises(ph.PsfUnavailable):
        ph.parse_psf_table(raw, 1)


# ------------------------------------------------------------------------------------------- pure maths
def test_synthetic_aperture_weights_cover_the_circle():
    synthetic_shape = (15, 15)
    weights = ph.aperture_weights(synthetic_shape, 7.3, 6.8, 2.0)
    assert weights.sum() == pytest.approx(math.pi * 4.0, rel=0.005)
    assert weights[7, 7] == 1.0 and weights[0, 0] == 0.0
    assert ((weights >= 0.0) & (weights <= 1.0)).all()


def test_synthetic_psf_model_is_normalised_and_centred():
    yy, xx = np.mgrid[0 : ph.PSF_SIDE, 0 : ph.PSF_SIDE]
    synthetic_stamp = np.exp(-0.5 * ((xx - 16.0) ** 2 + (yy - 16.0) ** 2) / 3.0**2)
    synthetic_stamp /= synthetic_stamp.sum()
    model = ph.psf_model(synthetic_stamp, (21, 21), 10.3, 9.6)
    assert model.sum() == pytest.approx(1.0, abs=1e-9)
    rows, cols = np.indices(model.shape)
    assert (model * cols).sum() == pytest.approx(10.3, abs=0.01)
    assert (model * rows).sum() == pytest.approx(9.6, abs=0.01)
    edge = ph.psf_model(
        synthetic_stamp, (21, 21), -0.5, 9.6
    )  # on the window's edge: half the light is off it
    assert edge.sum() == pytest.approx(0.5, abs=0.02)


def test_synthetic_pixel_solid_angle_of_a_tan_grid():
    synthetic = WCS(naxis=2)
    synthetic.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    synthetic.wcs.crval = [133.7598, -7.2422]
    synthetic.wcs.crpix = [1020.0, 1020.0]
    synthetic.wcs.cdelt = [-6.15 / 3600.0, 6.15 / 3600.0]
    expected = (math.radians(6.15 / 3600.0)) ** 2
    assert ph.pixel_solid_angle(synthetic, 1019.0, 1019.0) == pytest.approx(expected, rel=1e-6)


def test_separation_agrees_with_astropy():
    a, b = (133.7598, -7.2422), (133.7581654, -7.2411795)
    expected = SkyCoord(*a, unit=u.deg).separation(SkyCoord(*b, unit=u.deg)).arcsec
    assert ph.separation_arcsec(*a, *b) == pytest.approx(expected, abs=1e-6)


def test_positions_use_the_package_propagation():
    fixed = ph.Source(ra=10.0, dec=-5.0)
    assert fixed.position_at_year(2030.0) == (10.0, -5.0) and not fixed.moves
    moving = ph.Source(ra=269.44850253, dec=4.73942005, epoch=2016.0, pmra=-801.551, pmdec=10362.394)
    assert moving.position_at_year(2026.0) == propagate(269.44850253, 4.73942005, -801.551, 10362.394, 2016.0)
    with pytest.raises(ValueError):
        ph.Source(ra=400.0, dec=0.0)


def test_error_floor_is_in_quadrature():
    assert ph._error_with_floor(1000.0, 40.0) == pytest.approx(math.hypot(40.0, 30.0))
    assert ph._error_with_floor(-100.0, 40.0) == pytest.approx(math.hypot(40.0, 3.0))


def test_binned_error_holds_the_background_terms():
    """A binned value never claims to know the sky under a faint source better than BACKGROUND_FLOOR_UJY
    (measured: -16 to -35 microjansky per detector at the emptiest positions of the WISE 0855 field)."""
    assert ph.binned_error(0.0, 0.0, 1) == pytest.approx(ph.BACKGROUND_FLOOR_UJY[1]) == 25.0
    assert ph.binned_error(0.0, 0.0, 6) == pytest.approx(ph.BACKGROUND_FLOOR_UJY[6]) == 35.0
    assert ph.binned_error(1000.0, 10.0, 2, skew=-40.0) == pytest.approx(
        math.sqrt(10**2 + 30**2 + 25**2 + 40**2)
    )


def test_binned_errors_of_real_windows_carry_the_background_terms(recorded, library, sets):
    """Recorded real windows: every binned error equals its statistical error (from the points), the 3 percent
    floor and the detector's background floor in quadrature, plus the bin's measured skew. Before the background
    terms existed, WISE 0855's lone point at 1.63 micron came back binned as -32.8 +- 31.5 microjansky (now
    +- 40.3), so this test fails without them."""
    for name in ("empty", "wise0855"):
        neighbours = _neighbours(sets, name) if name == "wise0855" else []
        response = ph.measure_cutouts(recorded[name], _target(sets, name), neighbours=neighbours, psf=library)
        assert response.binned
        for b in response.binned:
            det = next(
                w.detector for w in presets.wave_bins() if w.lam_min <= b.lam_max and b.lam_min <= w.lam_max
            )
            assert b.err_ujy >= ph.BACKGROUND_FLOOR_UJY[det] - 0.01
            members = [
                p for p in response.points if p.time_bin == b.time_bin and b.lam_min <= p.lam <= b.lam_max
            ]
            members = [p for p in members if p.quality == "good"]
            assert len(members) == b.n
            stat = math.sqrt(1.0 / sum(1.0 / p.err_ujy**2 for p in members))  # includes the points' 3 % floor
            assert b.err_ujy >= math.sqrt(stat**2 + ph.BACKGROUND_FLOOR_UJY[det] ** 2) * 0.97
        if name == "empty":
            assert all(abs(b.flux_ujy) < 2.0 * b.err_ujy for b in response.binned)


def test_synthetic_background_skew_grows_with_faint_sources_in_the_annulus():
    """Pure maths of the annulus statistics, averaged over 200 synthetic skies (noise 0.01): a flat sky has no
    skew on average; faint synthetic sources that clipping keeps (20 percent of the pixels raised by 0 to 3
    sigma) raise the clipped mean above the median: the skew a binned error carries. One sky's skew is noisy
    (about 0.0006 here), which is why a bin carries the weighted mean of its exposures' skews."""
    dist = ph.distance_map((23, 23), 11.0, 11.0)
    flat, crowded = [], []
    for seed in range(200):
        rng = np.random.default_rng(seed)
        synthetic_sky = rng.normal(1.0, 0.01, size=(23, 23))
        synthetic_faint = (rng.random(synthetic_sky.shape) < 0.2) * rng.uniform(
            0.0, 0.03, synthetic_sky.shape
        )
        flat.append(ph._background(synthetic_sky, None, dist)[3])
        crowded.append(ph._background(synthetic_sky + synthetic_faint, None, dist)[3])
    assert abs(np.mean(flat)) < 0.00015  # measured 0.000035 +- 0.000041
    assert np.mean(crowded) > 0.0005  # measured 0.000697 +- 0.000045


def test_synthetic_binned_edges_hold_a_point_beyond_its_detectors_nominal_range():
    """Pure logic: a detector-1 point at 1.118 micron (the contract's D1 ends at 1.116) is binned in D1's last
    wave bin, and the binned point's lam_max widens to it, so lam always lies within lam_min..lam_max."""
    synthetic_exposure = Exposure(
        "synthetic_1", 1, 61000.0, "spherex_dr1", "nasa-irsa-spherex", "us-east-1", "k"
    )
    synthetic_points = [
        ph._Point(synthetic_exposure, 1.118, 0.01, 61000.0, 5.0, 20.0, 0, ph.QUALITY_GOOD, 0.8),
        ph._Point(synthetic_exposure, 1.110, 0.01, 61000.1, -5.0, 20.0, 0, ph.QUALITY_GOOD, 0.8),
    ]
    [binned] = ph._binned(synthetic_points, [0, 0])
    assert binned.lam_min == presets.wave_bins()[3].lam_min and binned.lam_max == 1.118
    assert binned.lam_min <= binned.lam <= binned.lam_max and binned.n == 2


# ----------------------------------------------------------------------------------------------- archive
@pytest.mark.network
def test_live_wise0855_spectrum(sets):
    from tombaugh.build import sample_exposures
    from tombaugh.discovery import discover

    exposures = sample_exposures(discover(133.7598, -7.2422))
    t = sets["wise0855"]["target"]
    response, stats = ph.measure_with_stats(
        exposures,
        t["ra"],
        t["dec"],
        epoch=t["epoch"],
        pmra=t["pmra"],
        pmdec=t["pmdec"],
        neighbours=_neighbours(sets, "wise0855"),
        deadline=http.Deadline(90.0),
    )
    assert response.state == "ok" and response.method.kind == "joint_psf"
    cold = [p for p in response.points if 4.4 <= p.lam <= 4.8 and p.quality == "good"]
    flux, err = _weighted_mean(cold)
    assert 400.0 < flux < 700.0 and flux > 8.0 * err
    assert stats.read > 200
