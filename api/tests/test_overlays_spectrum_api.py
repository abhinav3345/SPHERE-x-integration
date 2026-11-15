"""GET /api/fields/{key}/overlays and /spectrum (Contract v1.0, sections 7.1 and 7.3), and the derived files of
the disk cache behind them. No network.

The archive and the catalogues are replaced by stand-ins that serve RECORDED REAL answers: the Gaia and CatWISE
answers of tests/data/catalogs, the SPHEREx windows and point-spread-function stamps of tests/data/photometry
(see the README of each folder), and the recorded field cache/fixtures/wise0855. Where a stand-in returns
something made up (a stand-in photometry that only counts its calls, an exposure list for a synthetic build),
it is named synthetic_*.
"""

from __future__ import annotations

import functools
import gzip
import json
import threading
import time
import zlib
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from tombaugh import catalogs, http, main, photometry, remote_fits
from tombaugh import spectrum as spectra
from tombaugh.cache import FieldCache
from tombaugh.main import EXPOSURES_NAME, OVERLAYS_NAME, Settings, create_app
from tombaugh.models import Manifest, OverlaysResponse, OverlayUpstreams, SpectrumResponse
from tombaugh.tools.make_fixture import TARGETS
from tombaugh.types import Cutout, Exposure

REPO = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO / "cache" / "fixtures"
CATALOGS = Path(__file__).parent / "data" / "catalogs"
PHOTOMETRY = Path(__file__).parent / "data" / "photometry"
WISE0855 = json.loads((FIXTURES_DIR / "wise0855" / "manifest.json").read_text(encoding="utf-8"))
KEY = WISE0855["key"]
CENTRE = (WISE0855["centre"]["ra"], WISE0855["centre"]["dec"])
EMPTY = (133.7514, -7.2616)  # tests/data/photometry: 21.6" from the nearest CatWISE source
NEIGHBOUR = "J085501.95-071428.2"  # the background star blended with WISE 0855 (Contract section 7.1)
WISE0855_CATWISE = "J085507.96-071439.3"  # the CatWISE entry of WISE 0855 that the overlays give a track
ERROR_KEYS = {"contract", "status", "code", "message"}


# ------------------------------------------------------------------------------------------ recorded data
def _text(name: str) -> str:
    return gzip.decompress((CATALOGS / name).read_bytes()).decode("utf-8")


@functools.cache
def _rows(name: str):
    return (
        catalogs.parse_gaia_csv(_text(f"gaia_{name}.csv.gz")),
        catalogs.parse_catwise_ipac(_text(f"catwise_{name}.tbl.gz")),
    )


class Catalogues:
    """Stands in for the two catalogue services with the recorded answers; `down` makes one fail."""

    def __init__(self, name: str = "wise0855") -> None:
        self.name = name
        self.down: set[str] = set()
        self.calls: list[str] = []

    def gaia(self, *_):
        self.calls.append("gaia")
        if "gaia" in self.down:
            raise http.UpstreamError("gave up after 5 attempts: HTTP 502")
        return _rows(self.name)[0], "recorded"

    def catwise(self, *_):
        self.calls.append("catwise")
        if "catwise" in self.down:
            raise http.UpstreamError("gave up after 4 attempts: HTTP 502")
        return _rows(self.name)[1], "recorded"

    def overlays(self, manifest, *, previous=None):
        return catalogs.overlays_for_manifest(
            manifest, previous=previous, gaia_query=self.gaia, catwise_query=self.catwise
        )


@functools.cache
def _windows() -> dict[str, list[Cutout]]:
    meta = json.loads((PHOTOMETRY / "windows.json").read_text())
    arrays = np.load(PHOTOMETRY / "windows.npz")
    sets: dict[str, list[Cutout]] = {}
    for i, m in enumerate(meta):
        header = zlib.decompress(arrays[f"header_{i}"].tobytes()).decode("ascii")
        cut = Cutout(
            exposure=Exposure(**m["exposure"]), image=arrays[f"image_{i}"], flags=arrays[f"flags_{i}"],
            x0=m["x0"], y0=m["y0"], wcs_header=header, lam=m["lam"], dlam=m["dlam"], mjd=m["mjd"],
            psf_fwhm=m["psf_fwhm"], zodi_level=m["zodi_level"], sky_var=m["sky_var"], version=m["version"],
        )  # fmt: skip
        sets.setdefault(m["set"], []).append(cut)
    return sets


@functools.cache
def _library() -> photometry.PsfLibrary:
    psf = np.load(PHOTOMETRY / "psf.npz")
    library = photometry.PsfLibrary(fetch=None)
    for name in psf.files:
        if not name.startswith("zones_"):
            continue
        det = int(name.split("_")[1])
        stamps = np.full((len(psf[f"xcenter_{det}"]), photometry.PSF_SIDE, photometry.PSF_SIDE), np.nan)
        stamps[psf[f"zones_{det}"]] = psf[f"stamps_{det}"]
        table = photometry.PsfTable(
            det, psf[f"xcenter_{det}"], psf[f"ycenter_{det}"], psf[f"cwave_{det}"], stamps
        )
        for cuts in _windows().values():
            for cut in cuts:
                if cut.exposure.det == det:
                    library.put(photometry.psf_key(cut.exposure), table)
    return library


def _field_exposures() -> list[Exposure]:
    """The exposures of the recorded windows of the WISE 0855 field: what a stand-in archive search lists."""
    unique = {cut.exposure.uid: cut.exposure for name in ("wise0855", "empty") for cut in _windows()[name]}
    return list(unique.values())


class Archive:
    """Stands in for the archive search and the bucket with the recorded windows; counts what was asked."""

    def __init__(self) -> None:
        self.searches: list[tuple[float, float]] = []
        self.reads: list[int] = []
        self.search_fails = False

    def discover(self, ra, dec, *, deadline=None, **_):
        self.searches.append((ra, dec))
        if self.search_fails:
            raise http.UpstreamError("gave up after 8 attempts: HTTP 502")
        return _field_exposures()

    def read_windows(self, exps, ra, dec, half_px, *, workers=16, deadline=None, progress=None, **_):
        exps = list(exps)
        self.reads.append(len(exps))
        near_empty = spectra._separations(ra, dec, np.array([EMPTY[0]]), np.array([EMPTY[1]]))[0] < 30.0
        recorded = {cut.exposure.uid: cut for cut in _windows()["empty" if near_empty else "wise0855"]}
        cutouts, failures = [], []
        for exposure in exps:
            if exposure.uid in recorded:
                cutouts.append(recorded[exposure.uid])
            else:
                failures.append((exposure, remote_fits.OFF_DETECTOR))
        return cutouts, failures


@pytest.fixture
def archive(monkeypatch) -> Archive:
    fake = Archive()
    monkeypatch.setattr(photometry.remote_fits, "read_windows", fake.read_windows)
    return fake


def make_client(tmp_path, *, catalogues=None, archive=None, measure=None, cache=None, build=None):
    settings = Settings(fixtures_dir=FIXTURES_DIR, probe_upstreams=False, rate_burst=100.0)
    catalogues = catalogues or Catalogues()
    kwargs = {
        "cache": cache or FieldCache(tmp_path / "cache", max_mb=50),
        "overlays": catalogues.overlays,
        "measure": measure or functools.partial(photometry.measure_with_stats, psf=_library()),
        "discover": (archive or Archive()).discover,
    }
    if build is not None:
        kwargs["build"] = build
    return TestClient(create_app(settings, **kwargs))


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == ERROR_KEYS and body["status"] == "error" and body["code"] == code
    return body


def raw_body(client: TestClient, url: str, headers: dict | None = None):
    with client.stream("GET", url, headers=headers) as response:
        return response, b"".join(response.iter_raw())


# ---------------------------------------------------------------------------------------------- overlays
def test_overlays_of_a_recorded_field_follow_the_contract_and_are_kept(tmp_path):
    catalogues = Catalogues()
    client = make_client(tmp_path, catalogues=catalogues)
    response = client.get(f"/api/fields/{KEY}/overlays")
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"contract", "status", "gaia", "catwise", "upstreams"}
    answer = OverlaysResponse.model_validate(body)
    assert answer.upstreams == OverlayUpstreams(gaia="ok", catwise="ok")
    # catalogs.py report, same recorded answers: 428 CatWISE entries, less WISE 0855's two repeated entries
    assert len(answer.gaia) == 94 and len(answer.catwise) == 426
    assert [s.id for s in answer.catwise if s.track] == [WISE0855_CATWISE]
    assert response.headers["cache-control"] == main.FINAL_CACHE_CONTROL
    assert sorted(catalogues.calls) == ["catwise", "gaia"]

    # final: served from the disk cache, by key and by the recorded field's name, without asking again
    assert client.get(f"/api/fields/{KEY}/overlays").json() == body
    assert client.get("/api/fields/wise0855/overlays").json() == body
    assert sorted(catalogues.calls) == ["catwise", "gaia"]
    # ... and still after a restart
    again = make_client(tmp_path, catalogues=catalogues, cache=FieldCache(tmp_path / "cache", max_mb=50))
    assert again.get(f"/api/fields/{KEY}/overlays").json() == body
    assert sorted(catalogues.calls) == ["catwise", "gaia"]


def test_overlays_are_sent_gzip_compressed_to_clients_that_take_it(tmp_path):
    client = make_client(tmp_path)
    response, raw = raw_body(client, f"/api/fields/{KEY}/overlays", {"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip" and raw[:2] == b"\x1f\x8b"
    assert "accept-encoding" in response.headers["vary"].lower()
    unpacked = json.loads(gzip.decompress(raw))
    response, plain = raw_body(client, f"/api/fields/{KEY}/overlays", {"Accept-Encoding": "identity"})
    assert "content-encoding" not in response.headers and json.loads(plain) == unpacked
    assert len(raw) < len(plain) / 3


@pytest.mark.parametrize(
    ("header", "expected"),
    [("gzip", True), ("gzip, deflate, br", True), ("br;q=1.0, gzip;q=0.8", True), ("*", True),
     ("gzip;q=0", False), ("identity", False), ("", False), (None, False), ("gzipx", False)],
)  # fmt: skip
def test_accept_encoding_is_read_with_its_quality(header, expected):
    assert main.accepts_gzip(header) is expected


def test_one_catalogue_down_is_unavailable_then_stale_and_never_kept_as_final(tmp_path, monkeypatch):
    catalogues = Catalogues()
    catalogues.down = {"catwise"}
    client = make_client(tmp_path, catalogues=catalogues)
    first = client.get(f"/api/fields/{KEY}/overlays")
    assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
    body = first.json()
    assert body["upstreams"] == {"gaia": "ok", "catwise": "unavailable"}
    assert body["catwise"] == [] and len(body["gaia"]) == 94

    # within five minutes the failed catalogue is not asked again
    calls = len(catalogues.calls)
    assert client.get(f"/api/fields/{KEY}/overlays").json() == body
    assert len(catalogues.calls) == calls

    # later, Gaia fails and CatWISE answers: Gaia's earlier list is served as "stale"
    monkeypatch.setattr(main, "OVERLAYS_RETRY_S", 0.0)
    catalogues.down = {"gaia"}
    second = client.get(f"/api/fields/{KEY}/overlays").json()
    assert second["upstreams"] == {"gaia": "stale", "catwise": "ok"}
    # WISE 0855's two other CatWISE entries are left out (the object listed again, catalogs.published_matches)
    assert second["gaia"] == body["gaia"] and len(second["catwise"]) == 426
    # no Gaia answer to check CatWISE motions against: only the entry placed by published astrometry moves
    assert [source["id"] for source in second["catwise"] if "track" in source] == [WISE0855_CATWISE]

    # both answer: final
    catalogues.down = set()
    third = client.get(f"/api/fields/{KEY}/overlays")
    assert third.json()["upstreams"] == {"gaia": "ok", "catwise": "ok"}
    assert third.headers["cache-control"] == main.FINAL_CACHE_CONTROL


def test_overlays_with_both_catalogues_down_say_so_and_keep_nothing(tmp_path):
    catalogues = Catalogues()
    catalogues.down = {"gaia", "catwise"}
    cache = FieldCache(tmp_path / "cache", max_mb=50)
    client = make_client(tmp_path, catalogues=catalogues, cache=cache)
    body = client.get(f"/api/fields/{KEY}/overlays").json()
    assert body["upstreams"] == {"gaia": "unavailable", "catwise": "unavailable"}
    assert body["gaia"] == [] and body["catwise"] == []
    assert cache.get_derived(KEY, OVERLAYS_NAME) is None


@pytest.mark.parametrize("key", ["0123456789abcdef", "nosuchfield", "..", "0123456789ABCDEF", "a%2Fb"])
def test_overlays_and_spectrum_of_an_unknown_key_answer_404(tmp_path, key):
    client = make_client(tmp_path)
    assert_error(client.get(f"/api/fields/{key}/overlays"), 404, "not_found")
    assert_error(
        client.get(f"/api/fields/{key}/spectrum", params={"ra": CENTRE[0], "dec": CENTRE[1]}),
        404,
        "not_found",
    )


# ---------------------------------------------------------------------------------------------- spectrum
def _weighted_mean(points) -> tuple[float, float]:
    """Inverse-variance mean of points (microjansky) and its error, as tests/test_photometry.py computes it."""
    weights = np.array([1.0 / p.err_ujy**2 for p in points])
    flux = float((weights * [p.flux_ujy for p in points]).sum() / weights.sum())
    return flux, float(weights.sum() ** -0.5)


def test_spectrum_of_wise0855_uses_its_published_motion_and_fits_the_neighbours(tmp_path, archive):
    """The click at the field centre (WISE 0855 at 2026.0) snaps to the published astrometry the package holds,
    not to the CatWISE entry the overlays track (its motion is 362 mas/yr off in Dec); the background star
    4-11" away is fitted jointly; the recorded windows are measured."""
    client = make_client(tmp_path, archive=archive)
    response = client.get(f"/api/fields/{KEY}/spectrum", params={"ra": CENTRE[0], "dec": CENTRE[1]})
    assert response.status_code == 200, response.text
    body = response.json()
    answer = SpectrumResponse.model_validate(body)
    assert json.loads(answer.model_dump_json()) == body  # the contract's keys, nothing added or lost
    assert answer.status == "ok" and answer.state == "ok"
    target = TARGETS["wise0855"]
    assert answer.target.snapped_to is not None
    assert (answer.target.snapped_to.catalog, answer.target.snapped_to.id) == ("simbad", target.label)
    assert answer.target.snapped_to.sep_arcsec < 1.0
    assert (answer.target.pmra, answer.target.pmdec, answer.target.epoch) == (
        target.pmra,
        target.pmdec,
        2000.0,
    )
    assert answer.method.kind == "joint_psf"
    # the bright background star and a faint CatWISE source (the photometry report: W2 = 17.8), both fitted;
    # never WISE 0855's own CatWISE entry
    assert {(n.catalog, n.id, n.fitted) for n in answer.neighbours} == {
        ("catwise", NEIGHBOUR, True),
        ("catwise", "J085502.09-071434.5", True),
    }
    assert len(answer.points) == 7  # the 7 recorded windows of this set: 4 at 4.4-5.0 micron, 3 below 2.4
    cold = [p for p in answer.points if p.lam >= 4.4]
    assert len(cold) == 4 and all(p.time_bin in (1, 3) for p in cold)  # the manifest's own time bins
    flux, error = _weighted_mean(cold)  # the statistic of tests/test_photometry.py (E7: about 600 at 4.4-4.8)
    assert 300.0 < flux < 800.0 and flux > 4.0 * error
    for point in answer.points:  # below 2.4 micron only the neighbour shines; the target agrees with zero
        if point.lam < 2.5 and point.quality == "good":
            assert abs(point.flux_ujy) < 3.0 * point.err_ujy
    assert response.headers["cache-control"] == main.FINAL_CACHE_CONTROL
    assert archive.searches == [CENTRE]  # a recorded field: its exposures were found again, once


def test_wise0855_own_catwise_entries_are_never_its_neighbours():
    manifest, overlays = _overlays("wise0855")
    choice = spectra.choose(overlays, manifest, *CENTRE)
    assert choice.snapped_to.catalog == "simbad"
    entries = {s.id for s in overlays.catwise if s.track}
    assert entries == {WISE0855_CATWISE}
    assert not entries & {n.id for n in choice.neighbours}
    # clicking right on the CatWISE track still measures the published astrometry
    tracked = next(s for s in overlays.catwise if s.id == WISE0855_CATWISE)
    on_track = spectra.choose(overlays, manifest, tracked.track[1].ra, tracked.track[1].dec)
    assert on_track.identity == choice.identity


def test_a_measured_spectrum_and_the_exposure_list_are_kept(tmp_path, archive):
    cache = FieldCache(tmp_path / "cache", max_mb=50)
    client = make_client(tmp_path, archive=archive, cache=cache)
    params = {"ra": CENTRE[0], "dec": CENTRE[1]}
    first = client.get(f"/api/fields/{KEY}/spectrum", params=params).json()
    assert len(archive.reads) == 1
    assert client.get(f"/api/fields/{KEY}/spectrum", params=params).json() == first
    # another click on the same source (2" away) is the same measurement, answered with that click's own
    # separation from the source (the kept answer holds the first click's)
    nudged = {"ra": CENTRE[0] + 2.0 / 3600.0, "dec": CENTRE[1]}
    again = client.get(f"/api/fields/{KEY}/spectrum", params=nudged).json()
    assert len(archive.reads) == 1 and len(archive.searches) == 1
    manifest, overlays = _overlays("wise0855")
    expected = spectra.choose(overlays, manifest, nudged["ra"], nudged["dec"]).snapped_to
    assert again["target"]["snapped_to"] == expected.model_dump()
    assert expected.sep_arcsec != first["target"]["snapped_to"]["sep_arcsec"]
    again["target"]["snapped_to"]["sep_arcsec"] = first["target"]["snapped_to"]["sep_arcsec"]
    assert again == first
    stored = spectra.exposures_from_json(gzip.decompress(cache.get_derived(KEY, EXPOSURES_NAME)))
    assert {e.uid for e in stored} == {e.uid for e in _field_exposures()}
    # the next click elsewhere reads windows again but needs no new archive search
    client.get(f"/api/fields/{KEY}/spectrum", params={"ra": EMPTY[0], "dec": EMPTY[1]})
    assert len(archive.reads) == 2 and len(archive.searches) == 1


def test_spectrum_of_empty_sky_is_measured_at_the_click_and_agrees_with_zero(tmp_path, archive):
    client = make_client(tmp_path, archive=archive)
    body = client.get(f"/api/fields/{KEY}/spectrum", params={"ra": EMPTY[0], "dec": EMPTY[1]}).json()
    answer = SpectrumResponse.model_validate(body)
    assert answer.target.snapped_to is None and (answer.target.ra, answer.target.dec) == EMPTY
    assert answer.state == "ok" and answer.method.kind == "aperture" and answer.neighbours == []
    assert len(answer.points) == 4
    for point in answer.points:
        assert abs(point.flux_ujy) < 3.0 * point.err_ujy


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"ra": "133.7598"},
        {"dec": "-7.2422"},
        {"ra": "abc", "dec": "-7.2422"},
        {"ra": "133.7598", "dec": "nan"},
        {"ra": "400", "dec": "-7.2422"},
        {"ra": "133.7598", "dec": "-91"},
        {"ra": "133.9", "dec": "-7.2422"},  # 8.3' east of the centre: outside the 6' field
        {"ra": "133.7598", "dec": "-7.4"},
        {"ra": "313.7598", "dec": "7.2422"},  # the other side of the sky
    ],
)
def test_spectrum_requests_outside_the_field_or_malformed_answer_400(tmp_path, params):
    calls = []
    client = make_client(tmp_path, measure=lambda *a, **k: calls.append(a))
    assert_error(client.get(f"/api/fields/{KEY}/spectrum", params=params), 400, "bad_request")
    assert calls == []


def test_spectrum_needs_the_catalogues(tmp_path, archive):
    catalogues = Catalogues()
    catalogues.down = {"catwise"}
    client = make_client(tmp_path, catalogues=catalogues, archive=archive)
    body = assert_error(
        client.get(f"/api/fields/{KEY}/spectrum", params={"ra": CENTRE[0], "dec": CENTRE[1]}),
        503,
        "upstream_unavailable",
    )
    assert "catalogues" in body["message"] and archive.reads == []


def test_spectrum_when_the_archive_cannot_be_searched_answers_503(tmp_path, archive):
    archive.search_fails = True
    client = make_client(tmp_path, archive=archive)
    body = assert_error(
        client.get(f"/api/fields/{KEY}/spectrum", params={"ra": CENTRE[0], "dec": CENTRE[1]}),
        503,
        "upstream_unavailable",
    )
    assert "attempts" not in body["message"]  # the upstream's own words stay in the log


def _synthetic_stats(**counts) -> photometry.SpectrumStats:
    return photometry.SpectrumStats(requested=counts.pop("requested", 10), **counts)


def _synthetic_answer(state="no_data") -> SpectrumResponse:
    return SpectrumResponse(
        state=state,
        target={"ra": EMPTY[0], "dec": EMPTY[1]},
        method={"kind": "aperture", "radius_px": 2, "encircled_energy": 0.0, "annulus_px": [5, 9],
                "systematic_floor": 0.03},
        time_span=None,
    )  # fmt: skip


def test_an_incomplete_spectrum_says_so_and_is_not_kept(tmp_path):
    calls = []

    def synthetic_measure(exposures, ra, dec, **kwargs):
        calls.append(len(exposures))
        return _synthetic_answer(), _synthetic_stats(read=7, timed_out=3)

    cache = FieldCache(tmp_path / "cache", max_mb=50)
    client = make_client(tmp_path, measure=synthetic_measure, cache=cache)
    params = {"ra": EMPTY[0], "dec": EMPTY[1]}
    for expected_calls in (1, 2):  # measured again: an incomplete answer is never served from the cache
        response = client.get(f"/api/fields/{KEY}/spectrum", params=params)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.headers[main.INCOMPLETE_HEADER] == "3 of 10 exposures not measured; not cached"
        assert len(calls) == expected_calls


def test_spectra_beyond_the_slots_answer_429_and_healthz_answers_meanwhile(tmp_path):
    release = threading.Event()
    started = threading.Event()

    def synthetic_slow_measure(exposures, ra, dec, **kwargs):
        started.set()
        release.wait(10)
        return _synthetic_answer(), _synthetic_stats()

    client = make_client(tmp_path, measure=synthetic_slow_measure)
    service = client.app.state.service
    for _ in range(main.SPECTRUM_SLOTS - 1):  # all slots but one are taken by other spectra
        assert service._spectrum_slots.acquire(blocking=False)
    results = []
    worker = threading.Thread(
        target=lambda: results.append(
            client.get(f"/api/fields/{KEY}/spectrum", params={"ra": EMPTY[0], "dec": EMPTY[1]})
        )
    )
    worker.start()
    assert started.wait(10)
    began = time.monotonic()
    assert client.get("/healthz").status_code == 200
    assert time.monotonic() - began < 0.5  # liveness does not wait for the measurement
    other = client.get(f"/api/fields/{KEY}/spectrum", params={"ra": CENTRE[0], "dec": CENTRE[1]})
    body = assert_error(other, 429, "busy")
    assert int(other.headers["retry-after"]) >= 1 and "spectra" in body["message"]
    assert client.get("/api/fields", params={"fixture": "barnard"}).status_code == 200  # never blocked
    release.set()
    worker.join(10)
    assert results and results[0].status_code == 200
    for _ in range(main.SPECTRUM_SLOTS - 1):
        service._spectrum_slots.release()


def test_identical_spectrum_requests_share_one_measurement(tmp_path):
    release = threading.Event()
    calls = []

    def synthetic_slow_measure(exposures, ra, dec, **kwargs):
        calls.append(1)
        release.wait(10)
        return _synthetic_answer(), _synthetic_stats()

    client = make_client(tmp_path, measure=synthetic_slow_measure)
    results = []
    url = f"/api/fields/{KEY}/spectrum?ra={EMPTY[0]}&dec={EMPTY[1]}"
    workers = [threading.Thread(target=lambda: results.append(client.get(url))) for _ in range(3)]
    for worker in workers:
        worker.start()
    for _ in range(200):
        if calls:
            break
        time.sleep(0.01)
    time.sleep(0.2)
    release.set()
    for worker in workers:
        worker.join(10)
    assert [r.status_code for r in results] == [200, 200, 200] and len(calls) == 1


# ------------------------------------------------------------------------------- a built field's spectrum
def test_a_built_field_keeps_its_exposure_list_and_its_spectrum_reads_it(tmp_path):
    """The build stores the exposures it selected; the spectrum measures them without searching again."""
    from test_api import poll, synthetic_build_result  # the shared stand-in of the build

    synthetic_exposures = [
        Exposure(f"S0_{i:04d}", 6, 60800.5 + i, "spherex_dr1", "nasa-irsa-spherex", "us-east-1", "k")
        for i in range(3)
    ] + [Exposure("S9_0000", 6, 70000.0, "spherex_dr1", "nasa-irsa-spherex", "us-east-1", "k")]

    def synthetic_build(ra, dec, fov, *, progress=None, deadline_s=120.0, known=None):
        manifest, frames, stats = synthetic_build_result(ra, dec, fov)
        stats.exposures = list(synthetic_exposures)
        return manifest, frames, stats

    seen = []

    def synthetic_measure(exposures, ra, dec, **kwargs):
        seen.append(([e.uid for e in exposures], kwargs["time_bins"]))
        return _synthetic_answer(), _synthetic_stats(requested=len(exposures))

    archive = Archive()
    client = make_client(tmp_path, archive=archive, measure=synthetic_measure, build=synthetic_build)
    final, _ = poll(client, "/api/fields?ra=76.9563&dec=30.4012&fov=4")
    manifest = Manifest.model_validate(final.json())
    response = client.get(f"/api/fields/{manifest.key}/spectrum", params={"ra": 76.9563, "dec": 30.4012})
    assert response.status_code == 200
    [(uids, time_bins)] = seen
    assert uids == ["S0_0000/D6", "S0_0001/D6", "S0_0002/D6"]  # the one outside every visit is left out
    assert [b.id for b in time_bins] == [b.id for b in manifest.time_bins]
    assert archive.searches == []


# ------------------------------------------------------------------------------------- choosing the target
@functools.cache
def _overlays(name: str) -> tuple[Manifest, OverlaysResponse]:
    manifest = Manifest.model_validate_json(
        (FIXTURES_DIR / name / "manifest.json").read_text(encoding="utf-8")
    )
    return manifest, Catalogues(name).overlays(manifest)


def test_a_click_on_barnards_star_snaps_to_gaia_with_its_motion_and_without_itself_as_neighbour():
    manifest, overlays = _overlays("barnard")
    star = next(s for s in overlays.gaia if s.source_id == "4472832130942575872")
    visit = star.track[2]
    choice = spectra.choose(overlays, manifest, visit.ra + 1.0 / 3600.0, visit.dec)
    assert choice.snapped_to.catalog == "gaia" and choice.snapped_to.id == star.source_id
    assert choice.snapped_to.sep_arcsec < 1.5
    assert (choice.target.pmra, choice.target.pmdec, choice.target.epoch) == (star.pmra, star.pmdec, 2016.0)
    assert choice.identity == f"gaia:{star.source_id}"
    at_epoch = choice.target.position_at_year(catalogs.catwise_epoch_jyear())
    for neighbour in choice.neighbours:  # CatWISE's own entry of the star is not its neighbour
        assert neighbour.catalog == "catwise"
        separation = spectra._separations(*at_epoch, np.array([neighbour.ra]), np.array([neighbour.dec]))[0]
        assert separation >= spectra.SAME_OBJECT_ARCSEC


def test_a_click_far_from_any_source_is_measured_where_it_is_rounded_to_four_decimals():
    manifest, overlays = _overlays("wise0855")
    choice = spectra.choose(overlays, manifest, EMPTY[0] + 0.00002, EMPTY[1] - 0.00001)
    assert choice.snapped_to is None and not choice.target.moves
    assert (choice.target.ra, choice.target.dec) == EMPTY
    assert choice.identity == f"position:{EMPTY[0]:.4f},{EMPTY[1]:.4f}"
    assert choice.neighbours == ()  # the nearest CatWISE source is 21.6" away


def test_a_catwise_source_without_a_track_does_not_move():
    manifest, overlays = _overlays("wise0855")
    source = next(s for s in overlays.catwise if s.id == NEIGHBOUR)
    assert source.track is None and source.pmra is not None
    choice = spectra.choose(overlays, manifest, source.ra, source.dec)
    assert choice.snapped_to.id == NEIGHBOUR and not choice.target.moves
    assert choice.target.pmra is None and choice.target.epoch == source.epoch


def test_inside_the_field_means_on_the_grid():
    manifest, _ = _overlays("wise0855")
    half = (manifest.grid.nx - 1) / 2.0 * 3.075 / 3600.0
    assert spectra.inside_field(manifest, *CENTRE)
    assert spectra.inside_field(manifest, CENTRE[0], CENTRE[1] + half)
    assert not spectra.inside_field(manifest, CENTRE[0], CENTRE[1] + half + 2.0 / 3600.0)
    assert not spectra.inside_field(manifest, (CENTRE[0] + 180.0) % 360.0, -CENTRE[1])


def test_exposure_lists_round_trip_and_keep_only_the_visits():
    manifest, _ = _overlays("wise0855")
    exposures = _field_exposures()
    assert spectra.exposures_from_json(spectra.exposures_to_json(exposures)) == exposures
    later = Exposure("2027W01_1A_0001_1", 6, 61500.0, "spherex_qr3", "nasa-irsa-spherex", "us-east-1", "k")
    assert spectra.within_visits([*exposures, later], manifest.time_bins) == exposures
    for broken in (b"{}", b'"x"', b"[1]", b'[{"obs_id": "a"}]'):
        with pytest.raises(ValueError):
            spectra.exposures_from_json(broken)


# -------------------------------------------------------------------------------------- derived cache files
def test_derived_files_round_trip_survive_a_restart_and_refuse_paths(tmp_path):
    cache = FieldCache(tmp_path, max_mb=10)
    key = "0123456789abcdef"
    assert cache.get_derived(key, "overlays.json.gz") is None
    cache.put_derived(key, "overlays.json.gz", b"one")
    assert cache.get_derived(key, "overlays.json.gz") == b"one" and cache.derived_bytes() == 3
    assert FieldCache(tmp_path, max_mb=10).get_derived(key, "overlays.json.gz") == b"one"
    for name in ("../x", "a/b", "", ".hidden", "A"):
        with pytest.raises(ValueError):
            cache.put_derived(key, name, b"x")
        assert cache.get_derived(key, name) is None
    with pytest.raises(ValueError):
        cache.put_derived("..", "x.json", b"x")
    assert not list(tmp_path.rglob("*.tmp"))


def test_derived_files_have_their_own_cap_and_go_with_their_field(tmp_path):
    now = [1000.0]
    cache = FieldCache(tmp_path, max_mb=10, clock=lambda: now[0])
    assert cache.derived_max_bytes == 16 * 1024 * 1024  # at least 16 MB
    cache.derived_max_bytes = 10
    keys = [f"{i:016x}" for i in range(1, 5)]
    for key in keys[:3]:
        now[0] += 1.0
        assert cache.put_derived(key, "a.json", b"1234") == [] or key == keys[2]
    assert cache.get_derived(keys[0], "a.json") is None  # the least recently used went first
    assert cache.get_derived(keys[2], "a.json") == b"1234" and cache.derived_bytes() <= 10

    cache.derived_max_bytes = 1000
    cache.put(keys[3], b"{}", b"\x00\x00")
    cache.put_derived(keys[3], "exposures.json.gz", b"xyz")
    cache._remove(keys[3])  # the field is evicted: its derived files go with it
    assert cache.get_derived(keys[3], "exposures.json.gz") is None
    assert not (tmp_path / "derived" / keys[3]).exists()


def test_status_counts_derived_files_as_cache_use(tmp_path):
    cache = FieldCache(tmp_path / "cache", max_mb=50)
    cache.put_derived(KEY, "big.bin", bytes(3 * 1024 * 1024))
    client = make_client(tmp_path, cache=cache)
    assert client.get("/api/status").json()["cache"]["used_mb"] == 3


def test_a_request_that_joins_a_slow_catalogue_query_gets_429_not_500(tmp_path, monkeypatch):
    release = threading.Event()
    catalogues = Catalogues()

    def slow_overlays(manifest, *, previous=None):
        release.wait(10)
        return catalogues.overlays(manifest, previous=previous)

    settings = Settings(fixtures_dir=FIXTURES_DIR, probe_upstreams=False)
    app = create_app(settings, cache=FieldCache(tmp_path / "cache", max_mb=50), overlays=slow_overlays)
    client = TestClient(app)
    monkeypatch.setattr(catalogs, "DEADLINE_S", -9.9)  # a joiner waits DEADLINE_S + 10 s: here 0.1 s
    first = []
    owner = threading.Thread(target=lambda: first.append(client.get(f"/api/fields/{KEY}/overlays")))
    owner.start()
    time.sleep(0.2)
    for url in (f"/api/fields/{KEY}/overlays", f"/api/fields/{KEY}/spectrum?ra={EMPTY[0]}&dec={EMPTY[1]}"):
        response = client.get(url)
        assert_error(response, 429, "busy")
        assert int(response.headers["retry-after"]) >= 1
    release.set()
    owner.join(10)
    assert first and first[0].status_code == 200
