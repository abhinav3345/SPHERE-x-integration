"""Golden tests on the recorded answers of the two recorded REAL fields, and on the tool that records them.

``cache/fixtures/<name>/overlays.json`` and ``spectrum.json`` hold, in an envelope (Contract v1.0, section 8),
the answers of GET /api/fields/{key}/overlays and GET /api/fields/{key}/spectrum?ra=&dec= (sections 7.3 and
7.1) for the recorded field ``<name>``, as the engine served them live (``python -m
tombaugh.tools.record_answers <name>``). The page shows them, labelled as recorded, when no live answer can be
had. Nothing here uses the network. What these tests prove:

* each file is the envelope of its own field, byte for byte as the tool writes it (compact, the fixed key order,
  one trailing newline), its response is the contract model's own JSON, and its response and recording time are
  the recorded ones: a file edited by hand, or moved to the other field, fails;
* the overlays are exactly what ``catalogs.overlays_for_manifest`` makes, offline, of the catalogue answers kept
  in ``tests/data/catalogs`` (the same services asked the same cone): every position at every visit is the
  package's model; the tracks also agree with the astrometry the answer itself carries;
* the manifest's fixture stars are in the Gaia list at their recorded pixels; WISE 0855 has one tracked CatWISE
  source, placed by its published astrometry, and its track passes the field centre;
* each spectrum was measured for what the recorded overlays say at the request position; WISE 0855 is detected
  at 4.4-4.8 micron and consistent with zero below 3.8 micron; Barnard's Star is "saturated", with no points;
* the tool writes only final answers, and what it writes is what the routes serve.

The stand-ins of the tool tests serve recorded real answers (``tests/test_overlays_spectrum_api.py``); the
stand-in photometry that only counts its calls is named synthetic_*.
"""

from __future__ import annotations

import datetime as dt
import functools
import gzip
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest
from astropy.time import Time
from pydantic import ValidationError
from test_overlays_spectrum_api import (
    Archive,
    Catalogues,
    _library,
    _synthetic_answer,
    _synthetic_stats,
    make_client,
)

from tombaugh import CONTRACT_VERSION, __version__, catalogs, photometry, presets
from tombaugh import spectrum as spectra
from tombaugh.cache import FieldCache
from tombaugh.grid import sky_to_pixel
from tombaugh.main import INCOMPLETE_HEADER
from tombaugh.models import Manifest, OverlaysResponse, SpectrumResponse
from tombaugh.tools import make_fixture, record_answers
from tombaugh.tools.make_fixture import TARGETS

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "cache" / "fixtures"
CATALOGS = Path(__file__).parent / "data" / "catalogs"
NAMES = ("wise0855", "barnard")
ROUTES = ("overlays", "spectrum")
FILES = [(name, route) for name in NAMES for route in ROUTES]
ENVELOPE_KEYS = [
    "contract",
    "kind",
    "route",
    "field",
    "key",
    "pipeline_version",
    "recorded_at",
    "request",
    "response",
]
JOIN = b',"response":'
TIME_FORM = "%Y-%m-%dT%H:%M:%SZ"
# What was recorded: the SHA-256 of each response, from the tool's live runs of 15 Nov 2026 (UTC). The four
# responses are byte for byte those of a first recording at 2026-11-14T23:47:33Z: the engine answered the same
# twice. The digests hold every value of a response; `recorded_at` is held by its form and its range (after the
# field's build, not in the future), so recording again with the same answers needs no change here. A response
# that changes is a change in the engine or in the archives, to be explained in the same change as its digest.
RECORDED = {
    ("wise0855", "overlays"): "c0a645b6b1995ee46915096abe59e86ab3d6855245d75c3b939c0977bb38382c",
    ("wise0855", "spectrum"): "2e55d703bed3c3a7cc93db18ab0f9aa123203f6e7f4d963fb44b71d67f9d2e8a",
    ("barnard", "overlays"): "09b700b7892b2ff17f03993c390f23e4e6be5c225f47c0afcbf401074dfbbe42",
    ("barnard", "spectrum"): "00404e3715fb851dc392f8966c71fb2be67acaea537b34d4f31366373de70911",
}
WISE0855_CATWISE = "J085507.96-071439.3"  # the CatWISE entry of WISE 0855 that the overlays give a track
NEIGHBOUR = "J085501.95-071428.2"  # the background star blended with WISE 0855 (Contract section 7.1)
BARNARD_GAIA = TARGETS["barnard"].source.split()[-1]  # "Gaia DR3 4472832130942575872"


# ----------------------------------------------------------------------------------------------- reading
@functools.cache
def manifest_of(name: str) -> Manifest:
    return Manifest.model_validate_json((FIXTURES_DIR / name / "manifest.json").read_bytes())


@functools.cache
def file_bytes(name: str, route: str) -> bytes:
    return (FIXTURES_DIR / name / f"{route}.json").read_bytes()


def body_of(data: bytes) -> bytes:
    """The response bytes of an envelope: after its first ',"response":', less the closing brace and newline."""
    start = data.find(JOIN)
    return data[start + len(JOIN) : -2] if start >= 0 else b""


@functools.cache
def answer_of(name: str, route: str) -> OverlaysResponse | SpectrumResponse:
    return record_answers.MODELS[route].model_validate_json(body_of(file_bytes(name, route)))


def layout_problems(name: str, route: str, data: bytes) -> list[str]:
    """What keeps `data` from being a recorded `route` answer of the recorded field `name` (the envelope of
    contract section 8, and rule R1 of the page: contract, kind, route, field and key as expected, a response that
    passes the contract's validation); [] when nothing does."""
    manifest = manifest_of(name)
    try:
        envelope = json.loads(data)
    except ValueError as exc:
        return [f"not JSON: {exc}"]
    if not isinstance(envelope, dict) or list(envelope) != ENVELOPE_KEYS:
        return [f"not the envelope's keys in their order: {list(envelope)[:10]}"]
    problems = []
    expected = {
        "contract": CONTRACT_VERSION,
        "kind": "recorded_answer",
        "route": route,
        "field": name,
        "key": manifest.key,
        "pipeline_version": manifest.provenance.pipeline_version,
        "request": {} if route == "overlays" else {"ra": manifest.request.ra, "dec": manifest.request.dec},
    }
    problems += [f"{k} is {envelope[k]!r}, not {v!r}" for k, v in expected.items() if envelope[k] != v]
    stamp = envelope["recorded_at"]
    try:
        when = dt.datetime.strptime(stamp, TIME_FORM).replace(tzinfo=dt.UTC)
    except (TypeError, ValueError):
        problems.append(f"recorded_at {stamp!r} is not YYYY-MM-DDTHH:MM:SSZ")
    else:
        built = dt.datetime.strptime(manifest.provenance.built_at, TIME_FORM).replace(tzinfo=dt.UTC)
        if not (
            re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", stamp)
            and built <= when <= dt.datetime.now(dt.UTC)
        ):
            problems.append(f"recorded_at {stamp} is not between the field's build ({built}) and now")
    head = {k: v for k, v in envelope.items() if k != "response"}
    body = body_of(data)
    if (
        data
        != json.dumps(head, separators=(",", ":"), ensure_ascii=False)[:-1].encode() + JOIN + body + b"}\n"
    ):
        problems.append("not the compact envelope, in its key order, with one trailing newline")
    try:
        answer = record_answers.MODELS[route].model_validate_json(body)
    except ValidationError as exc:
        problems.append(f"the response fails the contract's validation: {exc.error_count()} errors")
    else:
        if answer.model_dump_json().encode() != body:
            problems.append("the response is not the contract model's own JSON")
        if answer.contract != CONTRACT_VERSION or answer.status != "ok":
            problems.append(f"the response is contract {answer.contract}, status {answer.status}")
    return problems


def recorded_problems(name: str, route: str, data: bytes) -> list[str]:
    """Differences between `data` and what was recorded (RECORDED): its response's digest."""
    if hashlib.sha256(body_of(data)).hexdigest() != RECORDED[(name, route)]:
        return ["the response is not the recorded one"]
    return []


def _stamp(when: dt.datetime) -> str:
    return when.astimezone(dt.UTC).strftime(TIME_FORM)


def _built(name: str) -> dt.datetime:
    return dt.datetime.strptime(manifest_of(name).provenance.built_at, TIME_FORM).replace(tzinfo=dt.UTC)


def _times(manifest: Manifest) -> Time:
    return Time([b.mjd_mid for b in manifest.time_bins], format="mjd", scale="utc")


def _on_grid(grid, x, y) -> np.ndarray:
    """Booleans: the pixel position lies on the grid (pixel centres -0.5 to n - 0.5, as catalogs.py keeps)."""
    x, y = np.asarray(x), np.asarray(y)
    low, high = -catalogs.GRID_EDGE_PX, grid.n - 1 + catalogs.GRID_EDGE_PX
    return (x >= low) & (x <= high) & (y >= low) & (y <= high)


def _apart_arcsec(ra1, dec1, ra2, dec2) -> list[float]:
    return [photometry.separation_arcsec(*pair) for pair in zip(ra1, dec1, ra2, dec2, strict=True)]


# ------------------------------------------------------------------------------------- the files themselves
@pytest.mark.parametrize(("name", "route"), FILES)
def test_each_file_is_the_envelope_of_its_own_field(name, route):
    data = file_bytes(name, route)
    assert layout_problems(name, route, data) == []
    assert data.count(b"\n") == 1
    # ... and exactly what the tool writes for that response at that time
    envelope = json.loads(data)
    written = record_answers.envelope(route, name, manifest_of(name), envelope["recorded_at"], body_of(data))
    assert written == data


@pytest.mark.parametrize(("name", "route"), FILES)
def test_each_file_holds_the_recorded_response(name, route):
    """The recorded response (RECORDED): a value edited by hand, however well formed, fails here."""
    assert recorded_problems(name, route, file_bytes(name, route)) == []
    # recorded by the pipeline that made the field, which is this package (as test_fixtures_golden holds)
    assert json.loads(file_bytes(name, route))["pipeline_version"] == __version__


def _with_next_digit(data: bytes, label: bytes) -> bytes:
    """`data` with the first digit after `label` raised by one (mod 10): still well-formed JSON."""
    at = data.index(label) + len(label)
    return data[:at] + str((int(data[at : at + 1]) + 1) % 10).encode() + data[at + 1 :]


@pytest.mark.parametrize(("name", "route"), FILES)
def test_the_checks_refuse_the_other_fields_file_and_hand_edits(name, route):
    """The checks above have teeth: each of these is refused."""
    data = file_bytes(name, route)
    other = next(n for n in NAMES if n != name)
    moved = layout_problems(name, route, file_bytes(other, route))
    assert any(p.startswith("key is") for p in moved) and any(p.startswith("field is") for p in moved)
    pretty = (json.dumps(json.loads(data), indent=1) + "\n").encode()
    assert layout_problems(name, route, pretty) != []
    assert layout_problems(name, route, data[:-1]) != []  # no trailing newline
    assert layout_problems(name, route, data + b"\n") != []
    assert layout_problems(name, route, data.replace(b'"kind":"recorded_answer"', b'"kind":"live"')) != []
    swapped = data.replace(f'"route":"{route}"'.encode(), b'"route":"x"')
    assert layout_problems(name, route, swapped) != []
    stamp = json.loads(data)["recorded_at"]
    recorded = dt.datetime.strptime(stamp, TIME_FORM).replace(tzinfo=dt.UTC)
    built = _built(name)
    for wrong in (
        recorded.strftime("%Y-%m-%d %H:%M:%S"),  # another form
        _stamp(built - dt.timedelta(seconds=1)),  # before the field was built
        _stamp(dt.datetime.now(dt.UTC) + dt.timedelta(days=1)),  # in the future
    ):
        assert layout_problems(name, route, data.replace(stamp.encode(), wrong.encode())) != [], wrong
    # Any time from the build to the recording passes: the time is held by its form and range, the response
    # by its digest, so recording again with the same answers changes nothing that these tests hold.
    again = data.replace(stamp.encode(), _stamp(built + (recorded - built) / 2).encode())
    assert layout_problems(name, route, again) == [] and recorded_problems(name, route, again) == []
    edited = _with_next_digit(data, b'"g":' if route == "overlays" else b'"sep_arcsec":')
    assert layout_problems(name, route, edited) == []
    assert recorded_problems(name, route, edited) == ["the response is not the recorded one"]


def test_recorded_values():
    """What the four answers say, for readers (the digests above hold every value)."""
    overlays = {name: answer_of(name, "overlays") for name in NAMES}
    assert [(len(o.gaia), len(o.catwise)) for o in overlays.values()] == [(94, 426), (829, 600)]
    tracks = [
        (sum(1 for s in o.gaia if s.track), sum(1 for s in o.catwise if s.track)) for o in overlays.values()
    ]
    assert tracks == [(1, 1), (2, 0)]
    wise0855, barnard = answer_of("wise0855", "spectrum"), answer_of("barnard", "spectrum")
    assert (wise0855.state, wise0855.method.kind, len(wise0855.points), len(wise0855.binned)) == (
        "ok",
        "joint_psf",
        257,
        65,
    )
    assert (barnard.state, barnard.method.kind, len(barnard.points), len(barnard.binned)) == (
        "saturated",
        "aperture",
        0,
        0,
    )
    # the figure quoted in ENGINE_NOTES and photometry.py: 18 good points at 4.4-4.8 micron, 562.0 +- 44.7
    good = [p for p in wise0855.points if p.quality == "good" and 4.4 <= p.lam <= 4.8]
    weights = np.array([1.0 / p.err_ujy**2 for p in good])
    flux = float((weights * [p.flux_ujy for p in good]).sum() / weights.sum())
    assert (len(good), round(flux, 1), round(float(weights.sum() ** -0.5), 1)) == (18, 562.0, 44.7)


# ----------------------------------------------------------------------------------------------- overlays
def _recorded_rows(name: str):
    gaia = gzip.decompress((CATALOGS / f"gaia_{name}.csv.gz").read_bytes()).decode("utf-8")
    catwise = gzip.decompress((CATALOGS / f"catwise_{name}.tbl.gz").read_bytes()).decode("utf-8")
    return catalogs.parse_gaia_csv(gaia), catalogs.parse_catwise_ipac(catwise)


@pytest.mark.parametrize("name", NAMES)
def test_overlays_are_the_package_model_of_the_recorded_catalogue_rows(name):
    """tests/data/catalogs keeps the two services' answers recorded at 19:55 UTC on 14 Nov 2026 for these fields.
    They answered the question the package asks now (same service, table, columns and cone), so the live answer
    recorded later is byte for byte what overlays_for_manifest makes of them offline: every source, every
    track point and the order of both lists are the package's model (Gaia DR3 and CatWISE2020 are fixed
    releases)."""
    manifest = manifest_of(name)
    grid = catalogs.field_grid(manifest)
    samples = json.loads((CATALOGS / "samples.json").read_text(encoding="utf-8"))
    asked = next(entry for entry in samples["fields"] if entry["field"] == name)
    url, table = make_fixture.TAP_SERVICES[0]
    gaia_radius = catalogs.search_radius_deg(grid, manifest.time_bins, catalogs.GAIA_EPOCH)
    catwise_radius = catalogs.search_radius_deg(grid, manifest.time_bins, catalogs.catwise_epoch_jyear())
    assert asked["gaia"]["url"] == url
    assert asked["gaia"]["params"] == catalogs.gaia_query_params(table, grid.ra0, grid.dec0, gaia_radius)
    assert asked["catwise"]["params"] == catalogs.catwise_query_params(grid.ra0, grid.dec0, catwise_radius)
    gaia, catwise = _recorded_rows(name)
    made = catalogs.overlays_for_manifest(
        manifest, gaia_query=lambda *_: (gaia, "recorded"), catwise_query=lambda *_: (catwise, "recorded")
    )
    assert made.model_dump_json().encode() == body_of(file_bytes(name, "overlays"))


@pytest.mark.parametrize("name", NAMES)
def test_overlay_positions_follow_the_astrometry_the_answer_carries(name):
    """From the answer alone: a Gaia source has a track exactly when it moves faster than 50 mas/yr, one point per
    visit where astrometric_positions puts its catalogue astrometry; every Gaia source is on the grid at a visit;
    a CatWISE source without a track is drawn at its catalogue position, on the grid."""
    manifest = manifest_of(name)
    answer = answer_of(name, "overlays")
    assert answer.upstreams.gaia == "ok" and answer.upstreams.catwise == "ok"
    grid = catalogs.field_grid(manifest)
    ids = [b.id for b in manifest.time_bins]
    gaia = answer.gaia
    ra, dec = catalogs.astrometric_positions(
        [s.ra for s in gaia],
        [s.dec for s in gaia],
        [s.pmra for s in gaia],
        [s.pmdec for s in gaia],
        [s.parallax for s in gaia],
        [None] * len(gaia),  # the answer carries no radial velocity
        Time(catalogs.GAIA_EPOCH, format="jyear", scale="tcb"),
        _times(manifest),
    )
    assert _on_grid(grid, *sky_to_pixel(grid, ra, dec)).any(axis=1).all()
    for k, source in enumerate(gaia):
        assert source.epoch == catalogs.GAIA_EPOCH
        moves = None not in (source.pmra, source.pmdec)
        fast = moves and math.hypot(source.pmra, source.pmdec) > catalogs.FAST_MAS_YR
        assert (source.track is not None) == fast, source.source_id
        if source.track:
            assert [point.time_bin for point in source.track] == ids
            apart = _apart_arcsec([p.ra for p in source.track], [p.dec for p in source.track], ra[k], dec[k])
            # measured: at most 0.34 mas (positions are rounded to 1e-7 degree), except Barnard's Star, 59.6 to
            # 73.1 mas: its radial velocity (-110.47 km/s in Gaia DR3) is applied to its track, and the answer
            # does not carry it
            assert max(apart) < (0.1 if source.source_id == BARNARD_GAIA else 0.001), source.source_id
    epoch = round(catalogs.catwise_epoch_jyear(), 4)
    for source in answer.catwise:
        assert source.epoch == epoch
        if not source.track:
            assert _on_grid(grid, *sky_to_pixel(grid, source.ra, source.dec)), source.id
    assert len({s.source_id for s in gaia}) == len(gaia) and len({s.id for s in answer.catwise}) == len(
        answer.catwise
    )
    assert gaia == sorted(gaia, key=lambda s: (s.g is None, s.g or 0.0, s.source_id))  # brightest first
    assert answer.catwise == sorted(answer.catwise, key=lambda s: (s.w2 is None, s.w2 or 0.0, s.id))


@pytest.mark.parametrize("name", NAMES)
def test_fixture_stars_are_in_the_gaia_list_at_their_recorded_pixels(name):
    """Contract section 8: each fixture star maps to its recorded pixel within 0.5 px. Moved to epoch_ref by
    proper motion, as make_fixture placed them, the Gaia list's entries land within 0.0007 px of them (measured
    0.0002 to 0.0006); where the page draws them (their 2016.0 catalogue position: none has a track), within
    0.12 px (measured 0.019 to 0.12: ten years of proper motion)."""
    manifest = manifest_of(name)
    grid = catalogs.field_grid(manifest)
    by_id = {source.source_id: source for source in answer_of(name, "overlays").gaia}
    for star in manifest.fixture_stars:
        source = by_id[star.source_id]
        assert source.track is None
        ra, dec = make_fixture.propagate(
            source.ra, source.dec, source.pmra, source.pmdec, source.epoch, manifest.epoch_ref
        )
        x, y = sky_to_pixel(grid, ra, dec)
        assert math.hypot(x - star.x, y - star.y) < 0.001
        x, y = sky_to_pixel(grid, source.ra, source.dec)
        assert math.hypot(x - star.x, y - star.y) < 0.5


def test_wise0855_has_one_tracked_catwise_source_and_its_track_passes_the_centre():
    """The centre of the field is WISE 0855 at epoch_ref (2026.0). Its one tracked CatWISE entry follows the
    published astrometry (catalogs.published_positions; measured 0.11 to 0.23 mas apart), and in grid pixels the
    track runs east to west through the centre: 1.56, 0.49, 0.21 and 1.07 px from it at the visits of 2025-05,
    2025-11, 2025-12 and 2026-04/05 (the object moves 2.65 px a year), and its path between the visits passes
    0.024 px from it (measured)."""
    manifest = manifest_of("wise0855")
    grid = catalogs.field_grid(manifest)
    tracked = [source for source in answer_of("wise0855", "overlays").catwise if source.track]
    assert [source.id for source in tracked] == [WISE0855_CATWISE]
    track = tracked[0].track
    assert [point.time_bin for point in track] == [b.id for b in manifest.time_bins]
    published = catalogs.published_positions(TARGETS["wise0855"], _times(manifest))
    assert max(_apart_arcsec([p.ra for p in track], [p.dec for p in track], *published)) < 0.001
    x, y = (np.asarray(v) for v in sky_to_pixel(grid, [p.ra for p in track], [p.dec for p in track]))
    assert float(np.hypot(x - grid.cx, y - grid.cy).min()) < 0.5
    closest = math.inf
    for (x0, y0), (x1, y1) in zip(zip(x[:-1], y[:-1]), zip(x[1:], y[1:]), strict=True):
        step = np.array([x1 - x0, y1 - y0])
        t = min(1.0, max(0.0, float(np.dot([grid.cx - x0, grid.cy - y0], step) / np.dot(step, step))))
        closest = min(closest, math.hypot(x0 + t * step[0] - grid.cx, y0 + t * step[1] - grid.cy))
    assert closest < 0.1
    assert x[0] < grid.cx < x[-1] and all(np.diff(x) > 0.0)  # east of the centre before 2026.0, west after


def test_barnard_field_has_no_catwise_track_because_of_barnards_star():
    """catwise_tracks moves no CatWISE marker in a field whose Gaia answer holds a star brighter than G = 10:
    around Barnard's Star (G = 8.19) spurious CatWISE motions reach the field's edge (catalogs.py)."""
    answer = answer_of("barnard", "overlays")
    bright = [s.source_id for s in answer.gaia if s.g is not None and s.g < catalogs.CATWISE_BRIGHT_G]
    assert bright == [BARNARD_GAIA]
    assert not any(source.track for source in answer.catwise)


# ----------------------------------------------------------------------------------------------- spectra
@pytest.mark.parametrize("name", NAMES)
def test_spectrum_was_measured_for_what_the_recorded_overlays_say_at_the_request_position(name):
    """spectrum.choose, offline on the recorded overlays, snaps the request position to the same source, with
    the same astrometry, as the recorded spectrum; its target position is that source at epoch_ref; its
    neighbours are among the candidates choose passes (the photometry keeps those within 15")."""
    manifest = manifest_of(name)
    answer = answer_of(name, "spectrum")
    choice = spectra.choose(answer_of(name, "overlays"), manifest, manifest.request.ra, manifest.request.dec)
    assert answer.target.snapped_to == choice.snapped_to
    target = choice.target
    astrometry = (answer.target.pmra, answer.target.pmdec, answer.target.parallax, answer.target.epoch)
    assert astrometry == (target.pmra, target.pmdec, target.parallax, target.epoch)
    ra, dec = target.position_at_year(manifest.epoch_ref)
    assert (answer.target.ra, answer.target.dec) == (round(ra, 7), round(dec, 7))
    candidates = {(n.catalog, n.id) for n in choice.neighbours}
    assert {(n.catalog, n.id) for n in answer.neighbours} <= candidates


def test_wise0855_spectrum_detects_the_dwarf_at_4_4_to_4_8_micron_and_nothing_below_3_8_micron():
    answer = answer_of("wise0855", "spectrum")
    target = TARGETS["wise0855"]
    assert answer.state == "ok" and answer.method.kind == "joint_psf"
    snapped = answer.target.snapped_to
    assert (snapped.catalog, snapped.id) == ("simbad", target.label) and snapped.sep_arcsec < 1.0  # 0.31
    assert (answer.target.pmra, answer.target.pmdec, answer.target.epoch) == (
        target.pmra,
        target.pmdec,
        target.epoch,
    )
    assert {(n.catalog, n.id, n.fitted) for n in answer.neighbours} == {
        ("catwise", NEIGHBOUR, True),
        ("catwise", "J085502.09-071434.5", True),
    }
    # binned values are made of "good" points only. Measured: six at 4.4-4.8 micron, in the visits 1 to 3, at
    # 3.46 to 6.39 times their errors; together 573.0 +- 47.6 microjansky, 12.0 sigma
    cold = [b for b in answer.binned if 4.4 <= b.lam <= 4.8]
    assert len(cold) >= 4 and all(b.flux_ujy > 3.0 * b.err_ujy for b in cold)
    weights = np.array([1.0 / b.err_ujy**2 for b in cold])
    flux = float((weights * [b.flux_ujy for b in cold]).sum() / weights.sum())
    assert flux > 10.0 * float(weights.sum() ** -0.5)
    # measured: 44 binned values below 3.8 micron, the largest at 2.48 times its error, flux/error rms 0.92.
    # Together they read -17.6 +- 5.5 microjansky: the blank-sky offset of ENGINE_NOTES known limit 17, not light
    blue = [b.flux_ujy / b.err_ujy for b in answer.binned if b.lam < 3.8]
    assert len(blue) >= 40 and max(abs(z) for z in blue) < 3.0
    assert math.sqrt(sum(z * z for z in blue) / len(blue)) < 1.5


def test_wise0855_points_and_binned_values_agree():
    """The points lie in the manifest's visits, sorted as photometry.py sorts them, and span time_span; each
    binned value is the inverse-variance mean of its visit's "good" points in one wave bin (contract 7.1 and
    section 4), recomputed here from the points: measured within 0.0102 microjansky and 0.000014 micron (the
    points are rounded to 0.01 microjansky and 1e-5 micron), and its error at least the statistical, 3 % and
    background terms (measured: 0.004 below them at worst, rounding)."""
    manifest = manifest_of("wise0855")
    answer = answer_of("wise0855", "spectrum")
    visits = {b.id: b for b in manifest.time_bins}
    for point in answer.points:
        assert visits[point.time_bin].mjd_start <= point.mjd <= visits[point.time_bin].mjd_end
    order = [(p.time_bin, p.lam, p.mjd) for p in answer.points]
    assert order == sorted(order)
    times = [p.mjd for p in answer.points]
    assert (answer.time_span.mjd_min, answer.time_span.mjd_max) == (min(times), max(times))
    groups = defaultdict(list)
    for point in answer.points:
        if point.quality == "good":
            groups[(point.time_bin, presets.wave_bin_for(point.det, point.lam))].append(point)
    edges = {w.id: w for w in presets.wave_bins()}
    assert len(answer.binned) == len(groups)
    for (time_bin, wave_bin), value in zip(sorted(groups), answer.binned, strict=True):
        members, edge = groups[(time_bin, wave_bin)], edges[wave_bin]
        assert (value.time_bin, value.n) == (time_bin, len(members))
        assert value.lam_min == min(edge.lam_min, min(p.lam for p in members))
        assert value.lam_max == max(edge.lam_max, max(p.lam for p in members))
        assert value.lam_min <= value.lam <= value.lam_max
        statistical = [
            math.sqrt(p.err_ujy**2 - (photometry.SYSTEMATIC_FLOOR * p.flux_ujy) ** 2) for p in members
        ]
        weights = np.array([1.0 / s**2 for s in statistical])
        flux = float((weights * [p.flux_ujy for p in members]).sum() / weights.sum())
        lam = float((weights * [p.lam for p in members]).sum() / weights.sum())
        assert abs(flux - value.flux_ujy) < 0.05 and abs(lam - value.lam) < 1e-4
        least = math.sqrt(
            1.0 / weights.sum()
            + (photometry.SYSTEMATIC_FLOOR * flux) ** 2
            + photometry.BACKGROUND_FLOOR_UJY[edge.detector] ** 2
        )
        assert value.err_ujy > least - 0.01


def test_barnard_spectrum_is_saturated_with_no_points_and_no_time_span():
    answer = answer_of("barnard", "spectrum")
    star = TARGETS["barnard"]
    assert answer.state == "saturated" and answer.points == [] and answer.binned == []
    assert answer.time_span is None
    snapped = answer.target.snapped_to
    assert (snapped.catalog, snapped.id) == ("gaia", BARNARD_GAIA)
    assert (answer.target.pmra, answer.target.pmdec, answer.target.parallax) == (
        star.pmra,
        star.pmdec,
        star.parallax,
    )


# ------------------------------------------------------------------------------- the tool (no network)
@pytest.fixture
def archive(monkeypatch) -> Archive:
    fake = Archive()
    monkeypatch.setattr(photometry.remote_fits, "read_windows", fake.read_windows)
    return fake


def _stand_ins(archive: Archive, catalogues: Catalogues | None = None, measure=None) -> dict:
    """create_app options that answer from recorded real data (tests/test_overlays_spectrum_api.py)."""
    return {
        "overlays": (catalogues or Catalogues()).overlays,
        "measure": measure or functools.partial(photometry.measure_with_stats, psf=_library()),
        "discover": archive.discover,
    }


def test_the_tool_writes_what_the_routes_serve(tmp_path, archive):
    out = tmp_path / "out"
    outcomes = record_answers.record(
        "wise0855",
        fixtures_dir=FIXTURES_DIR,
        out_dir=out,
        cache_dir=tmp_path / "cache",
        **_stand_ins(archive),
    )
    assert [(o.route, o.status, o.refused) for o in outcomes] == [
        ("overlays", 200, ""),
        ("spectrum", 200, ""),
    ]
    assert [o.path for o in outcomes] == [
        out / "wise0855" / "overlays.json",
        out / "wise0855" / "spectrum.json",
    ]
    client = make_client(tmp_path, archive=archive, cache=FieldCache(tmp_path / "other", max_mb=50))
    key = manifest_of("wise0855").key
    for outcome in outcomes:
        data = outcome.path.read_bytes()
        assert layout_problems("wise0855", outcome.route, data) == []
        request = json.loads(data)["request"]
        served = client.get(
            f"/api/fields/{key}/{outcome.route}", params=request, headers={"Accept-Encoding": "identity"}
        )
        assert served.status_code == 200 and body_of(data) == served.content
    # the recorded catalogue rows make the live answer: the overlays response is the committed one
    assert body_of((out / "wise0855" / "overlays.json").read_bytes()) == body_of(
        file_bytes("wise0855", "overlays")
    )
    assert sorted(p.name for p in (out / "wise0855").iterdir()) == ["overlays.json", "spectrum.json"]


def test_the_tool_refuses_answers_that_are_not_final_and_leaves_the_files_as_they_were(tmp_path, archive):
    out = tmp_path / "out"
    kept = out / "wise0855" / "spectrum.json"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"what was there\n")
    catalogues = Catalogues()
    catalogues.down = {"catwise"}
    outcomes = record_answers.record(
        "wise0855",
        fixtures_dir=FIXTURES_DIR,
        out_dir=out,
        cache_dir=tmp_path / "cache",
        **_stand_ins(archive, catalogues),
    )
    assert [(o.route, o.status, o.path) for o in outcomes] == [
        ("overlays", 200, None),
        ("spectrum", 503, None),
    ]
    assert outcomes[0].refused == "not final: Gaia ok, CatWISE unavailable"
    assert outcomes[1].refused.startswith("HTTP 503") and "upstream_unavailable" in outcomes[1].refused
    assert sorted(p.name for p in kept.parent.iterdir()) == ["spectrum.json"]
    assert kept.read_bytes() == b"what was there\n"


def test_the_tool_refuses_an_incomplete_spectrum(tmp_path, archive):
    calls = []

    def synthetic_measure(exposures, ra, dec, **kwargs):
        calls.append(len(exposures))
        return _synthetic_answer(), _synthetic_stats(read=7, timed_out=3)

    out = tmp_path / "out"
    outcomes = record_answers.record(
        "wise0855",
        fixtures_dir=FIXTURES_DIR,
        out_dir=out,
        cache_dir=tmp_path / "cache",
        routes=("spectrum",),
        **_stand_ins(archive, measure=synthetic_measure),
    )
    [outcome] = outcomes
    assert len(calls) == 1 and outcome.status == 200 and outcome.path is None
    assert outcome.refused == "incomplete: 3 of 10 exposures not measured; not cached"
    assert not out.exists()


def test_what_the_tool_calls_final():
    overlays = answer_of("wise0855", "overlays")
    body = overlays.model_dump_json().encode()
    assert record_answers.refusal("overlays", 200, {}, body) == ""
    assert record_answers.refusal("overlays", 404, {}, b'{"code":"not_found"}').startswith("HTTP 404")
    assert record_answers.refusal("overlays", 200, {}, b"{}").startswith("not a contract answer")
    stale = overlays.model_copy(update={"upstreams": overlays.upstreams.model_copy(update={"gaia": "stale"})})
    assert record_answers.refusal("overlays", 200, {}, stale.model_dump_json().encode()).startswith(
        "not final"
    )
    pretty = json.dumps(json.loads(body), indent=1).encode()
    assert record_answers.refusal("overlays", 200, {}, pretty).startswith("the body is not")
    spectrum = answer_of("barnard", "spectrum").model_dump_json().encode()
    assert record_answers.refusal("spectrum", 200, {"content-type": "application/json"}, spectrum) == ""
    header = {INCOMPLETE_HEADER.lower(): "1 of 364 exposures not measured; not cached"}
    assert record_answers.refusal("spectrum", 200, header, spectrum).startswith("incomplete")


def _synthetic_field_copy(tmp_path: Path, pipeline_version: str) -> Path:
    """A copy of the recorded WISE 0855 field whose manifest names another pipeline version (synthetic)."""
    folder = tmp_path / "fixtures" / "wise0855"
    folder.mkdir(parents=True)
    shutil.copyfile(FIXTURES_DIR / "wise0855" / "frames.bin", folder / "frames.bin")
    synthetic_manifest = json.loads((FIXTURES_DIR / "wise0855" / "manifest.json").read_text(encoding="utf-8"))
    synthetic_manifest["provenance"]["pipeline_version"] = pipeline_version
    (folder / "manifest.json").write_text(json.dumps(synthetic_manifest), encoding="utf-8")
    return folder.parent


def test_the_tool_records_nothing_for_another_pipeline_version_or_a_missing_field(tmp_path):
    fixtures = _synthetic_field_copy(tmp_path, "0.0.0")
    with pytest.raises(record_answers.RecordError, match="pipeline 0.0.0"):
        record_answers.record(
            "wise0855", fixtures_dir=fixtures, out_dir=fixtures, cache_dir=tmp_path / "cache"
        )
    with pytest.raises(record_answers.RecordError, match="does not hold a recorded field"):
        record_answers.record(
            "barnard", fixtures_dir=fixtures, out_dir=fixtures, cache_dir=tmp_path / "cache"
        )
    # the command line, in a process of its own (it sends the service's log lines to standard error)
    command = [sys.executable, "-m", "tombaugh.tools.record_answers", "wise0855", "--fixtures", str(fixtures)]
    run = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    assert run.returncode == 1 and run.stdout == "" and "record the field again" in run.stderr
    assert sorted(p.name for p in (fixtures / "wise0855").iterdir()) == ["frames.bin", "manifest.json"]
    with pytest.raises(SystemExit):  # a field is named from a fixed list, never by a path or an address
        record_answers.main(["https://example.org/field"])


def test_the_envelope_is_compact_with_one_trailing_newline():
    manifest = manifest_of("barnard")
    body = answer_of("barnard", "spectrum").model_dump_json().encode()
    stamp = json.loads(file_bytes("barnard", "spectrum"))["recorded_at"]
    data = record_answers.envelope("spectrum", "barnard", manifest, stamp, body)
    assert data == file_bytes("barnard", "spectrum")
    assert data.endswith(b"}}\n") and b" " not in data.split(JOIN)[0]
    assert record_answers.request_of("overlays", manifest) == {}
    assert record_answers.request_of("spectrum", manifest) == {"ra": 269.4463, "dec": 4.7682}
