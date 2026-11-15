"""The HTTP service (Contract v1.0, section 7) and the disk cache behind it.

No network: recorded fields come from ``cache/fixtures`` (real data), and where a build is needed the
pipeline is replaced by a stand-in that assembles a manifest from small synthetic planes.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from tombaugh import http, models
from tombaugh.build import AlreadyBuilt, BuildStats, assemble_manifest, field_key
from tombaugh.cache import MB, REQUEST_TTL_S, FieldCache, default_cache_dir, default_max_mb, request_id
from tombaugh.grid import Grid
from tombaugh.main import (
    Builder,
    Fixtures,
    RateLimiter,
    Settings,
    UpstreamProbes,
    create_app,
    default_fixtures_dir,
    parse_position,
)
from tombaugh.models import BuildingResponse, ErrorResponse, Manifest, StatusResponse
from tombaugh.stack import Registered
from tombaugh.types import Exposure, StackedPlane

REPO = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO / "cache" / "fixtures"
FIXTURE_NAMES = ("wise0855", "barnard")
ERROR_KEYS = {"contract", "status", "code", "message"}


def make_client(tmp_path, *, secret="", build=None, probes=None, burst=5.0, per_minute=3.0, cache=None):
    settings = Settings(
        cors_origins=("http://localhost:5173",),
        proxy_secret=secret,
        fixtures_dir=FIXTURES_DIR,
        rate_burst=burst,
        rate_per_minute=per_minute,
        probe_upstreams=False,
    )
    cache = cache or FieldCache(tmp_path / "cache", max_mb=50)
    kwargs = {} if build is None else {"build": build}
    app = create_app(settings, cache=cache, probes=probes, **kwargs)
    return TestClient(app)


@pytest.fixture
def client(tmp_path):
    return make_client(tmp_path)


def assert_error(response, status: int, code: str) -> dict:
    """The response is an error in the contract shape; returns its body."""
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == ERROR_KEYS
    assert body["contract"] == "1.0" and body["status"] == "error" and body["code"] == code
    assert isinstance(body["message"], str) and body["message"]
    ErrorResponse.model_validate(body)
    return body


def raw_body(client: TestClient, url: str, headers: dict | None = None):
    """(response, body bytes exactly as sent): the test client would otherwise undo the gzip encoding."""
    with client.stream("GET", url, headers=headers) as response:
        return response, b"".join(response.iter_raw())


# ------------------------------------------------------------------------------------ health, fixtures
def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"contract": "1.0", "status": "ok"}


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_manifest_is_the_recorded_file_and_a_valid_manifest(client, name):
    response = client.get("/api/fields", params={"fixture": name})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body == json.loads((FIXTURES_DIR / name / "manifest.json").read_text(encoding="utf-8"))
    manifest = Manifest.model_validate(body)
    assert manifest.contract == "1.0" and manifest.status == "ready"
    assert manifest.frames is not None
    assert manifest.frames.url == f"/api/fields/{manifest.key}/frames.bin?v={manifest.frames.sha256[:16]}"
    assert manifest.fixture_stars is not None and len(manifest.fixture_stars) == 3
    assert len(manifest.planes) > 0 and len(manifest.wave_bins) == 24
    assert json.loads(manifest.model_dump_json()) == body  # the models neither add nor drop a key


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_frames_by_name_and_by_key(client, name):
    manifest = client.get("/api/fields", params={"fixture": name}).json()
    frames = manifest["frames"]
    recorded = (FIXTURES_DIR / name / "frames.bin").read_bytes()
    for url in (f"/api/fields/{name}/frames.bin", frames["url"]):
        response, raw = raw_body(client, url)
        assert response.status_code == 200
        assert response.headers["content-encoding"] == "gzip"
        assert response.headers["content-type"] == "application/octet-stream"
        assert raw[:2] == b"\x1f\x8b"  # gzip magic
        assert int(response.headers["content-length"]) == len(raw) < frames["nbytes"]
        unpacked = gzip.decompress(raw)
        assert len(unpacked) == frames["nbytes"]
        assert hashlib.sha256(unpacked).hexdigest() == frames["sha256"]
        assert unpacked == recorded
        assert client.get(url).content == recorded  # an HTTP client that honours the encoding gets the file
    by_key = client.get(frames["url"])
    assert by_key.headers["cache-control"] == "public, max-age=31536000, immutable"
    by_name = client.get(f"/api/fields/{name}/frames.bin")
    assert "immutable" not in by_name.headers["cache-control"]  # a name can be recorded again; a key cannot


def _other_build_under_the_key_of(name: str) -> tuple[dict, bytes, bytes]:
    """(recorded manifest, manifest JSON, frame bytes) of another build that has the recorded field's key.

    The planes are the recorded ones with the first pixel changed: what a pipeline change without a version
    bump, or a reprocessed archive file, leaves in the disk cache under the same content key.
    """
    recorded = json.loads((FIXTURES_DIR / name / "manifest.json").read_text(encoding="utf-8"))
    other = bytearray((FIXTURES_DIR / name / "frames.bin").read_bytes())
    other[0] ^= 0x01
    digest = hashlib.sha256(other).hexdigest()
    rebuilt = json.loads(json.dumps(recorded))
    rebuilt["frames"]["sha256"] = digest
    rebuilt["frames"]["url"] = f"/api/fields/{recorded['key']}/frames.bin?v={digest[:16]}"
    return recorded, json.dumps(rebuilt).encode("utf-8"), bytes(other)


def test_a_manifest_is_never_paired_with_the_frames_of_another_build(tmp_path):
    """Regression: with another build stored under a recorded field's key, `?fixture=` answered the
    recorded manifest and its frame URL answered the other build's bytes, both as immutable."""
    recorded, rebuilt_json, rebuilt_frames = _other_build_under_the_key_of("wise0855")
    key = recorded["key"]
    cache = FieldCache(tmp_path / "cache", max_mb=50)
    cache.put(key, rebuilt_json, rebuilt_frames)
    client = make_client(tmp_path, cache=cache)

    manifest = client.get("/api/fields", params={"fixture": "wise0855"}).json()
    assert manifest == recorded
    response = client.get(manifest["frames"]["url"])
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == manifest["frames"]["sha256"]
    assert response.content == (FIXTURES_DIR / "wise0855" / "frames.bin").read_bytes()
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"

    # the other build is served under its own URL, and only there
    rebuilt = json.loads(rebuilt_json)
    assert rebuilt["frames"]["url"] != manifest["frames"]["url"]
    other = client.get(rebuilt["frames"]["url"])
    assert other.status_code == 200 and other.content == rebuilt_frames
    assert other.headers["cache-control"] == "public, max-age=31536000, immutable"

    # a version that names no copy held here is not answered with some other bytes
    for wrong in ("0" * 16, "", manifest["frames"]["sha256"][:15], manifest["frames"]["sha256"]):
        assert_error(client.get(f"/api/fields/{key}/frames.bin", params={"v": wrong}), 404, "not_found")
    # without a version the first copy is served, as before
    assert client.get(f"/api/fields/{key}/frames.bin").status_code == 200


def test_frame_version_of_a_built_field_is_checked_too(tmp_path):
    client = make_client(tmp_path, build=StandInBuild())
    final, _ = poll(client, URL)
    manifest = Manifest.model_validate(final.json())
    path, version = manifest.frames.url.split("?v=")
    assert path == f"/api/fields/{manifest.key}/frames.bin" and version == manifest.frames.sha256[:16]
    assert hashlib.sha256(client.get(manifest.frames.url).content).hexdigest() == manifest.frames.sha256
    assert_error(client.get(path, params={"v": "f" * 16}), 404, "not_found")
    assert client.get(path).status_code == 200


def test_frames_length_matches_the_planes(client):
    for name in FIXTURE_NAMES:
        manifest = client.get("/api/fields", params={"fixture": name}).json()
        grid = manifest["grid"]
        assert manifest["frames"]["nbytes"] == len(manifest["planes"]) * grid["nx"] * grid["ny"] * 2
        for index, plane in enumerate(manifest["planes"]):
            assert plane["index"] == index and plane["offset"] == index * grid["nx"] * grid["ny"] * 2


# ---------------------------------------------------------------------------------------------- errors
@pytest.mark.parametrize(
    "query",
    [
        {"ra": "76.9563", "dec": "30.4012", "fov": "7"},
        {"ra": "76.9563", "dec": "30.4012", "fov": "6.5"},
        {"ra": "76.9563", "dec": "30.4012", "fov": "six"},
        {"ra": "76.9563", "dec": "30.4012", "fov": "0"},
        {"ra": "76.9563", "dec": "30.4012", "fov": "-6"},
        {"ra": "76.9563", "dec": "30.4012", "fov": "nan"},
        {"dec": "30.4012"},
        {"ra": "76.9563"},
        {},
        {"ra": "", "dec": "30.4012"},
        {"ra": "abc", "dec": "30.4012"},
        {"ra": "-0.001", "dec": "30.4012"},
        {"ra": "360.001", "dec": "30.4012"},
        {"ra": "76.9563", "dec": "90.001"},
        {"ra": "76.9563", "dec": "-91"},
        {"ra": "nan", "dec": "30.4012"},
        {"ra": "inf", "dec": "30.4012"},
        {"ra": "76.9563", "dec": "-inf"},
        {"ra": "1e999", "dec": "0"},
    ],
)
def test_bad_requests_answer_400_in_the_contract_shape(tmp_path, query):
    calls = []
    client = make_client(tmp_path, build=lambda *a, **k: calls.append(a))
    assert_error(client.get("/api/fields", params=query), 400, "bad_request")
    assert calls == []  # nothing was built for a bad request


def test_parse_position_limits_and_default_field_of_view():
    assert parse_position({"ra": "0", "dec": "-90"}) == (0.0, -90.0, 6)
    assert parse_position({"ra": "360", "dec": "90", "fov": "10"}) == (360.0, 90.0, 10)
    assert parse_position({"ra": " 76.9563 ", "dec": "30.4012", "fov": "3.0"}) == (76.9563, 30.4012, 3)
    for fov in ("3", "4", "5", "6", "8", "10"):
        assert parse_position({"ra": "1", "dec": "1", "fov": fov})[2] == int(fov)


def test_unknown_fixture_and_unknown_key_answer_404(client):
    assert_error(client.get("/api/fields", params={"fixture": "nosuchfield"}), 404, "not_found")
    assert_error(client.get("/api/fields/0123456789abcdef/frames.bin"), 404, "not_found")
    assert_error(client.get("/api/fields/nosuchfield/frames.bin"), 404, "not_found")
    assert_error(client.get("/api/nothing/here"), 404, "not_found")
    assert_error(client.get("/nothing"), 404, "not_found")


def test_endpoints_not_built_yet_say_so(client):
    body = assert_error(client.get("/api/resolve?q=M31"), 404, "not_found")
    assert "not built yet" in body["message"]


@pytest.mark.parametrize(
    "name",
    [
        "../wise0855",
        "wise0855/..",
        "wise0855/",
        "/wise0855",
        "..",
        ".",
        "wise.0855",
        "wise0855.json",
        "wise0855/manifest.json",
        "WISE0855",
        "wise-0855",
        "wise0855\n",
        "wise 0855",
        "",
        "%2e%2e",
        "..%2fwise0855",
        "a" * 65,
    ],
)
def test_fixture_names_with_slashes_dots_or_other_characters_are_refused(client, name):
    assert_error(client.get("/api/fields", params={"fixture": name}), 404, "not_found")


@pytest.mark.parametrize(
    "key",
    [
        "..",
        ".",
        "%2e%2e",
        "wise0855.bak",
        "wise.0855",
        "0123456789abcde.",
        "0123456789ABCDEF",
        "0123456789abcde",  # 15 characters
        "0123456789abcdef0",  # 17 characters: not a key, and no fixture of that name
        "0123456789abcdeg",
        "wise0855%0a",
        "wise0855%00",
        "a%2Fb",
        "..%2f..%2fmanifest.json",
        "%2e%2e%2fwise0855",
    ],
)
def test_keys_with_slashes_dots_or_a_wrong_shape_are_refused(client, key):
    assert_error(client.get(f"/api/fields/{key}/frames.bin"), 404, "not_found")


def test_a_path_that_climbs_out_of_the_fixtures_folder_serves_nothing(tmp_path):
    root = tmp_path / "fixtures"
    (root / "inside").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    for folder in (root / "inside", tmp_path / "outside"):
        (folder / "manifest.json").write_text('{"key": "0123456789abcdef"}', encoding="utf-8")
        (folder / "frames.bin").write_bytes(b"\x00\x00")
    fixtures = Fixtures(root)
    assert fixtures.names() == ["inside"]
    assert fixtures.get("inside") is not None
    for name in ("../outside", "inside/../../outside", "..", "", "outside"):
        assert fixtures.get(name) is None
    assert fixtures.by_key("0123456789abcdef") is fixtures.get("inside")
    assert fixtures.by_key("fedcba9876543210") is None


# -------------------------------------------------------------------------------------- proxy secret
def test_proxy_secret_is_enforced_on_api_paths_only(tmp_path):
    client = make_client(tmp_path, secret="s3cret-value")
    good = {"x-tombaugh-proxy-secret": "s3cret-value"}
    for url in ("/api/fields?fixture=wise0855", "/api/status", "/api/fields/wise0855/frames.bin", "/api/x"):
        assert_error(client.get(url), 403, "bad_request")
        assert_error(client.get(url, headers={"x-tombaugh-proxy-secret": "wrong"}), 403, "bad_request")
        assert_error(client.get(url, headers={"x-tombaugh-proxy-secret": ""}), 403, "bad_request")
        assert_error(
            client.get(url, headers={"x-tombaugh-proxy-secret": "s3cret-value "}), 403, "bad_request"
        )
    assert client.get("/api/fields?fixture=wise0855", headers=good).status_code == 200
    assert client.get("/api/status", headers=good).status_code == 200
    assert client.get("/api/fields/wise0855/frames.bin", headers=good).status_code == 200
    assert client.get("/healthz").status_code == 200  # exempt: the host's health check has no secret
    assert "s3cret-value" not in client.get("/api/status").text


def test_without_a_configured_secret_no_header_is_needed(client):
    assert client.get("/api/fields?fixture=wise0855").status_code == 200
    assert (
        client.get("/api/fields?fixture=wise0855", headers={"x-tombaugh-proxy-secret": "x"}).status_code
        == 200
    )


def test_cors_allows_only_the_configured_origins(client):
    allowed = client.get("/api/fields?fixture=wise0855", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    other = client.get("/api/fields?fixture=wise0855", headers={"Origin": "http://example.org"})
    assert "access-control-allow-origin" not in other.headers
    refused = client.get("/api/fields?fov=7&ra=1&dec=1", headers={"Origin": "http://localhost:5173"})
    assert (
        refused.status_code == 400
        and refused.headers["access-control-allow-origin"] == "http://localhost:5173"
    )


def test_settings_from_the_environment(monkeypatch):
    for name in (
        "TOMBAUGH_CORS_ORIGINS",
        "TOMBAUGH_PROXY_SECRET",
        "TOMBAUGH_FIXTURES_DIR",
        "TOMBAUGH_RATE_BURST",
    ):
        monkeypatch.delenv(name, raising=False)
    plain = Settings.from_env()
    assert plain.cors_origins == ("http://localhost:5173",) and plain.proxy_secret == ""
    assert plain.fixtures_dir == default_fixtures_dir() == FIXTURES_DIR
    monkeypatch.setenv("TOMBAUGH_CORS_ORIGINS", "https://a.example, https://b.example/ ,")
    monkeypatch.setenv("TOMBAUGH_PROXY_SECRET", " abc ")
    monkeypatch.setenv("TOMBAUGH_RATE_BURST", "9")
    monkeypatch.setenv("TOMBAUGH_PROBE_UPSTREAMS", "0")
    changed = Settings.from_env()
    assert changed.cors_origins == ("https://a.example", "https://b.example")
    assert changed.proxy_secret == "abc" and changed.rate_burst == 9.0 and changed.probe_upstreams is False


# ------------------------------------------------------------------------------------------------ status
def test_status_has_the_contract_shape_and_never_probes_when_told_not_to(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    status = StatusResponse.model_validate(body)
    assert set(body) == {
        "contract",
        "status",
        "pipeline_version",
        "newest_exposure",
        "upstreams",
        "cache",
        "builds",
    }
    assert status.status == "ok" and status.pipeline_version == "0.3.0"
    assert set(body["upstreams"]) == {"irsa_sia", "s3"}
    assert body["upstreams"]["s3"] == {"ok": False, "latency_ms": None, "checked_at": None}
    assert body["builds"] == {"active": 0, "queued": 0}
    assert body["cache"]["used_mb"] == 0 and 0 < body["cache"]["free_mb"] <= 50
    newest = max(
        json.loads((FIXTURES_DIR / name / "manifest.json").read_text())["exposures"]["newest_mjd"]
        for name in FIXTURE_NAMES
    )
    assert body["newest_exposure"]["mjd"] == newest and len(body["newest_exposure"]["date"]) == 10


def test_status_reports_probe_results_without_waiting_for_them(tmp_path):
    release = threading.Event()
    done = threading.Event()

    def slow_ok():
        release.wait(5)

    def broken():
        try:
            raise http.UpstreamError("gave up")
        finally:
            done.set()

    probes = UpstreamProbes({"irsa_sia": slow_ok, "s3": broken}, max_age_s=300.0)
    client = make_client(tmp_path, probes=probes)
    started = time.monotonic()
    first = client.get("/api/status").json()
    assert time.monotonic() - started < 2.0  # the probe is still waiting: the request did not
    assert first["upstreams"]["irsa_sia"] == {"ok": False, "latency_ms": None, "checked_at": None}
    release.set()
    assert done.wait(5)
    for _ in range(100):
        body = client.get("/api/status").json()
        if body["upstreams"]["s3"]["checked_at"] is not None:
            break
        time.sleep(0.02)
    assert body["upstreams"]["irsa_sia"]["ok"] is True and body["upstreams"]["irsa_sia"]["latency_ms"] >= 0
    assert body["upstreams"]["s3"]["ok"] is False and body["upstreams"]["s3"]["checked_at"].endswith("Z")


def test_probe_results_are_kept_for_five_minutes(tmp_path):
    rounds = []
    probes = UpstreamProbes({"irsa_sia": lambda: rounds.append(1)}, max_age_s=300.0)
    for _ in range(50):
        if probes.snapshot()["irsa_sia"].checked_at is not None:
            break
        time.sleep(0.02)
    for _ in range(5):
        probes.snapshot()
    assert rounds == [1]


# ------------------------------------------------------------------------------- builds (stand-in)
def synthetic_build_result(ra: float, dec: float, fov: int, n_exposures: int = 3):
    """A valid manifest and frame bytes from two small synthetic planes."""
    grid = Grid.for_field(ra, dec, fov)
    synthetic_items, synthetic_planes = [], []
    for time_bin in (0, 1):
        synthetic_data = np.full(grid.shape, 0.5 + time_bin, dtype=np.float32)
        synthetic_data[grid.cy, grid.cx] = 3.0
        synthetic_data[0, :] = np.nan
        mjd = 60800.5 + 100.0 * time_bin
        synthetic_planes.append(
            StackedPlane(time_bin, 20, synthetic_data, n_exposures, 0.01, 4.49, mjd + 1.0, mjd, mjd + 2.0)
        )
        for i in range(n_exposures):
            exposure = Exposure(
                f"S{time_bin}_{i:04d}", 6, mjd + i, "spherex_dr1", "nasa-irsa-spherex", "us-east-1", "k"
            )
            synthetic_items.append(Registered(exposure, synthetic_data, 1.0, 4.49, mjd + i, time_bin, 20))
    manifest, frames = assemble_manifest(
        ra, dec, fov, grid, synthetic_planes, synthetic_items, found=2 * n_exposures
    )
    stats = BuildStats(
        key=manifest.key, status=manifest.status, found=2 * n_exposures, newest_found_mjd=60902.5
    )
    return manifest, frames, stats


class StandInBuild:
    """Replaces the pipeline: waits until released, then returns synthetic planes or raises `error`."""

    def __init__(self, error: Exception | None = None, hold: bool = False):
        self.calls: list[tuple[float, float, int]] = []
        self.error = error
        self.release = threading.Event()
        if not hold:
            self.release.set()
        self.started = threading.Event()

    def __call__(self, ra, dec, fov, *, progress=None, deadline_s=120.0, known=None):
        self.calls.append((ra, dec, fov))
        self.started.set()
        progress("discover", 1, 1)
        progress("fetch", 3, 6)
        while not self.release.wait(0.01):
            progress("fetch", 3, 6)  # a real build reports as it goes; this is where it gets cancelled
        if self.error is not None:
            raise self.error
        return synthetic_build_result(ra, dec, fov)


def poll(client: TestClient, url: str, tries: int = 300):
    """Repeat a GET while it answers 202; returns (final response, the 202 bodies seen)."""
    seen = []
    for _ in range(tries):
        response = client.get(url)
        if response.status_code != 202:
            return response, seen
        seen.append(response.json())
        time.sleep(0.01)
    raise AssertionError("the build did not finish")


URL = "/api/fields?ra=76.95631&dec=30.40122&fov=4"


def test_cold_request_builds_then_serves_from_the_cache(tmp_path):
    build = StandInBuild(hold=True)
    client = make_client(tmp_path, build=build)
    first = client.get(URL)
    assert first.status_code == 202
    assert first.headers["retry-after"] == "1"
    building = BuildingResponse.model_validate(first.json())
    assert set(first.json()) == {"contract", "status", "progress", "retry_after_s"}
    assert building.status == "building" and building.retry_after_s == 1
    assert build.started.wait(5)
    for _ in range(200):
        progress = client.get(URL).json()["progress"]
        if progress == {"stage": "fetch", "done": 3, "total": 6}:
            break
        time.sleep(0.01)
    assert progress == {"stage": "fetch", "done": 3, "total": 6}
    assert client.get("/api/status").json()["builds"] == {"active": 1, "queued": 0}
    assert client.get("/healthz").status_code == 200  # answers while a build runs

    build.release.set()
    final, _ = poll(client, URL)
    assert final.status_code == 200
    manifest = Manifest.model_validate(final.json())
    assert manifest.status == "ready"
    assert manifest.request.model_dump() == {"ra": 76.95631, "dec": 30.40122, "fov_arcmin": 4}
    assert manifest.centre.model_dump() == {"ra": 76.9563, "dec": 30.4012}
    assert build.calls == [(76.95631, 30.40122, 4)]

    # the frame file of the new key: gzip on the wire, the manifest's bytes inside
    response, raw = raw_body(client, manifest.frames.url)
    assert response.headers["content-encoding"] == "gzip" and raw[:2] == b"\x1f\x8b"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    unpacked = gzip.decompress(raw)
    assert len(unpacked) == manifest.frames.nbytes
    assert hashlib.sha256(unpacked).hexdigest() == manifest.frames.sha256

    # a repeat, and a request that snaps to the same centre, are answered without another build
    again = client.get("/api/fields?ra=76.95634&dec=30.40118&fov=4")
    assert again.status_code == 200 and again.json()["key"] == manifest.key
    assert again.json()["request"] == {"ra": 76.95634, "dec": 30.40118, "fov_arcmin": 4}
    assert client.get(URL).status_code == 200
    assert build.calls == [(76.95631, 30.40122, 4)]
    assert client.get("/api/status").json()["builds"] == {"active": 0, "queued": 0}
    assert client.get("/api/status").json()["newest_exposure"]["mjd"] >= 60902.5
    # another field of view is another field
    assert client.get("/api/fields?ra=76.95631&dec=30.40122&fov=6").status_code == 202


def test_requests_for_the_same_snapped_position_join_one_build(tmp_path):
    build = StandInBuild(hold=True)
    client = make_client(tmp_path, build=build)
    assert client.get("/api/fields?ra=10.00001&dec=20&fov=3").status_code == 202
    assert client.get("/api/fields?ra=10.00002&dec=20.00001&fov=3").status_code == 202
    assert client.get("/api/fields?ra=10&dec=20&fov=3").status_code == 202
    build.release.set()
    final, _ = poll(client, "/api/fields?ra=10&dec=20&fov=3")
    assert final.status_code == 200 and len(build.calls) == 1


def test_an_uncovered_position_answers_200_empty(tmp_path):
    def empty_build(ra, dec, fov, *, progress=None, deadline_s=120.0, known=None):
        manifest, frames = assemble_manifest(ra, dec, fov, Grid.for_field(ra, dec, fov), [], [], found=0)
        return manifest, frames, BuildStats(key=manifest.key, status="empty")

    client = make_client(tmp_path, build=empty_build)
    final, _ = poll(client, "/api/fields?ra=1&dec=2")
    assert final.status_code == 200
    body = final.json()
    assert body["status"] == "empty" and body["planes"] == [] and body["frames"] is None
    assert body["request"] == {"ra": 1.0, "dec": 2.0, "fov_arcmin": 6}
    Manifest.model_validate(body)
    assert_error(client.get(f"/api/fields/{body['key']}/frames.bin"), 404, "not_found")


def test_archive_down_and_nothing_cached_answers_503_then_allows_a_retry(tmp_path, monkeypatch):
    build = StandInBuild(error=http.UpstreamError("gave up after 8 attempts"))
    client = make_client(tmp_path, build=build)
    final, _ = poll(client, URL)
    body = assert_error(final, 503, "upstream_unavailable")
    assert "attempts" not in body["message"]  # the upstream's own words stay in the log
    assert_error(client.get(URL), 503, "upstream_unavailable")  # the same failed build, not a new one
    assert len(build.calls) == 1
    monkeypatch.setattr("tombaugh.main.ERROR_TTL_S", 0.0)
    build.error = None
    service = client.app.state.service
    with service.builder._wake:
        for job in service.builder._jobs.values():
            job.expires = 0.0
    final, _ = poll(client, URL)
    assert final.status_code == 200 and len(build.calls) == 2


def test_an_unexpected_failure_answers_500_without_details(tmp_path):
    build = StandInBuild(error=RuntimeError("secret internal detail"))
    client = make_client(tmp_path, build=build)
    final, _ = poll(client, URL)
    body = assert_error(final, 500, "internal")
    assert "secret internal detail" not in body["message"]


def test_queue_holds_eight_waiting_builds_then_answers_429(tmp_path):
    build = StandInBuild(hold=True)
    client = make_client(tmp_path, build=build, burst=100.0)
    urls = [f"/api/fields?ra={10 + i}&dec=5&fov=3" for i in range(10)]
    assert client.get(urls[0]).status_code == 202
    assert build.started.wait(5)  # the first build is running; the next eight wait
    for url in urls[1:9]:
        assert client.get(url).status_code == 202
    assert client.get("/api/status").json()["builds"] == {"active": 1, "queued": 8}
    refused = client.get(urls[9])
    assert_error(refused, 429, "busy")
    assert int(refused.headers["retry-after"]) >= 1
    assert client.get(urls[3]).status_code == 202  # polling a queued build is not a new build
    assert client.get("/api/fields?fixture=wise0855").status_code == 200  # recorded fields never queue
    build.release.set()
    for url in urls[:9]:
        final, _ = poll(client, url)
        assert final.status_code == 200
    assert len(build.calls) == 9


def test_rate_limit_applies_to_new_builds_only(tmp_path):
    build = StandInBuild()
    client = make_client(tmp_path, build=build, burst=2.0, per_minute=0.001)
    first, _ = poll(client, "/api/fields?ra=10&dec=5&fov=3")
    second, _ = poll(client, "/api/fields?ra=11&dec=5&fov=3")
    assert first.status_code == second.status_code == 200
    limited = client.get("/api/fields?ra=12&dec=5&fov=3")
    assert_error(limited, 429, "busy")
    assert int(limited.headers["retry-after"]) >= 1
    # cached answers, recorded fields and bad requests are never limited
    for _ in range(20):
        assert client.get("/api/fields?ra=10&dec=5&fov=3").status_code == 200
        assert client.get("/api/fields?fixture=barnard").status_code == 200
    assert_error(client.get("/api/fields?ra=12&dec=5&fov=7"), 400, "bad_request")
    assert len(build.calls) == 2


def test_rate_limit_is_per_forwarded_client_only_when_the_secret_matched(tmp_path):
    build = StandInBuild()
    secret = {"x-tombaugh-proxy-secret": "abc"}
    client = make_client(tmp_path, secret="abc", build=build, burst=1.0, per_minute=0.001)
    one = {**secret, "x-forwarded-client-ip": "203.0.113.7"}
    two = {**secret, "x-forwarded-client-ip": "203.0.113.8"}
    assert client.get("/api/fields?ra=10&dec=5&fov=3", headers=one).status_code == 202
    assert_error(client.get("/api/fields?ra=11&dec=5&fov=3", headers=one), 429, "busy")
    assert client.get("/api/fields?ra=11&dec=5&fov=3", headers=two).status_code == 202

    # without a configured secret the header is not believed: every caller is the socket address
    open_client = make_client(tmp_path / "open", build=StandInBuild(), burst=1.0, per_minute=0.001)
    assert (
        open_client.get("/api/fields?ra=10&dec=5&fov=3", headers={"x-forwarded-client-ip": "a"}).status_code
        == 202
    )
    refused = open_client.get("/api/fields?ra=11&dec=5&fov=3", headers={"x-forwarded-client-ip": "b"})
    assert_error(refused, 429, "busy")


def test_rate_limiter_refills():
    now = [0.0]
    limiter = RateLimiter(burst=2, per_minute=6, clock=lambda: now[0])
    assert limiter.take("a") == 0.0 and limiter.take("a") == 0.0
    assert limiter.take("a") == pytest.approx(10.0)
    assert limiter.take("b") == 0.0  # another client has its own bucket
    now[0] = 4.0
    assert limiter.take("a") == pytest.approx(6.0)
    now[0] = 10.0
    assert limiter.take("a") == 0.0
    now[0] = 1000.0
    assert (
        limiter.take("a") == 0.0 and limiter.take("a") == 0.0 and limiter.take("a") > 0.0
    )  # capped at burst


def test_a_build_nobody_polls_is_cancelled(tmp_path):
    cache = FieldCache(tmp_path / "cache", max_mb=50)
    build = StandInBuild(hold=True)
    now = [1000.0]
    builder = Builder(lambda: cache, build, idle_cancel_s=20.0, clock=lambda: now[0])
    name = request_id(10.0, 5.0, 3)
    assert builder.start(name, 10.0, 5.0, 3) is not None
    assert build.started.wait(5)
    now[0] += 19.0
    assert builder.poll(name) is not None  # polled in time: still running
    now[0] += 21.0  # nobody asked for 21 s: the next progress call stops the build
    for _ in range(500):
        if builder.counts() == (0, 0):
            break
        time.sleep(0.01)
    assert builder.counts() == (0, 0)
    assert builder.poll(name) is None and cache.lookup(10.0, 5.0, 3) is None

    # a queued build that nobody polls never starts
    blocker = StandInBuild(hold=True)
    builder = Builder(lambda: cache, blocker, idle_cancel_s=20.0, clock=lambda: now[0])
    builder.start("first", 1.0, 1.0, 3)
    assert blocker.started.wait(5)
    builder.start("second", 2.0, 2.0, 3)
    assert builder.counts() == (1, 1)
    now[0] += 15.0
    builder.poll("first")
    now[0] += 15.0
    builder.poll("first")  # "second" has now waited 30 s without a poll
    assert builder.counts() == (1, 0)
    blocker.release.set()
    for _ in range(500):
        if builder.counts() == (0, 0):
            break
        time.sleep(0.01)
    assert blocker.calls == [(1.0, 1.0, 3)]


def test_an_expired_field_with_unchanged_exposures_is_not_built_again(tmp_path):
    now = [1_000_000.0]
    cache = FieldCache(tmp_path / "cache", max_mb=50, clock=lambda: now[0])
    manifest, frames, _ = synthetic_build_result(76.9563, 30.4012, 4)
    cache.put(manifest.key, manifest.model_dump_json().encode(), frames)
    cache.remember(76.9563, 30.4012, 4, manifest.key, newest_mjd=60902.5)
    asked = []

    def unchanged(ra, dec, fov, *, progress=None, deadline_s=120.0, known=None):
        asked.append(known(manifest.key))
        raise AlreadyBuilt(manifest.key)

    client = make_client(tmp_path, build=unchanged, cache=cache)
    assert client.get(URL).status_code == 200 and asked == []  # fresh: no discovery at all
    now[0] += REQUEST_TTL_S + 1.0
    final, seen = poll(client, URL)
    assert seen and final.status_code == 200 and final.json()["key"] == manifest.key
    assert asked == [True]
    assert client.get(URL).status_code == 200 and asked == [True]  # fresh again for 24 hours
    assert cache.newest_mjd() == 60902.5


def test_an_expired_field_is_still_served_when_the_archive_is_down(tmp_path):
    now = [1_000_000.0]
    cache = FieldCache(tmp_path / "cache", max_mb=50, clock=lambda: now[0])
    manifest, frames, _ = synthetic_build_result(76.9563, 30.4012, 4)
    cache.put(manifest.key, manifest.model_dump_json().encode(), frames)
    cache.remember(76.9563, 30.4012, 4, manifest.key)
    build = StandInBuild(error=http.UpstreamError("IRSA is down"))
    client = make_client(tmp_path, build=build, cache=cache)
    now[0] += REQUEST_TTL_S + 1.0
    final, seen = poll(client, URL)
    assert seen and final.status_code == 200 and final.json()["key"] == manifest.key
    assert len(build.calls) == 1
    assert client.get(URL).status_code == 200 and len(build.calls) == 1  # no rebuild storm while it is down
    now[0] += 601.0
    assert client.get(URL).status_code == 202  # ten minutes later the archive is tried again


# ---------------------------------------------------------------------------------------- disk cache
KEYS = [f"{i:016x}" for i in range(1, 9)]


def test_cache_round_trip_and_gzip(tmp_path):
    cache = FieldCache(tmp_path, max_mb=10)
    synthetic_frames = np.arange(5000, dtype="<f2").tobytes()
    assert cache.get_manifest(KEYS[0]) is None and not cache.has(KEYS[0])
    assert cache.put(KEYS[0], b'{"key": 1}', synthetic_frames) == []
    assert cache.has(KEYS[0]) and cache.get_manifest(KEYS[0]) == b'{"key": 1}'
    packed = cache.get_frames_gz(KEYS[0])
    assert packed[:2] == b"\x1f\x8b" and gzip.decompress(packed) == synthetic_frames
    assert cache.used_bytes() == len(packed) + len(b'{"key": 1}')
    assert (tmp_path / "fields" / KEYS[0] / "manifest.json").read_bytes() == b'{"key": 1}'
    assert not list(tmp_path.rglob("*.tmp"))  # nothing temporary is left behind

    assert cache.get_field(KEYS[0]) == (b'{"key": 1}', packed)  # both, read as one pair
    assert cache.get_field(KEYS[1]) == (None, None)

    cache.put(KEYS[1], b"{}", None)  # an empty field has no frame file
    assert cache.get_manifest(KEYS[1]) == b"{}" and cache.get_frames_gz(KEYS[1]) is None
    assert cache.get_field(KEYS[1]) == (b"{}", None)

    reopened = FieldCache(tmp_path, max_mb=10)  # a restart finds what is on the disk
    assert reopened.has(KEYS[0]) and reopened.used_bytes() == cache.used_bytes()
    assert gzip.decompress(reopened.get_frames_gz(KEYS[0])) == synthetic_frames


@pytest.mark.parametrize(
    "key", ["", "..", "../x", "0123456789abcde", "0123456789ABCDEF", "0123456789abcdef\n", "a/b"]
)
def test_cache_refuses_anything_that_is_not_a_key(tmp_path, key):
    cache = FieldCache(tmp_path, max_mb=10)
    with pytest.raises(ValueError):
        cache.put(key, b"{}", b"\x00\x00")
    with pytest.raises(ValueError):
        cache.remember(1.0, 2.0, 6, key)
    assert cache.get_manifest(key) is None and cache.get_frames_gz(key) is None and not cache.has(key)
    assert list((tmp_path / "fields").iterdir()) == []


def test_cache_evicts_least_recently_used_but_never_pinned_or_the_newest(tmp_path):
    now = [100.0]
    cache = FieldCache(tmp_path, max_mb=3.2, clock=lambda: now[0])  # room for three fields of 1 MB
    rng = np.random.default_rng(0)

    def synthetic_megabyte() -> bytes:
        return rng.integers(0, 256, MB, dtype=np.uint8).tobytes()  # does not compress

    for key in KEYS[:3]:
        now[0] += 10.0
        assert cache.put(key, b"{}", synthetic_megabyte()) == []
        cache.remember(float(KEYS.index(key)), 0.0, 6, key)
    cache.pin(KEYS[0])
    now[0] += 10.0
    assert cache.get_manifest(KEYS[1]) is not None  # used now: key 2 becomes the least recently used
    now[0] += 10.0
    assert cache.put(KEYS[3], b"{}", synthetic_megabyte()) == [KEYS[2]]
    assert [cache.has(key) for key in KEYS[:4]] == [True, True, False, True]
    assert cache.lookup(2.0, 0.0, 6) is None and cache.lookup(1.0, 0.0, 6) == KEYS[1]
    assert not (tmp_path / "fields" / KEYS[2]).exists()
    assert 3 * MB < cache.used_bytes() <= 3.2 * MB

    now[0] += 10.0
    assert cache.put(KEYS[4], b"{}", synthetic_megabyte()) == [KEYS[1]]  # the pinned key is older but stays
    assert cache.has(KEYS[0]) and cache.pinned() == frozenset({KEYS[0]})

    now[0] += 10.0
    big = rng.integers(0, 256, 4 * MB, dtype=np.uint8).tobytes()
    evicted = cache.put(KEYS[5], b"{}", big)  # larger than the cap by itself
    assert set(evicted) == {KEYS[3], KEYS[4]}
    assert cache.has(KEYS[5]) and cache.has(KEYS[0])  # the key just written and the pinned key remain

    cache.unpin(KEYS[0])
    now[0] += 10.0
    assert KEYS[0] in cache.put(KEYS[6], b"{}", b"\x00\x00")
    assert FieldCache(tmp_path, max_mb=3.2).pinned() == frozenset()


def test_cache_use_order_survives_a_restart(tmp_path):
    now = [1_700_000_000.0]
    cache = FieldCache(tmp_path, max_mb=10, clock=lambda: now[0])
    for key in KEYS[:3]:
        now[0] += 100.0
        cache.put(key, b"{}", b"\x00\x00")
    now[0] += 100.0
    cache.get_manifest(KEYS[0])
    assert cache.keys_by_use() == [KEYS[1], KEYS[2], KEYS[0]]
    assert FieldCache(tmp_path, max_mb=10).keys_by_use() == [KEYS[1], KEYS[2], KEYS[0]]


def test_request_index_answers_for_24_hours_and_survives_a_restart(tmp_path):
    now = [1_000_000.0]
    cache = FieldCache(tmp_path, max_mb=10, clock=lambda: now[0])
    cache.put(KEYS[0], b"{}", b"\x00\x00")
    assert cache.lookup(133.7598, -7.2422, 6) is None
    cache.remember(133.75981, -7.24219, 6, KEYS[0], newest_mjd=61174.29)
    assert cache.lookup(133.7598, -7.2422, 6) == KEYS[0]
    assert cache.lookup(133.75984, -7.24224, 6) == KEYS[0]  # snaps to the same centre
    assert cache.lookup(133.7599, -7.2422, 6) is None and cache.lookup(133.7598, -7.2422, 8) is None
    assert request_id(133.75981, -7.24219, 6) == "133.7598,-7.2422,6"
    assert cache.newest_mjd() == 61174.29

    reopened = FieldCache(tmp_path, max_mb=10, clock=lambda: now[0])
    assert reopened.lookup(133.7598, -7.2422, 6) == KEYS[0] and reopened.newest_mjd() == 61174.29
    now[0] += REQUEST_TTL_S - 1.0
    assert reopened.lookup(133.7598, -7.2422, 6) == KEYS[0]
    now[0] += 2.0
    assert reopened.lookup(133.7598, -7.2422, 6) is None  # older than 24 hours: discover again
    assert (
        reopened.lookup(133.7598, -7.2422, 6, max_age_s=None) == KEYS[0]
    )  # still there if the archive is down

    reopened.remember(133.7598, -7.2422, 6, KEYS[0], age_s=REQUEST_TTL_S - 600.0)
    assert reopened.newest_mjd() == 61174.29  # kept when not given again
    now[0] += 599.0
    assert reopened.lookup(133.7598, -7.2422, 6) == KEYS[0]
    now[0] += 2.0
    assert reopened.lookup(133.7598, -7.2422, 6) is None


def test_request_index_remembers_the_listing_of_a_complete_build(tmp_path):
    now = [1_000_000.0]
    cache = FieldCache(tmp_path, max_mb=10, clock=lambda: now[0])
    cache.put(KEYS[0], b"{}", b"\x00\x00")
    cache.put(KEYS[1], b"{}", b"\x00\x00")
    position = (133.7598, -7.2422, 6)
    listing, other_listing = KEYS[6], KEYS[7]

    assert cache.field_for_listing(*position, listing) is None
    assert cache.field_for_listing(*position, KEYS[0]) == KEYS[0]  # a field that used every listed exposure
    cache.remember(*position, KEYS[0], listing_key=listing)
    assert cache.field_for_listing(*position, listing) == KEYS[0]
    assert cache.field_for_listing(*position, other_listing) is None  # the archive lists something else
    assert cache.field_for_listing(10.0, 20.0, 6, listing) is None  # another request

    now[0] += REQUEST_TTL_S + 1.0  # the entry no longer answers requests, but still knows its listing
    assert cache.lookup(*position) is None and cache.field_for_listing(*position, listing) == KEYS[0]
    reopened = FieldCache(tmp_path, max_mb=10, clock=lambda: now[0])
    assert reopened.field_for_listing(*position, listing) == KEYS[0]  # and it survives a restart

    cache.remember(*position, KEYS[0], age_s=REQUEST_TTL_S - 600.0)  # the same field again: listing kept
    assert cache.field_for_listing(*position, listing) == KEYS[0]
    cache.remember(*position, KEYS[1])  # another field without a listing: a partial build, say
    assert cache.field_for_listing(*position, listing) is None
    cache.remember(*position, KEYS[0], listing_key=listing)
    assert cache.field_for_listing(*position, listing) == KEYS[0]
    cache._remove(KEYS[0])  # evicted: the listing answers nothing
    assert cache.field_for_listing(*position, listing) is None


def test_cache_drops_folders_left_incomplete_by_a_crash(tmp_path):
    cache = FieldCache(tmp_path, max_mb=10)
    cache.put(KEYS[0], b"{}", b"\x00\x00")
    broken = tmp_path / "fields" / KEYS[1]
    broken.mkdir()
    (broken / "frames.bin.gz").write_bytes(b"half")  # frames written, manifest never arrived
    (tmp_path / "fields" / KEYS[0] / ".manifest.json.1.abc.tmp").write_bytes(b"partial")
    (tmp_path / "requests.json").write_text("{not json", encoding="utf-8")
    reopened = FieldCache(tmp_path, max_mb=10)
    assert reopened.has(KEYS[0]) and not reopened.has(KEYS[1]) and not broken.exists()
    assert not list(tmp_path.rglob("*.tmp"))
    assert reopened.lookup(1.0, 2.0, 6) is None


def test_cache_location_and_cap_come_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("TOMBAUGH_CACHE_DIR", raising=False)
    monkeypatch.delenv("TOMBAUGH_CACHE_MAX_MB", raising=False)
    assert default_cache_dir() == REPO / ".cache"  # found relative to the package, at the repository root
    assert default_max_mb() == 2500.0
    monkeypatch.setenv("TOMBAUGH_CACHE_DIR", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("TOMBAUGH_CACHE_MAX_MB", "12")
    cache = FieldCache()
    assert cache.root == tmp_path / "elsewhere" and cache.max_bytes == 12 * MB
    assert cache.free_bytes() == 12 * MB
    monkeypatch.setenv("TOMBAUGH_CACHE_MAX_MB", "lots")
    assert default_max_mb() == 2500.0


def test_exported_manifest_schema_is_current():
    """docs/contract/manifest.schema.json is exported from the models (Contract section 9)."""
    exported = json.loads((REPO / "docs" / "contract" / "manifest.schema.json").read_text(encoding="utf-8"))
    assert exported == models.manifest_schema()
    assert exported["title"] == "Tombaugh manifest (Contract v1.0)"
    assert "fixture_stars" not in exported["required"] and "frames" in exported["required"]


def test_no_local_path_is_written_in_the_sources():
    """Paths in the package are repo-relative: no home folder or temporary folder of a developer machine."""
    home_folders = ["/" + name + "/" for name in ("Users", "home", "private")]
    for path in (REPO / "api" / "tombaugh").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(folder in text for folder in home_folders), path.name


def test_field_key_of_the_recorded_fields_has_the_key_shape():
    for name in FIXTURE_NAMES:
        manifest = json.loads((FIXTURES_DIR / name / "manifest.json").read_text(encoding="utf-8"))
        assert len(manifest["key"]) == 16 and int(manifest["key"], 16) >= 0
        assert manifest["key"] != field_key(manifest["centre"]["ra"], manifest["centre"]["dec"], 6, [])
