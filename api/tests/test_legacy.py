"""tombaugh.legacy ("Then and now") on recorded real IRSA answers (tests/data/legacy, see its README). No network.

`http.get` is replaced by a stand-in that serves exactly the recorded answers and fails on any other request.
The recorded SPHEREx field `cache/fixtures/wise0855` gives the paired frames: the 3' test grid has the same
centre and pixel scale as that field, so it is exactly its central 59 x 59 pixels.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import threading
from pathlib import Path

import numpy as np
import pytest
from astropy.wcs import WCS
from reproject import reproject_interp

from tombaugh import http, legacy
from tombaugh.frames import decode_planes
from tombaugh.grid import Grid, sky_to_pixel
from tombaugh.models import Manifest, Plane
from tombaugh.prepare import clipped_stats
from tombaugh.types import StackedPlane

pytestmark = pytest.mark.filterwarnings("ignore::astropy.wcs.FITSFixedWarning")

DATA = Path(__file__).parent / "data" / "legacy"
INDEX = json.loads((DATA / "requests.json").read_text())
GRID = Grid(*INDEX["grid"][:2], INDEX["grid"][2])
FIXTURE = Path(__file__).resolve().parents[2] / "cache" / "fixtures" / "wise0855"
CROP = slice(30, 89)  # the 3' grid inside the 119-pixel grid of the recorded field (same centre and scale)
W2_URL = "https://irsa.ipac.caltech.edu/ibe/data/wise/allwise/p3am_cdd/13/1342/1342m076_ac51/1342m076_ac51-w2-int-3.fits"


def _key(url: str, params) -> tuple:
    return url, tuple(sorted((params or {}).items()))


SERVED = {_key(r["url"], r["params"]): (DATA / r["file"]).read_bytes() for r in INDEX["requests"]}


class _Answer:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200


class Replay:
    """Stands in for http.get: the recorded answers and nothing else; `fail` makes chosen URLs fail."""

    def __init__(self, fail: tuple[str, ...] = ()) -> None:
        self.calls: list[tuple] = []
        self.fail = fail
        self._lock = threading.Lock()

    def __call__(self, url, *, params=None, deadline=None, **_):
        with self._lock:
            self.calls.append(_key(url, params))
        http.check_url(url)
        if any(part in url for part in self.fail) or any(part in str(params) for part in self.fail):
            raise http.UpstreamError("gave up after 6 attempts: HTTP 503", url=url, status=503)
        key = _key(url, params)
        if key not in SERVED:
            raise AssertionError(f"unrecorded request {key}")
        return _Answer(SERVED[key])


@pytest.fixture
def replay(monkeypatch) -> Replay:
    fake = Replay()
    monkeypatch.setattr(http, "get", fake)
    return fake


def _fixture_planes() -> list[StackedPlane]:
    """The SPHEREx stacks of the recorded field (kind "sci"); its legacy planes have no time or wave bin."""
    manifest = Manifest.model_validate(json.loads((FIXTURE / "manifest.json").read_text()))
    grid = manifest.grid
    data = decode_planes((FIXTURE / "frames.bin").read_bytes(), len(manifest.planes), grid.ny, grid.nx)
    return [
        StackedPlane(
            p.time_bin,
            p.wave_bin,
            data[p.index],
            p.n_exposures,
            p.sigma,
            p.lam_eff,
            p.mjd_mid,
            p.mjd_mid,
            p.mjd_mid,
        )
        for p in manifest.planes
        if p.kind == "sci"
    ]


@pytest.fixture(scope="module")
def fixture_planes() -> list[StackedPlane]:
    return _fixture_planes()


def _cutout(band: str, obs_id: str) -> bytes:
    return (DATA / f"cutout_{band}_{obs_id}.fits.gz").read_bytes()


def _image(images, obs_id: str) -> legacy.LegacyImage:
    return next(image for image in images if image.obs_id == obs_id)


@pytest.fixture(scope="module")
def sia() -> dict[str, list[legacy.LegacyImage]]:
    return {
        "AllWISE": legacy.parse_sia_tsv((DATA / "sia_wise_allwise_0.tsv").read_text(), "AllWISE")[0],
        "2MASS": legacy.parse_sia_tsv((DATA / "sia_twomass_allsky_0.tsv").read_text(), "2MASS")[0],
    }


# ----------------------------------------------------------------------------------------------- samples
def test_recorded_samples_are_intact():
    for request in INDEX["requests"]:
        body = (DATA / request["file"]).read_bytes()
        assert len(body) == request["bytes"]
        assert hashlib.sha256(body).hexdigest() == request["sha256"]
    assert sum(path.stat().st_size for path in DATA.iterdir()) < 400_000


# --------------------------------------------------------------------------------------------- discovery
def test_sia_answers_parse_to_the_science_images(sia):
    text = (DATA / "sia_wise_allwise_0.tsv").read_text()
    images, dropped = legacy.parse_sia_tsv(text, "AllWISE")
    assert [(i.band, i.obs_id) for i in images] == [("W2", "1342m076_ac51")]
    w2 = images[0]
    assert w2.url == W2_URL
    assert (w2.mjd_min, w2.mjd_max) == (55319.364866, 55513.471187)  # the archive's t_min, t_max
    assert w2.lam_min == pytest.approx(4.10) and w2.lam_max == pytest.approx(5.16)
    assert w2.resolution_arcsec == 6.4 and len(w2.region) == 4
    assert dropped == {"not_science": 13, "other_band": 1}  # 7 W2 and 6 W3 ancillary rows; the W3 image

    twomass = sia["2MASS"]
    assert {i.band for i in twomass} == {"J", "Ks"}  # SIA's "K" is the contract's "Ks"
    ks = sorted(i.obs_id for i in twomass if i.band == "Ks")
    assert ks == ["allsky_981228s_s093_0056", "allsky_981228s_s093_0068", "allsky_981228s_s094_0209"]
    assert all(i.mjd_min == i.mjd_max and 51175.32 < i.mjd_min < 51175.34 for i in twomass)  # 1998-12-28


def test_rows_with_another_host_or_path_are_dropped():
    lines = (DATA / "sia_wise_allwise_0.tsv").read_text().splitlines()
    science = next(line for line in lines if "\tscience\t" in line and "-w2-int-3.fits" in line)
    bad = [
        science.replace("https://irsa.ipac.caltech.edu/ibe/data/", "https://example.org/ibe/data/"),
        science.replace("-w2-int-3.fits", "-w2-int-3.fits?center=1,1"),
        science.replace("https://", "http://"),
    ]
    images, dropped = legacy.parse_sia_tsv("\n".join([lines[0], *bad]), "AllWISE")
    assert images == [] and dropped == {"unexpected_url": 3}


def test_an_answer_that_is_not_an_sia_table_raises():
    with pytest.raises(ValueError):
        legacy.parse_sia_tsv("<html>502 Proxy Error</html>", "2MASS")
    with pytest.raises(ValueError):
        legacy.parse_sia_tsv("", "AllWISE")


@pytest.mark.parametrize("fov", [3, 4, 5, 6, 8, 10])
def test_search_circles_cover_the_field_and_stay_small(fov):
    grid = Grid.for_field(269.4463, 4.7682, fov)
    circles = legacy.search_circles(grid)
    assert len(circles) == (1 if fov <= 6 else 4)
    assert all(radius <= legacy.SIA_MAX_RADIUS_DEG for _, _, radius in circles)
    xs, ys = legacy._lattice(grid, 9)
    for x, y in zip(xs, ys, strict=True):  # every point of the field lies in some circle
        inside = False
        for ra, dec, radius in circles:
            cx, cy = sky_to_pixel(grid, ra, dec)
            inside |= math.hypot(x - cx, y - cy) * grid.pixscale <= radius * 3600 + 1e-6
        assert inside


def test_the_two_needed_2mass_images_are_chosen(sia):
    ks = [image for image in sia["2MASS"] if image.band == "Ks"]
    chosen, share = legacy.choose_images(ks, GRID)
    assert sorted(image.obs_id for image in chosen) == [
        "allsky_981228s_s093_0068",
        "allsky_981228s_s094_0209",
    ]
    assert share == 1.0
    wide, share = legacy.choose_images(ks, Grid(GRID.ra0, GRID.dec0, 119))  # the 6' field needs the third
    assert len(wide) == 3 and share == 1.0
    w2 = [image for image in sia["AllWISE"] if image.band == "W2"]
    assert [image.obs_id for image in legacy.choose_images(w2, GRID)[0]] == ["1342m076_ac51"]


def test_cutout_request_is_centred_on_the_field(sia):
    w2 = _image(sia["AllWISE"], "1342m076_ac51")
    side = legacy.cutout_side_arcsec(GRID, w2, 1.375)
    assert side == math.ceil(59 * 3.075 * 1.25 + 2 * 2 * 1.375)
    assert legacy.cutout_params(GRID, side) == {
        "center": "133.759800,-7.242200",
        "size": "233arcsec",
        "gzip": "true",
    }


# ----------------------------------------------------------------------------------------------- reading
def test_read_cutout_gzip_and_plain_agree():
    raw = _cutout("W2", "1342m076_ac51")
    header, image = legacy.read_cutout(raw)
    _, plain = legacy.read_cutout(gzip.decompress(raw))
    assert image.shape == (170, 171) and np.array_equal(image, plain, equal_nan=True)  # as the service cut it
    assert header["BUNIT"].strip() == "DN" and header["WAVELEN"] == 4.618 and header["MAGZP"] == 19.5
    assert header["DATEOBS1"].startswith("2010-05-03") and header["DATEOBS2"].startswith("2010-11-13")
    assert legacy.native_pixscale_arcsec(header) == pytest.approx(1.375, abs=1e-6)
    with pytest.raises(ValueError):
        legacy.read_cutout(b"<html>not fits</html>")
    with pytest.raises(ValueError):
        legacy.read_cutout(gzip.compress(b"\0" * (legacy.MAX_FITS_BYTES + 1)))


def _grid_wcs(grid: Grid) -> WCS:
    """The contract grid as an astropy WCS, for the independent route: TAN, x grows west and y grows south."""
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crval = [grid.ra0, grid.dec0]
    wcs.wcs.crpix = [grid.cx + 1, grid.cy + 1]
    wcs.wcs.cdelt = [-grid.pixscale / 3600.0, -grid.pixscale / 3600.0]  # row 0 is north
    # The survey headers say FK5 J2000 and legacy.resample reads their coordinates as ICRS (0.03" apart, see
    # the module); the same frame here keeps reproject from moving the image by that amount.
    wcs.wcs.radesys, wcs.wcs.equinox = "FK5", 2000.0
    return wcs


@pytest.mark.parametrize(("band", "obs_id"), [("W2", "1342m076_ac51"), ("Ks", "allsky_981228s_s093_0068")])
def test_resample_agrees_with_reproject(band, obs_id):
    header, image = legacy.read_cutout(_cutout(band, obs_id))
    ours = legacy.resample(image, header, GRID)
    theirs, footprint = reproject_interp(
        (image, WCS(header)), _grid_wcs(GRID), shape_out=GRID.shape, order="bilinear"
    )
    both = np.isfinite(ours) & np.isfinite(theirs) & (footprint > 0)
    assert both.mean() > 0.4  # the Ks image covers part of the field only
    assert np.isfinite(ours).sum() >= both.sum()
    _, sigma, _ = clipped_stats(image)
    assert np.median(np.abs(ours[both] - theirs[both])) < 0.01 * sigma
    assert np.percentile(np.abs(ours[both] - theirs[both]), 99) < 0.2 * sigma


def test_smoothing_takes_a_2mass_beam_to_ten_arcsec():
    sigma = legacy.kernel_sigma_arcsec(2.9)
    assert sigma == pytest.approx(math.sqrt(10.0**2 - 2.9**2) / (2 * math.sqrt(2 * math.log(2))))
    assert legacy.kernel_sigma_arcsec(12.0) == 0.0  # never sharpened
    # pure maths: a Gaussian of 2.9 px FWHM smoothed with that kernel (in 1 px units) has 10 px FWHM
    rows, cols = np.indices((81, 81), dtype=np.float64)
    s0 = 2.9 / legacy.FWHM_PER_SIGMA
    synthetic_star = np.exp(-((cols - 40) ** 2 + (rows - 40) ** 2) / (2 * s0 * s0))
    synthetic_star[0:3, 0:3] = np.nan
    smoothed = legacy.smooth(synthetic_star, sigma)
    centre = (slice(10, 71), slice(10, 71))
    weights = smoothed[centre] / smoothed[centre].sum()
    variance = (weights * (cols[centre] - 40) ** 2).sum()
    assert math.sqrt(variance) * legacy.FWHM_PER_SIGMA == pytest.approx(10.0, rel=0.01)
    assert np.isnan(smoothed[0, 0])  # under half its kernel on data: the masked corner, and the array corners
    assert np.isfinite(smoothed[8:-8, 8:-8]).all()


# ------------------------------------------------------------------------------------------- the build
def test_build_on_recorded_answers(replay):
    result = legacy.build_legacy_planes(GRID, ("W2", "Ks"))
    assert len(replay.calls) == len(INDEX["requests"])  # 2 SIA queries and 3 cut-outs, nothing else
    assert set(replay.calls) == set(SERVED)
    w2, ks = result.planes
    assert (w2.mission, w2.band, ks.mission, ks.band) == ("AllWISE", "W2", "2MASS", "Ks")
    for plane in (w2, ks):
        assert plane.data.shape == GRID.shape and plane.data.dtype == np.float32
        assert plane.coverage == 1.0 and np.isfinite(plane.data).all()
        assert plane.scaled is None and plane.unit == "DN" and plane.gain is None
        median, sigma, _ = clipped_stats(plane.data)
        assert abs(median) < 0.25 * sigma and sigma == pytest.approx(plane.sigma, rel=1e-5)
    # AllWISE: a coadd of several passes, its span from the archive, never one date
    model = w2.plane_model(0, GRID)
    assert (model.date_start, model.date_end) == ("2010-05-03", "2010-11-13")
    assert (model.lam_min, model.lam_eff, model.lam_max) == (4.1, 4.618, 5.16)
    assert model.n_exposures == 26 and w2.images == ["1342m076_ac51"] and w2.resolution_arcsec == 6.4
    # 2MASS: a mosaic of two scans of one night, smoothed to 10"
    model = ks.plane_model(1, GRID)
    assert (model.date_start, model.date_end) == ("1998-12-28", "1998-12-28")
    assert (model.lam_min, model.lam_eff, model.lam_max) == (2.028, 2.159, 2.29)
    assert model.n_exposures == 6 and ks.resolution_arcsec == 10.0
    assert sorted(ks.images) == ["allsky_981228s_s093_0068", "allsky_981228s_s094_0209"]
    assert model.offset == GRID.n * GRID.n * 2 and model.scaled is None
    assert any("mosaic" in note for note in ks.notes)
    assert any("not scaled on field stars (no paired SPHEREx frame)" in w for w in result.warnings)


def test_mosaic_fills_from_one_image_and_never_averages():
    parts = [
        legacy.prepare_image(image, _cutout("Ks", image.obs_id), GRID)
        for image in legacy.choose_images(
            [
                i
                for i in legacy.parse_sia_tsv((DATA / "sia_twomass_allsky_0.tsv").read_text(), "2MASS")[0]
                if i.band == "Ks"
            ],
            GRID,
        )[0]
    ]
    mosaic, used = legacy.mosaic(parts)
    first, second = used
    assert first.coverage >= second.coverage
    both = np.isfinite(first.data) & np.isfinite(second.data)
    assert both.any()  # the scans overlap ...
    assert np.array_equal(mosaic[both], first.data[both])  # ... and the overlap comes from the first only
    only_second = ~np.isfinite(first.data) & np.isfinite(second.data)
    factor = 10 ** (0.4 * (first.magzp - second.magzp))  # m = MAGZP - 2.5 log10(DN)
    assert np.allclose(mosaic[only_second], second.data[only_second] * factor)
    assert {first.magzp, second.magzp} == {19.8763, 19.8756}  # the headers' MAGZP of the two scans


def test_wise0855_is_at_the_centre_of_the_cold_frame_and_not_in_the_2010_w2_plane(replay, fixture_planes):
    """WISE 0855 sits at the centre in the SPHEREx 4-5 um frames (2025-26); in 2010 it was 126" east."""
    cold = legacy.paired_reference(fixture_planes, "W2")[CROP, CROP]
    result = legacy.build_legacy_planes(GRID, ("W2",), references={"W2": cold})
    w2 = result.planes[0]
    _, sigma_cold, _ = clipped_stats(cold)
    _, sigma_w2, _ = clipped_stats(w2.data)
    assert cold[GRID.cy, GRID.cx] > 15 * sigma_cold
    assert w2.data[GRID.cy, GRID.cx] < 3 * sigma_w2  # only the wing of a catalogued star 6.9" away
    # with only the moving dwarf and one star at the edge, there are too few common stars to scale
    assert w2.scaled is None and any("usable field stars" in w for w in w2.warnings)


def test_field_star_gain_recovers_a_known_factor(fixture_planes):
    """Maths on a real frame: the plane is the paired SPHEREx frame divided by 40 (a stand-in, not data)."""
    reference = legacy.paired_reference(fixture_planes, "W1")
    synthetic_scaled_copy = reference / 40.0
    scale, reason = legacy.field_star_scale(synthetic_scaled_copy, reference)
    assert reason == "" and scale.n_stars >= legacy.MIN_FIELD_STARS
    assert scale.gain == pytest.approx(40.0, rel=1e-9) and scale.scatter < 1e-9


def test_a_scaled_plane_says_so(replay, fixture_planes):
    result = legacy.build_legacy_planes(GRID, ("Ks",))
    plane = result.planes[0]
    before = plane.data.copy()
    reference = legacy.paired_reference(fixture_planes, "W1")
    synthetic_scaled_copy = reference / 40.0
    scaled = legacy.assemble_plane(
        "Ks",
        [legacy.prepare_image(i, _cutout("Ks", i.obs_id), GRID) for i in _ks_images()],
        GRID,
        None,
    )
    assert np.array_equal(scaled.data, before, equal_nan=True)  # no reference, no scaling
    scale, _ = legacy.field_star_scale(synthetic_scaled_copy, reference)
    plane.gain, plane.n_stars = scale.gain, scale.n_stars
    model = plane.plane_model(3, GRID)
    assert model.scaled == "field_stars" and model.kind == "legacy"
    assert model.time_bin is None and model.wave_bin is None and model.band == "Ks"
    assert Plane.model_validate(model.model_dump()) == model


def _ks_images() -> list[legacy.LegacyImage]:
    images = legacy.parse_sia_tsv((DATA / "sia_twomass_allsky_0.tsv").read_text(), "2MASS")[0]
    return legacy.choose_images([i for i in images if i.band == "Ks"], GRID)[0]


def test_paired_reference_is_the_contract_frame_averaged_over_visits(fixture_planes):
    reference = legacy.paired_reference(fixture_planes, "W2")
    cold = set(legacy.presets.preset_wave_bins("cold"))
    frames = []
    for time_bin in sorted({p.time_bin for p in fixture_planes}):
        chosen = [p.data for p in fixture_planes if p.time_bin == time_bin and p.wave_bin in cold]
        if chosen:
            with np.errstate(all="ignore"):
                frames.append(np.nanmean(np.stack(chosen), axis=0))
    with np.errstate(all="ignore"):
        expected = np.nanmean(np.stack(frames), axis=0)
    assert np.allclose(reference, expected, equal_nan=True)
    assert legacy.paired_reference([], "W2") is None


# ------------------------------------------------------------------------------------- honest failures
def test_a_failing_cutout_gives_a_warning_and_no_plane(monkeypatch):
    fake = Replay(fail=("ki0930068", "ki0940209"))
    monkeypatch.setattr(http, "get", fake)
    result = legacy.build_legacy_planes(GRID, ("W2", "Ks"))
    assert [plane.band for plane in result.planes] == ["W2"]
    assert any("2MASS Ks: 2 image(s) not read" in w for w in result.warnings)
    assert any("2MASS Ks: no data on this field; no plane." in w for w in result.warnings)


def test_one_failing_image_of_a_mosaic_leaves_nan_and_says_how_much(monkeypatch):
    fake = Replay(fail=("ki0940209",))
    monkeypatch.setattr(http, "get", fake)
    result = legacy.build_legacy_planes(GRID, ("Ks",))
    plane = result.planes[0]
    assert 0.0 < plane.coverage < 1.0 and np.isnan(plane.data).any()
    assert plane.images == ["allsky_981228s_s093_0068"]
    assert any("of the field has no data from the survey" in w for w in result.warnings)


def test_an_unreachable_archive_gives_a_warning_and_no_plane(monkeypatch):
    fake = Replay(fail=("twomass_allsky",))
    monkeypatch.setattr(http, "get", fake)
    result = legacy.build_legacy_planes(GRID, ("W2", "Ks"))
    assert [plane.band for plane in result.planes] == ["W2"]
    assert any(w.startswith("2MASS: archive unavailable") for w in result.warnings)


def test_an_unknown_band_raises_before_any_request(replay):
    with pytest.raises(KeyError):
        legacy.build_legacy_planes(GRID, ("W3",))
    assert replay.calls == []


# --------------------------------------------------------------------------------------------- network
@pytest.mark.network
def test_live_w2_shows_wise0855_at_its_2010_position():
    grid = Grid(133.7598, -7.2422, 119)
    result = legacy.build_legacy_planes(grid, ("W2",), deadline=http.Deadline(90))
    assert result.planes, result.warnings
    w2 = result.planes[0]
    x, y = sky_to_pixel(grid, 133.79513, -7.24515)  # the challenge brief's coordinates, 2010
    _, sigma, _ = clipped_stats(w2.data)
    rows, cols = np.indices(grid.shape)
    near = np.hypot(cols - x, rows - y) <= 2.0
    assert np.nanmax(w2.data[near]) > 10 * sigma
