"""Catalogue overlays (Contract v1.0, section 7.3) on the two recorded REAL fields, with no network.

The catalogue answers are recorded real answers (``tests/data/catalogs``, see its README) and the frames are
the recorded fixtures. What these tests prove: positions computed for Gaia stars land on the stars in the
frames; Barnard's Star's track follows it through its five visits; WISE 0855's track (its published
astrometry, not CatWISE's motion) sits within 0.5 px of the faint source of the 4-5 micron frames; unreliable
CatWISE motions give no track; one catalogue failing does not lose the other; nothing is downloaded at run
time.
"""

from __future__ import annotations

import gzip
import json
import math
import urllib.request
from pathlib import Path

import astropy.units as u
import numpy as np
import pytest
from astropy.coordinates import Distance, SkyCoord, get_body_barycentric
from astropy.time import Time
from astropy.utils import iers
from astropy.utils.data import conf as data_conf
from scipy import optimize

from tombaugh import catalogs, http, presets
from tombaugh.frames import decode_planes
from tombaugh.grid import Grid, sky_to_pixel
from tombaugh.models import Manifest, OverlaysResponse, TimeBin
from tombaugh.tools.make_fixture import TARGETS

DATA = Path(__file__).resolve().parent / "data" / "catalogs"
FIXTURES = Path(__file__).resolve().parents[2] / "cache" / "fixtures"
BARNARD_ID = "4472832130942575872"
WISE0855_KEPT = "J085507.96-071439.3"  # the most significant of WISE 0855's three CatWISE entries
WISE0855_NEIGHBOUR = (
    "J085501.95-071428.2"  # the background star blended with WISE 0855 (Contract section 7.1)
)


def _text(name: str) -> str:
    return gzip.decompress((DATA / name).read_bytes()).decode("utf-8")


def _replay(name: str):
    gaia_rows = catalogs.parse_gaia_csv(_text(f"gaia_{name}.csv.gz"))
    catwise_rows = catalogs.parse_catwise_ipac(_text(f"catwise_{name}.tbl.gz"))
    return (lambda *_: (gaia_rows, "recorded")), (lambda *_: (catwise_rows, "recorded"))


class Field:
    """A recorded field, its decoded planes and its overlays computed from the recorded catalogue answers."""

    def __init__(self, name: str) -> None:
        folder = FIXTURES / name
        self.manifest = Manifest.model_validate_json((folder / "manifest.json").read_text(encoding="utf-8"))
        grid = self.manifest.grid
        self.grid = catalogs.field_grid(self.manifest)
        self.planes = decode_planes(
            (folder / "frames.bin").read_bytes(), len(self.manifest.planes), grid.ny, grid.nx
        )
        gaia_query, catwise_query = _replay(name)
        self.overlays = catalogs.overlays_for_manifest(
            self.manifest, gaia_query=gaia_query, catwise_query=catwise_query
        )

    def frame(self, time_bin: int, wave_bins: list[int]) -> np.ndarray | None:
        """The contract's uniform-weight frame of one time bin over the given wave bins (NaN where empty)."""
        chosen = [p for p in self.manifest.planes if p.time_bin == time_bin and p.wave_bin in wave_bins]
        if not chosen:
            return None
        stack = np.stack([self.planes[p.index] for p in chosen]).astype(np.float64)
        finite = np.isfinite(stack)
        count = finite.sum(axis=0)
        with np.errstate(invalid="ignore"):
            return np.where(
                count > 0, np.where(finite, stack, 0.0).sum(axis=0) / np.maximum(count, 1), np.nan
            )

    def full_visits(self) -> list[int]:
        return [b.id for b in self.manifest.time_bins if b.n_exposures >= 100]


@pytest.fixture(scope="module")
def wise0855() -> Field:
    return Field("wise0855")


@pytest.fixture(scope="module")
def barnard() -> Field:
    return Field("barnard")


def _gauss(coords, amp, x0, y0, sigma, bg):
    x, y = coords
    return amp * np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / (2.0 * sigma**2)) + bg


def _fit_star(image: np.ndarray, x: float, y: float, half: int = 4) -> tuple[float, float] | None:
    """Centre of a circular Gaussian plus background fitted in a 9 x 9 box around (x, y).

    None when the fit is unusable: a blank pixel in the box, no convergence, a negative peak, a width outside
    0.6 to 4 px, or a centre that wandered more than 2.5 px (onto another source). A position error larger
    than that leaves too few usable fits, which the caller counts.
    """
    xi, yi = round(x), round(y)
    box = image[yi - half : yi + half + 1, xi - half : xi + half + 1]
    if box.shape != (2 * half + 1, 2 * half + 1) or not np.isfinite(box).all():
        return None
    rows, cols = np.indices(box.shape, dtype=np.float64)
    coords = (cols.ravel() + xi - half, rows.ravel() + yi - half)
    start = [box.max() - np.median(box), x, y, 1.4, np.median(box)]
    try:
        p, _ = optimize.curve_fit(_gauss, coords, box.ravel(), p0=start, maxfev=4000)
    except (RuntimeError, ValueError):
        return None
    if p[0] <= 0.0 or not 0.6 < abs(p[3]) < 4.0 or math.hypot(p[1] - x, p[2] - y) > 2.5:
        return None
    return float(p[1]), float(p[2])


def _isolated_stars(field: Field) -> list:
    """Gaia stars G 11 to 15.5, 8 px inside the grid, with no source within 20 arcsec less than 3 mag fainter."""
    sources = field.overlays.gaia
    x, y = sky_to_pixel(field.grid, [s.ra for s in sources], [s.dec for s in sources])
    g = np.array([99.0 if s.g is None else s.g for s in sources])
    chosen = []
    for i, star in enumerate(sources):
        if star.g is None or not 11.0 <= star.g <= 15.5 or not (8 <= x[i] <= 110 and 8 <= y[i] <= 110):
            continue
        near = (np.hypot(x - x[i], y - y[i]) * 3.075 < 20.0) & (g < star.g + 3.0)
        near[i] = False
        if not near.any():
            chosen.append(star)
    return chosen


# ------------------------------------------------------------------------------------------------ parsing
def test_recorded_answers_parse_with_the_documented_columns():
    samples = json.loads((DATA / "samples.json").read_text(encoding="utf-8"))
    counts = {f["field"]: (f["gaia"]["rows"], f["catwise"]["rows"]) for f in samples["fields"]}
    for name, (n_gaia, n_catwise) in counts.items():
        assert len(catalogs.parse_gaia_csv(_text(f"gaia_{name}.csv.gz"))) == n_gaia
        assert len(catalogs.parse_catwise_ipac(_text(f"catwise_{name}.tbl.gz"))) == n_catwise
    assert counts == {"wise0855": (282, 1388), "barnard": (2636, 2196)}


def test_gaia_row_of_barnards_star_is_read_as_the_catalogue_gives_it():
    rows = {r.source_id: r for r in catalogs.parse_gaia_csv(_text("gaia_barnard.csv.gz"))}
    star = rows[BARNARD_ID]
    assert (star.ra, star.dec) == pytest.approx((269.44850252543836, 4.739420051112412), abs=1e-12)
    assert (star.pmra, star.pmdec, star.parallax) == pytest.approx((-801.551, 10362.394, 546.976), abs=1e-3)
    assert star.radial_velocity == pytest.approx(-110.468, abs=1e-3) and star.g == pytest.approx(
        8.194, abs=1e-3
    )


def test_catwise_motions_are_converted_to_mas_per_year():
    rows = {r.id: r for r in catalogs.parse_catwise_ipac(_text("catwise_wise0855.tbl.gz"))}
    entry = rows["J085508.34-071439.2"]  # the CatWISE id of the contract's spectrum example
    assert (entry.ra, entry.dec) == pytest.approx((133.7839831, -7.2441961), abs=1e-9)
    assert (entry.pmra, entry.pmdec) == pytest.approx((-7965.0, 806.2), abs=1e-6)  # arcsec/yr x 1000
    assert (entry.w1, entry.w2) == pytest.approx((17.966, 13.82))
    assert catalogs.catwise_epoch_jyear() == pytest.approx(2015.40178, abs=1e-5)  # MJD 57170


def test_answers_that_are_not_tables_are_refused():
    with pytest.raises(ValueError):
        catalogs.parse_gaia_csv("<VOTABLE><INFO name='QUERY_STATUS' value='ERROR'/></VOTABLE>")
    with pytest.raises(ValueError):
        catalogs.parse_catwise_ipac('[struct stat="ERROR", msg="no such catalog"]')
    truncated = _text("catwise_wise0855.tbl.gz").splitlines()[:-5]
    with pytest.raises(ValueError, match="announces 1388 rows"):
        catalogs.parse_catwise_ipac("\n".join(truncated))


# --------------------------------------------------------------------------------------------- astrometry
def test_propagation_agrees_with_astropy_space_motion_and_the_earths_position():
    """An independent route: astropy's rigorous space motion (``apply_space_motion``) to each visit, then the
    vector from the Earth's centre (same built-in ephemeris). Barnard's Star, with parallax and RV."""
    star = {r.source_id: r for r in catalogs.parse_gaia_csv(_text("gaia_barnard.csv.gz"))}[BARNARD_ID]
    times = Time([60912.98663, 61125.0614, 61287.13008], format="mjd", scale="utc")
    epoch = Time(2016.0, format="jyear", scale="tcb")
    ra, dec = catalogs.astrometric_positions(
        [star.ra],
        [star.dec],
        [star.pmra],
        [star.pmdec],
        [star.parallax],
        [star.radial_velocity],
        epoch,
        times,
    )
    coord = SkyCoord(
        ra=star.ra * u.deg,
        dec=star.dec * u.deg,
        distance=Distance(parallax=star.parallax * u.mas),
        pm_ra_cosdec=star.pmra * u.mas / u.yr,
        pm_dec=star.pmdec * u.mas / u.yr,
        radial_velocity=star.radial_velocity * u.km / u.s,
        obstime=epoch,
    )
    for k, t in enumerate(times):
        moved = coord.apply_space_motion(new_obstime=t).cartesian.xyz.to_value(u.au)
        seen = moved - get_body_barycentric("earth", t, ephemeris="builtin").xyz.to_value(u.au)
        ref = SkyCoord(x=seen[0], y=seen[1], z=seen[2], representation_type="cartesian")
        ours = SkyCoord(ra[0, k] * u.deg, dec[0, k] * u.deg)
        assert ours.separation(SkyCoord(ref.spherical.lon, ref.spherical.lat)).to_value(u.mas) < 2.0


def test_parallax_is_applied():
    """Barnard's Star with and without its parallax: the yearly ellipse moves it by tenths of an arcsec."""
    star = {r.source_id: r for r in catalogs.parse_gaia_csv(_text("gaia_barnard.csv.gz"))}[BARNARD_ID]
    times = Time([60912.98663, 61125.0614], format="mjd", scale="utc")
    epoch = Time(2016.0, format="jyear", scale="tcb")
    args = ([star.ra], [star.dec], [star.pmra], [star.pmdec])
    with_px = catalogs.astrometric_positions(*args, [star.parallax], [None], epoch, times)
    without = catalogs.astrometric_positions(*args, [None], [None], epoch, times)
    shift = SkyCoord(with_px[0][0] * u.deg, with_px[1][0] * u.deg).separation(
        SkyCoord(without[0][0] * u.deg, without[1][0] * u.deg)
    )
    assert all(100.0 < value < star.parallax for value in shift.to_value(u.mas))


def test_nothing_is_downloaded_at_run_time(monkeypatch):
    """No internet for astropy and no socket for urllib: the ephemeris and the time scales still work."""

    def refuse(*_, **__):
        raise AssertionError("a download was attempted")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    assert iers.conf.auto_download is False
    with data_conf.set_temp("allow_internet", False):
        position = catalogs.earth_barycentric_au(Time([61287.13008], format="mjd", scale="utc"))
        ra, _ = catalogs.astrometric_positions(
            [269.4485], [4.7394], [-801.551], [10362.394], [546.976], [None],
            Time(2016.0, format="jyear", scale="tcb"), Time([61287.13008], format="mjd", scale="utc"),
        )  # fmt: skip
    assert position.shape == (1, 3) and 0.9 < float(np.linalg.norm(position)) < 1.1  # about 1 au
    assert np.isfinite(ra).all()


def test_search_radius_covers_the_corner_and_the_fastest_star(wise0855):
    grid, bins = wise0855.grid, wise0855.manifest.time_bins
    corner = 119 / 2 * 3.075 * math.sqrt(2.0)
    years = Time(bins[-1].mjd_mid, format="mjd", scale="utc").tt.jyear - 2016.0
    expected = (corner + catalogs.MAX_PM_ARCSEC_YR * years + catalogs.SEARCH_SLACK_ARCSEC) / 3600.0
    assert catalogs.search_radius_deg(grid, bins, 2016.0) == pytest.approx(expected, rel=1e-9)
    assert catalogs.MAX_PM_ARCSEC_YR == pytest.approx(10.393, abs=1e-3)


def test_synthetic_sources_are_kept_only_when_on_the_grid_at_a_visit():
    """Pure geometry: a synthetic still source just inside the grid edge is kept, one just outside is left
    out, and a synthetic fast mover that crosses the edge between two visits is kept, with a track."""
    synthetic_grid = Grid(ra0=10.0, dec0=0.0, n=11)
    edge = (5.5 + 0.2) * 3.075 / 3600.0  # 0.2 px beyond the outer edge of the edge pixel
    synthetic_bins = [
        TimeBin(id=0, mjd_start=60000.0, mjd_end=60001.0, mjd_mid=60000.5, date_start="2023-02-25",
                date_end="2023-02-26", n_exposures=10, detectors=[1]),
        TimeBin(id=1, mjd_start=61000.0, mjd_end=61001.0, mjd_mid=61000.5, date_start="2025-11-21",
                date_end="2025-11-22", n_exposures=10, detectors=[1]),
    ]  # fmt: skip
    synthetic_rows = [
        catalogs.GaiaRow("1", 10.0 - edge + 0.4 * 3.075 / 3600.0, 0.0, 0.0, 0.0, None, None, 15.0),  # inside
        catalogs.GaiaRow("2", 10.0 - edge, 0.0, 0.0, 0.0, None, None, 15.0),  # outside at every visit
        catalogs.GaiaRow("3", 10.0 - edge - 2e-4, 0.0, 1000.0, 0.0, None, None, 15.0),  # enters the grid
    ]
    sources = {s.source_id: s for s in catalogs.gaia_sources(synthetic_rows, synthetic_grid, synthetic_bins)}
    assert set(sources) == {"1", "3"}
    assert sources["1"].track is None and [p.time_bin for p in sources["3"].track] == [0, 1]


# ------------------------------------------------------------------------------- the recorded real fields
@pytest.mark.parametrize("name", ["wise0855", "barnard"])
def test_gaia_positions_land_on_the_stars_in_the_frames(name, request):
    """Isolated, unsaturated Gaia stars: a Gaussian fitted in the all-band frame of every full visit lies
    within 0.25 px of the position computed for that visit, 0.1 px on average (measured 14 Nov 2026: 0.067
    px over 4 stars in the WISE 0855 field, 0.044 px over 8 stars in the Barnard field)."""
    field: Field = request.getfixturevalue(name)
    wave_bins = presets.preset_wave_bins("all")
    stars = _isolated_stars(field)
    assert len(stars) >= (4 if name == "wise0855" else 8)
    distances = []
    for visit in field.full_visits():
        image = field.frame(visit, wave_bins)
        for star in stars:
            point = next((p for p in star.track or [] if p.time_bin == visit), None)
            ra, dec = (point.ra, point.dec) if point else (star.ra, star.dec)
            x, y = sky_to_pixel(field.grid, ra, dec)
            fitted = _fit_star(image, x, y)
            if fitted is not None:
                distances.append(math.hypot(fitted[0] - x, fitted[1] - y))
    assert len(distances) >= 2 * len(stars) - 1
    assert max(distances) < 0.25 and float(np.mean(distances)) < 0.1


def test_barnards_star_track_follows_the_star_through_its_five_visits(barnard):
    """The track has one point per visit; it moves 3.4 px north in the year from the first to the last visit,
    and the flux-weighted centroid of the D5 + D6 frame (12 px around the track, the saturated core blank)
    is within 0.35 px of it in every visit that has those planes (measured: 0.07 to 0.26 px)."""
    star = next(s for s in barnard.overlays.gaia if s.source_id == BARNARD_ID)
    assert [p.time_bin for p in star.track] == [b.id for b in barnard.manifest.time_bins] == [0, 1, 2, 3, 4]
    xs, ys = sky_to_pixel(barnard.grid, [p.ra for p in star.track], [p.dec for p in star.track])
    assert 3.2 < ys[0] - ys[-1] < 3.7 and abs(xs[-1] - xs[0]) < 0.5
    red = presets.preset_wave_bins("d5") + presets.preset_wave_bins("d6")
    checked = 0
    for point, x, y in zip(star.track, xs, ys, strict=True):
        image = barnard.frame(point.time_bin, red)
        if image is None:
            continue
        rows, cols = np.indices(image.shape, dtype=np.float64)
        radius = np.hypot(cols - x, rows - y)
        background = np.nanmedian(np.where((radius > 15) & (radius < 25), image, np.nan))
        flux = np.clip(np.where((radius <= 12) & np.isfinite(image), image - background, 0.0), 0.0, None)
        centre = ((flux * cols).sum() / flux.sum(), (flux * rows).sum() / flux.sum())
        assert math.hypot(centre[0] - x, centre[1] - y) < 0.35, f"time bin {point.time_bin}"
        checked += 1
    assert checked == 4  # time bin 1 has no D5 or D6 plane


def test_wise0855_track_sits_on_the_faint_source_of_the_cold_frames(wise0855):
    """WISE 0855 is not in Gaia. Its CatWISE entry is placed by its published astrometry (make_fixture.TARGETS,
    parallax included), and that track lies within 0.5 px of the source fitted in the 4-5 micron frame of every
    visit (two Gaussians, the catalogued background star held at its CatWISE position). Measured 14 Nov 2026:
    0.18 to 0.24 px; CatWISE's own motion of WISE 0855, used before, put it 0.89 to 1.14 px off."""
    tracked = [s for s in wise0855.overlays.catwise if s.track is not None]
    assert [s.id for s in tracked] == [WISE0855_KEPT]
    times = Time([b.mjd_mid for b in wise0855.manifest.time_bins], format="mjd", scale="utc")
    ra, dec = catalogs.published_positions(TARGETS["wise0855"], times)
    assert [p.ra for p in tracked[0].track] == pytest.approx(ra, abs=1e-7)
    assert [p.dec for p in tracked[0].track] == pytest.approx(dec, abs=1e-7)
    neighbour = next(s for s in wise0855.overlays.catwise if s.id == WISE0855_NEIGHBOUR)
    nx, ny = sky_to_pixel(wise0855.grid, neighbour.ra, neighbour.dec)
    cold = presets.preset_wave_bins("cold")
    for point in tracked[0].track:
        x, y = sky_to_pixel(wise0855.grid, point.ra, point.dec)
        image = wise0855.frame(point.time_bin, cold)
        xi, yi, half = round(x), round(y), 6
        box = image[yi - half : yi + half + 1, xi - half : xi + half + 1]
        rows, cols = np.indices(box.shape, dtype=np.float64)
        ok = np.isfinite(box)

        def model(coords, a1, x1, y1, a2, s, bg, nx=nx, ny=ny):
            u_, v_ = coords
            return (
                a1 * np.exp(-((u_ - x1) ** 2 + (v_ - y1) ** 2) / (2 * s**2))
                + a2 * np.exp(-((u_ - nx) ** 2 + (v_ - ny) ** 2) / (2 * s**2))
                + bg
            )

        coords = (cols[ok] + xi - half, rows[ok] + yi - half)
        start = [np.nanmax(box), x, y, np.nanmax(box) / 3.0, 1.5, 0.0]
        p, _ = optimize.curve_fit(model, coords, box[ok], p0=start, maxfev=8000)
        assert math.hypot(p[1] - x, p[2] - y) < 0.5, f"time bin {point.time_bin}"


def test_unreliable_catwise_motions_give_no_track(barnard, wise0855):
    """Around Barnard's Star (G = 8.19) CatWISE lists hundreds of fast "movers" that Gaia does not see: none
    gets a track. WISE 0855's other two entries above 30 sigma are the object listed again: they are left out,
    since their catalogue positions of MJD 57170 lie about 83" from it in the 2025-26 frames. Without the Gaia
    answer to check against, no CatWISE motion is used at all."""
    rows = catalogs.parse_catwise_ipac(_text("catwise_barnard.tbl.gz"))
    loud = [
        r for r in rows if (catalogs.catwise_pm_snr(r) or 0.0) >= 5.0 and math.hypot(r.pmra, r.pmdec) > 50
    ]
    assert len(loud) > 200
    assert not any(s.track for s in barnard.overlays.catwise)
    ids = {s.id: s for s in wise0855.overlays.catwise}
    assert "J085508.34-071439.2" not in ids and "J085506.91-071437.5" not in ids
    wise_rows = catalogs.parse_catwise_ipac(_text("catwise_wise0855.tbl.gz"))
    assert not catalogs.catwise_tracks(wise_rows, wise0855.grid, wise0855.manifest.time_bins, None).any()
    entries = catalogs.published_matches(wise_rows, wise0855.manifest.time_bins)
    assert sorted(wise_rows[i].id for i in entries) == [
        "J085506.91-071437.5", "J085507.96-071439.3", "J085508.34-071439.2",
    ]  # fmt: skip


def test_published_astrometry_places_its_catwise_entry_and_spares_a_still_star_on_its_path(wise0855):
    """Synthetic CatWISE rows (pure logic): a still star within 3" of WISE 0855's published position at the
    CatWISE epoch is not taken for WISE 0855 (its motion disagrees), a row with WISE 0855's motion is, and
    the published track needs no Gaia answer (it is not a CatWISE motion)."""
    target = TARGETS["wise0855"]
    epoch = Time([catalogs.catwise_epoch_jyear()], format="jyear", scale="tt")
    ra, dec = catalogs.published_positions(target, epoch, parallax=False)
    near = float(ra[0]) + 1.5 / 3600.0, float(dec[0])
    synthetic_rows = [
        catalogs.CatwiseRow("J000000.00+000000.1", *near, 3.0, -2.0, 10.0, 10.0, 15.0, 15.0),  # still
        catalogs.CatwiseRow("J000000.00+000000.2", *near, -8000.0, 700.0, 100.0, 100.0, 18.0, 14.0),  # mover
    ]
    bins = wise0855.manifest.time_bins
    assert catalogs.published_matches(synthetic_rows, bins) == {1: target}
    sources = {s.id: s for s in catalogs.catwise_sources(synthetic_rows, wise0855.grid, bins)}  # no Gaia
    still = sources["J000000.00+000000.1"]
    assert still.track is None and (still.ra, still.dec) == pytest.approx(near, abs=1e-7)
    times = Time([b.mjd_mid for b in bins], format="mjd", scale="utc")
    t_ra, t_dec = catalogs.published_positions(target, times)
    assert [p.ra for p in sources["J000000.00+000000.2"].track] == pytest.approx(t_ra, abs=1e-7)
    assert [p.dec for p in sources["J000000.00+000000.2"].track] == pytest.approx(t_dec, abs=1e-7)


def test_tracks_only_for_sources_faster_than_50_mas_per_year(wise0855, barnard):
    for field in (wise0855, barnard):
        for star in field.overlays.gaia:
            fast = star.pmra is not None and math.hypot(star.pmra, star.pmdec) > 50.0
            assert (star.track is not None) == fast
            if star.track:
                assert [p.time_bin for p in star.track] == [b.id for b in field.manifest.time_bins]
    assert [s.source_id for s in barnard.overlays.gaia if s.track] == [BARNARD_ID, "4472836254100173184"]


def test_every_source_is_on_the_grid_at_one_visit_and_the_lists_are_ordered(wise0855, barnard):
    for field in (wise0855, barnard):
        assert field.overlays.upstreams.model_dump() == {"gaia": "ok", "catwise": "ok"}
        for source in [*field.overlays.gaia, *field.overlays.catwise]:
            points = source.track or [type("P", (), {"ra": source.ra, "dec": source.dec})()]
            xs, ys = sky_to_pixel(field.grid, [p.ra for p in points], [p.dec for p in points])
            inside = (np.asarray(xs) >= -0.5) & (np.asarray(xs) <= 118.5)
            inside &= (np.asarray(ys) >= -0.5) & (np.asarray(ys) <= 118.5)
            assert inside.any() or source.track is None
        g = [s.g for s in field.overlays.gaia if s.g is not None]
        assert g == sorted(g)
    assert (len(wise0855.overlays.gaia), len(barnard.overlays.gaia)) == (94, 829)


def test_response_serialises_as_the_contract_example(barnard):
    body = json.loads(barnard.overlays.model_dump_json())
    assert set(body) == {"contract", "status", "gaia", "catwise", "upstreams"}
    star = next(s for s in body["gaia"] if s["source_id"] == BARNARD_ID)
    assert star["epoch"] == 2016.0 and star["g"] == pytest.approx(8.194) and len(star["track"]) == 5
    assert all("track" not in s for s in body["catwise"])  # omitted, never null
    assert OverlaysResponse.model_validate(body) == barnard.overlays


# ------------------------------------------------------------------------------------------ upstream states
def _failing(*_):
    raise http.UpstreamError("HTTP 502", status=502)


def test_one_catalogue_down_does_not_lose_the_other(wise0855):
    gaia_query, catwise_query = _replay("wise0855")
    no_gaia = catalogs.overlays_for_manifest(
        wise0855.manifest, gaia_query=_failing, catwise_query=catwise_query
    )
    assert no_gaia.upstreams.model_dump() == {"gaia": "unavailable", "catwise": "ok"}
    assert no_gaia.gaia == [] and len(no_gaia.catwise) == len(wise0855.overlays.catwise)
    # nothing to check CatWISE motions against: no CatWISE motion moves a marker; WISE 0855's entry is placed by
    # its published astrometry, which needs no such check
    tracked = [s for s in no_gaia.catwise if s.track]
    assert [s.id for s in tracked] == [WISE0855_KEPT]
    assert tracked[0] == next(s for s in wise0855.overlays.catwise if s.id == WISE0855_KEPT)
    no_catwise = catalogs.overlays_for_manifest(
        wise0855.manifest, gaia_query=gaia_query, catwise_query=_failing
    )
    assert no_catwise.upstreams.model_dump() == {"gaia": "ok", "catwise": "unavailable"}
    assert no_catwise.gaia == wise0855.overlays.gaia and no_catwise.catwise == []


def test_a_cached_copy_is_served_as_stale(wise0855):
    stale = catalogs.overlays_for_manifest(
        wise0855.manifest, previous=wise0855.overlays, gaia_query=_failing, catwise_query=_failing
    )
    assert stale.upstreams.model_dump() == {"gaia": "stale", "catwise": "stale"}
    assert stale.gaia == wise0855.overlays.gaia and stale.catwise == wise0855.overlays.catwise


def test_a_service_that_hangs_is_cut_off_by_the_deadline(wise0855):
    def slow(ra, dec, radius, deadline):
        raise http.DeadlineExceeded("deadline expired")

    answer = catalogs.overlays_for_manifest(
        wise0855.manifest, gaia_query=slow, catwise_query=slow, deadline_s=0.1
    )
    assert answer.upstreams.model_dump() == {"gaia": "unavailable", "catwise": "unavailable"}


# ---------------------------------------------------------------------------------------------- network
@pytest.mark.network
def test_live_catalogues_answer_for_the_wise0855_field(wise0855):
    answer = catalogs.overlays_for_manifest(wise0855.manifest)
    assert answer.upstreams.model_dump() == {"gaia": "ok", "catwise": "ok"}
    assert len(answer.gaia) == len(wise0855.overlays.gaia)
    assert [s.id for s in answer.catwise if s.track] == [WISE0855_KEPT]
