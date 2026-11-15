"""The Tombaugh HTTP service (Contract v1.0, section 7).

    uv run uvicorn tombaugh.main:app --port 8080

One process, one build at a time. `GET /api/fields` answers from the disk cache when it can; otherwise it
starts a build on the single worker thread, or joins the one already running for the same snapped request,
and answers 202 until the build is done. Recorded fields (`?fixture=NAME`) come straight from
``cache/fixtures`` and need no upstream.

`GET /api/fields/{key}/overlays` (Contract 7.3) and `GET /api/fields/{key}/spectrum` (Contract 7.1) work for
built and recorded fields alike; `{key}` is the manifest's content key (a recorded field's name is accepted
too, as for frames.bin). Both answer in the request's own thread, never on the build worker, and keep what
they fetched in the disk cache's derived files: the catalogue answer per key (final once both catalogues
answered), the field's exposure list (written at build time, or found again from the archive for a recorded
field), and each complete spectrum per key and snapped target. At most `SPECTRUM_SLOTS` spectra are measured
at once; an identical request joins the one being measured.

Settings, all optional environment variables:

    TOMBAUGH_CACHE_DIR, TOMBAUGH_CACHE_MAX_MB   the disk cache (see tombaugh.cache)
    TOMBAUGH_FIXTURES_DIR      folder of recorded fields; default cache/fixtures at the repository root
    TOMBAUGH_CORS_ORIGINS      comma-separated origins allowed to call the API; default http://localhost:5173
    TOMBAUGH_PROXY_SECRET      when set, every /api request must carry it in x-tombaugh-proxy-secret
    TOMBAUGH_RATE_BURST, TOMBAUGH_RATE_PER_MINUTE   per-client limit on NEW builds; defaults 5 and 3
    TOMBAUGH_PROBE_UPSTREAMS   "0" stops /api/status from probing the archives

Logs are one JSON object per line on standard output: one per request, one per build.
Durations are seconds unless a name says milliseconds.
"""

from __future__ import annotations

import datetime as _dt
import gzip
import hmac
import json
import logging
import math
import os
import re
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from tombaugh import CONTRACT_VERSION, __version__, catalogs, http, photometry
from tombaugh import spectrum as spectra
from tombaugh.build import (
    DEFAULT_DEADLINE_S,
    MAX_EXPOSURES,
    AlreadyBuilt,
    BuildStats,
    build_field_for_service,
    frames_version,
    sample_exposures,
)
from tombaugh.cache import MB, REQUEST_TTL_S, FieldCache, compress_frames, is_key, request_id
from tombaugh.discovery import BUCKET, REGION, SIA_URL, discover, parse_sia_csv_counted
from tombaugh.grid import ALLOWED_FOV, snap
from tombaugh.models import (
    BuildingResponse,
    BuildsStatus,
    CacheStatus,
    ErrorResponse,
    Manifest,
    NewestExposure,
    OverlaysResponse,
    Progress,
    SnappedTo,
    SpectrumResponse,
    StatusResponse,
    UpstreamHealth,
)
from tombaugh.timebins import mjd_to_date
from tombaugh.types import Exposure

DEFAULT_FOV = 6
DEFAULT_CORS_ORIGINS = ("http://localhost:5173",)
SECRET_HEADER = "x-tombaugh-proxy-secret"
CLIENT_IP_HEADER = "x-forwarded-client-ip"
FIXTURE_NAME = re.compile(r"[a-z0-9_]{1,64}")  # used with fullmatch: ^[a-z0-9_]+$
FRAMES_CACHE_CONTROL = "public, max-age=31536000, immutable"  # Contract section 6
FIXTURE_ALIAS_CACHE_CONTROL = "public, max-age=300"  # a fixture NAME is not a content key: it can be rebuilt
NO_STORE = "no-store"

MAX_WAITING = 8  # builds that may wait behind the running one
IDLE_CANCEL_S = 20.0  # a build nobody has polled for this long is cancelled
ERROR_TTL_S = 15.0  # how long a failed build keeps answering with its error before a new one may start
RETRY_AFTER_QUEUE_S = 10
POLL_AFTER_S = 1
# Python's thread switch interval (default 5 ms). The reader threads of a build and of a spectrum parse FITS
# headers in Python; with about 20 of them runnable, the event loop that answers /healthz waited its turn up
# to 230 ms at the default (measured 14 Nov 2026, local server, cold spectra). See docs/ENGINE_NOTES.md.
SWITCH_INTERVAL_S = 0.001
RETRY_INCOMPLETE_S = 600.0  # a partial field, or one with failed downloads, is rebuilt after this long
RETRY_STALE_S = 600.0  # an expired field served because the archive is down is retried after this long
DEFAULT_RATE_BURST = 5.0
DEFAULT_RATE_PER_MINUTE = 3.0
RATE_CLIENTS_MAX = 10000  # token buckets kept in memory
PROBE_MAX_AGE_S = 300.0
PROBE_DEADLINE_S = 20.0
PROBE_TIMEOUT = (5.0, 15.0)
PROBE_POSITION = "circle 133.7598 -7.2422 0.01"  # a field that public exposures cover (WISE 0855-0714)
UPSTREAM_DOWN_MESSAGE = (
    "The SPHEREx archive cannot be reached right now and this field is not cached. Try again in a minute."
)

# Derived answers (disk cache, tombaugh.cache "derived" files). Names carry the pipeline version where the
# code that makes them can change; an exposure list is what the archive listed, whatever the code.
EXPOSURES_NAME = "exposures.json.gz"
OVERLAYS_NAME = f"overlays-{__version__}.json.gz"
OVERLAYS_RETRY_S = 300.0  # a catalogue that failed is asked again for the same key after this long
FINAL_CACHE_CONTROL = "public, max-age=86400"  # a complete overlays or spectrum answer of a content key
SPECTRUM_SLOTS = 2  # spectra measured at the same time; more answer 429
SPECTRUM_DEADLINE_S = 60.0  # the photometry's reads stop here (Contract 7.1 sets none; measured 21 s for 258)
SPECTRUM_DISCOVER_DEADLINE_S = 30.0  # finding a recorded field's exposures again
SPECTRUM_JOIN_WAIT_S = 120.0  # how long an identical request waits for the measurement it joined
RETRY_AFTER_SPECTRUM_S = 15
INCOMPLETE_HEADER = "X-Tombaugh-Incomplete"  # says how many exposures a spectrum is missing (not cached)
CATALOGUES_DOWN_MESSAGE = (
    "The catalogues that place the source and its neighbours (Gaia DR3, CatWISE2020) cannot be reached "
    "right now, so no spectrum can be measured honestly. Try again in a minute."
)
SPECTRUM_UPSTREAM_MESSAGE = "The SPHEREx archive could not be read for this spectrum. Try again in a minute."

BuildFn = Callable[..., tuple[Manifest, bytes, BuildStats]]
OverlaysFn = Callable[..., OverlaysResponse]
MeasureFn = Callable[..., tuple]
DiscoverFn = Callable[..., list[Exposure]]

log = logging.getLogger("tombaugh.api")


# --------------------------------------------------------------------------------------------- logging
class _JsonLines(logging.Formatter):
    """One JSON object per line. A message that already is a JSON object only gets a timestamp."""

    def format(self, record: logging.LogRecord) -> str:
        stamp = (
            _dt.datetime.fromtimestamp(record.created, _dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        )
        message = record.getMessage()
        if message.startswith('{"') and message.endswith("}"):
            return f'{{"ts": "{stamp}", {message[1:]}'
        entry = {"ts": stamp, "event": "log", "level": record.levelname.lower(), "logger": record.name}
        entry["message"] = message
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def configure_logging() -> None:
    """Send the package's logs to standard output as JSON lines (does nothing the second time)."""
    logger = logging.getLogger("tombaugh")
    if any(isinstance(handler.formatter, _JsonLines) for handler in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonLines())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _log(event: str, **fields: object) -> None:
    log.info(json.dumps({"event": event, **fields}, default=str))


def _utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# -------------------------------------------------------------------------------------------- settings
def _env_number(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if math.isfinite(value) and value > 0.0 else default


def default_fixtures_dir() -> Path:
    """``TOMBAUGH_FIXTURES_DIR`` when set, else ``cache/fixtures`` at the repository root."""
    configured = os.environ.get("TOMBAUGH_FIXTURES_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "cache" / "fixtures"


@dataclass(frozen=True)
class Settings:
    """What the service reads from its environment."""

    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    proxy_secret: str = ""
    fixtures_dir: Path | None = None
    rate_burst: float = DEFAULT_RATE_BURST
    rate_per_minute: float = DEFAULT_RATE_PER_MINUTE
    probe_upstreams: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        """The settings of this process."""
        listed = os.environ.get("TOMBAUGH_CORS_ORIGINS", "")
        origins = tuple(origin.strip().rstrip("/") for origin in listed.split(",") if origin.strip())
        return cls(
            cors_origins=origins or DEFAULT_CORS_ORIGINS,
            proxy_secret=os.environ.get("TOMBAUGH_PROXY_SECRET", "").strip(),
            fixtures_dir=default_fixtures_dir(),
            rate_burst=_env_number("TOMBAUGH_RATE_BURST", DEFAULT_RATE_BURST),
            rate_per_minute=_env_number("TOMBAUGH_RATE_PER_MINUTE", DEFAULT_RATE_PER_MINUTE),
            probe_upstreams=os.environ.get("TOMBAUGH_PROBE_UPSTREAMS", "1").strip() != "0",
        )


# ------------------------------------------------------------------------------------------- responses
def error_response(
    status: int, code: str, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    """An error in the contract shape: {"contract", "status": "error", "code", "message"}."""
    body = ErrorResponse(code=code, message=message).model_dump()
    return JSONResponse(body, status_code=status, headers={"Cache-Control": NO_STORE, **(headers or {})})


def _json_bytes(body: bytes, status: int = 200) -> Response:
    return Response(
        body, status_code=status, media_type="application/json", headers={"Cache-Control": NO_STORE}
    )


def _frames_response(body: bytes, cache_control: str) -> Response:
    """The gzip bytes of a frame file, declared as such (Contract section 6)."""
    headers = {"Content-Encoding": "gzip", "Cache-Control": cache_control}
    return Response(body, media_type="application/octet-stream", headers=headers)


def accepts_gzip(header: str | None) -> bool:
    """True when an Accept-Encoding header allows gzip (by name or "*", with a q above zero)."""
    for item in (header or "").split(","):
        name, _, params = item.strip().partition(";")
        if name.strip().lower() not in ("gzip", "*"):
            continue
        quality = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if quality > 0.0:
            return True
    return False


def _json_gz_response(
    body_gz: bytes, request: Request, cache_control: str, headers: Mapping[str, str] | None = None
) -> Response:
    """A JSON body kept gzip-compressed: sent as it is when the client takes gzip, else unpacked."""
    sent = {"Cache-Control": cache_control, "Vary": "Accept-Encoding", **(headers or {})}
    if accepts_gzip(request.headers.get("accept-encoding")):
        sent["Content-Encoding"] = "gzip"
        return Response(body_gz, media_type="application/json", headers=sent)
    return Response(gzip.decompress(body_gz), media_type="application/json", headers=sent)


def _pack(data: bytes) -> bytes:
    """The deterministic gzip of the cache (the same as for frame files)."""
    return compress_frames(data)


def _for_this_click(body_gz: bytes, snapped_to: SnappedTo | None) -> bytes:
    """A measured spectrum (gzip JSON) as answered to one click: its `target.snapped_to` is this click's.

    A spectrum is kept and shared per snapped source, and the separation between the click and the source
    differs from click to click; nothing else in the answer depends on the click.
    """
    answer = SpectrumResponse.model_validate_json(gzip.decompress(body_gz))
    if answer.target.snapped_to == snapped_to:
        return body_gz
    answer.target.snapped_to = snapped_to
    return _pack(answer.model_dump_json().encode())


def _still_asking() -> JSONResponse:
    """429 for a request that joined a catalogue query which outlasted its wait."""
    message = "The catalogues are still being asked for this field. Try again shortly."
    return error_response(429, "busy", message, {"Retry-After": str(RETRY_AFTER_SPECTRUM_S)})


_CODE_BY_STATUS = {400: "bad_request", 404: "not_found", 429: "busy", 503: "upstream_unavailable"}


class BadRequest(ValueError):
    """A query that the contract answers with 400 bad_request; the text is shown to the user."""


def _number(params: Mapping[str, str], name: str, low: float, high: float) -> float:
    text = params.get(name)
    if text is None or not text.strip():
        raise BadRequest(f"'{name}' is required: decimal degrees from {low:g} to {high:g}.")
    try:
        value = float(text)
    except ValueError:
        value = math.nan
    if not (math.isfinite(value) and low <= value <= high):
        raise BadRequest(f"'{name}' must be a number of degrees from {low:g} to {high:g}.")
    return value


def parse_position(params: Mapping[str, str]) -> tuple[float, float, int]:
    """(ra, dec, fov) of a query: degrees, degrees, arcmin. Raises BadRequest outside the contract's limits."""
    ra = _number(params, "ra", 0.0, 360.0)
    dec = _number(params, "dec", -90.0, 90.0)
    text = params.get("fov")
    if text is None or not text.strip():
        return ra, dec, DEFAULT_FOV
    try:
        fov = float(text)
    except ValueError:
        fov = math.nan
    if fov not in ALLOWED_FOV:
        choices = ", ".join(str(choice) for choice in ALLOWED_FOV)
        raise BadRequest(f"'fov' must be one of {choices} (arcmin).")
    return ra, dec, int(fov)


# -------------------------------------------------------------------------------------------- fixtures
def _recorded_sha256(manifest: object) -> str:
    """The SHA-256 a manifest (a parsed JSON document) records for its frame file; "" when it has none."""
    frames = manifest.get("frames") if isinstance(manifest, dict) else None
    digest = frames.get("sha256") if isinstance(frames, dict) else None
    return digest if isinstance(digest, str) else ""


@dataclass
class _Fixture:
    stamp: tuple[int, int]  # modification times (ns) of manifest.json and frames.bin
    manifest: bytes
    frames_gz: bytes
    key: str
    sha256: str  # of the uncompressed frame bytes, as the manifest records it
    newest_mjd: float | None


class Fixtures:
    """The recorded real fields under ``cache/fixtures/<name>/`` (Contract section 8)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()
        self._loaded: dict[str, _Fixture] = {}

    def names(self) -> list[str]:
        """Names of the recorded fields present on the disk."""
        try:
            folders = [entry for entry in self.root.iterdir() if entry.is_dir()]
        except OSError:
            return []
        return sorted(
            folder.name
            for folder in folders
            if FIXTURE_NAME.fullmatch(folder.name) and (folder / "manifest.json").is_file()
        )

    def get(self, name: str) -> _Fixture | None:
        """The fixture `name`, read once and again whenever its files change; None when it does not exist."""
        if not isinstance(name, str) or FIXTURE_NAME.fullmatch(name) is None:
            return None
        manifest_path, frames_path = self.root / name / "manifest.json", self.root / name / "frames.bin"
        try:
            stamp = (manifest_path.stat().st_mtime_ns, frames_path.stat().st_mtime_ns)
        except OSError:
            return None
        with self._lock:
            held = self._loaded.get(name)
            if held is not None and held.stamp == stamp:
                return held
            try:
                manifest = manifest_path.read_bytes()
                document = json.loads(manifest)
                frames_gz = compress_frames(frames_path.read_bytes())
            except (OSError, ValueError):
                return None
            exposures = document.get("exposures") or {}
            newest = exposures.get("newest_mjd")
            loaded = _Fixture(
                stamp=stamp,
                manifest=manifest,
                frames_gz=frames_gz,
                key=str(document.get("key", "")),
                sha256=_recorded_sha256(document),
                newest_mjd=float(newest) if isinstance(newest, int | float) else None,
            )
            self._loaded[name] = loaded
            return loaded

    def by_key(self, key: str) -> _Fixture | None:
        """The fixture whose manifest carries the content key `key`, or None."""
        for name in self.names():
            fixture = self.get(name)
            if fixture is not None and fixture.key == key:
                return fixture
        return None

    def newest_mjd(self) -> float | None:
        """Mid-time (MJD days) of the newest exposure in any recorded field, or None."""
        loaded = (self.get(name) for name in self.names())
        times = [fixture.newest_mjd for fixture in loaded if fixture and fixture.newest_mjd is not None]
        return max(times, default=None)


# ---------------------------------------------------------------------------------------- rate limiter
class RateLimiter:
    """A token bucket per client: `burst` tokens at most, refilled at `per_minute` tokens a minute."""

    def __init__(self, burst: float, per_minute: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.burst = max(1.0, float(burst))
        self.per_second = max(1e-6, float(per_minute) / 60.0)
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}  # client -> (tokens, time of that count)

    def take(self, client: str) -> float:
        """Take one token for `client`. Returns 0.0 on success, else the seconds until one is available."""
        now = self._clock()
        with self._lock:
            tokens, since = self._buckets.get(client, (self.burst, now))
            tokens = min(self.burst, tokens + (now - since) * self.per_second)
            if tokens >= 1.0:
                self._buckets[client] = (tokens - 1.0, now)
                wait = 0.0
            else:
                self._buckets[client] = (tokens, now)
                wait = (1.0 - tokens) / self.per_second
            if len(self._buckets) > RATE_CLIENTS_MAX:
                self._forget_full_buckets(now)
            return wait

    def _forget_full_buckets(self, now: float) -> None:
        """Drop the clients whose bucket has refilled: forgetting them changes nothing."""
        full = [
            client
            for client, (tokens, since) in self._buckets.items()
            if tokens + (now - since) * self.per_second >= self.burst
        ]
        for client in full:
            del self._buckets[client]
        if len(self._buckets) > RATE_CLIENTS_MAX:  # all are in use: forget the oldest half
            oldest = sorted(self._buckets, key=lambda client: self._buckets[client][1])
            for client in oldest[: len(oldest) // 2]:
                del self._buckets[client]


# --------------------------------------------------------------------------------------------- builds
class _Cancelled(Exception):
    """Nobody has polled the build for IDLE_CANCEL_S seconds."""


@dataclass
class Job:
    """One build, waiting or running, or failed a moment ago."""

    name: str  # request_id of the snapped request
    ra: float  # the position as first requested, degrees
    dec: float
    fov: int  # arcmin
    last_polled: float  # monotonic seconds
    state: str = "queued"  # "queued" | "running" | "failed"
    stage: str = "discover"
    done: int = 0
    total: int = 0
    error: tuple[int, str, str] | None = None  # (HTTP status, code, message)
    expires: float = 0.0  # monotonic seconds after which a failed job is forgotten


class Builder:
    """The build queue: one worker thread, at most `max_waiting` builds behind the running one."""

    def __init__(
        self,
        cache: Callable[[], FieldCache],
        build: BuildFn,
        *,
        max_waiting: int = MAX_WAITING,
        idle_cancel_s: float = IDLE_CANCEL_S,
        deadline_s: float = DEFAULT_DEADLINE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cache = cache
        self._build = build
        self.max_waiting = max_waiting
        self.idle_cancel_s = idle_cancel_s
        self.deadline_s = deadline_s
        self._clock = clock
        self._wake = threading.Condition()
        self._jobs: dict[str, Job] = {}
        self._queue: deque[Job] = deque()
        self._worker: threading.Thread | None = None

    def _drop_dead_jobs(self) -> None:
        """Forget failed jobs past their time and queued jobs nobody polls any more (call under the lock)."""
        now = self._clock()
        for job in list(self._jobs.values()):
            expired = job.state == "failed" and now >= job.expires
            abandoned = job.state == "queued" and now - job.last_polled > self.idle_cancel_s
            if expired or abandoned:
                del self._jobs[job.name]
        self._queue = deque(job for job in self._queue if self._jobs.get(job.name) is job)

    def poll(self, name: str) -> Job | None:
        """The job of a request, if one is waiting, running or has just failed; marks it as polled now."""
        with self._wake:
            self._drop_dead_jobs()
            job = self._jobs.get(name)
            if job is not None:
                job.last_polled = self._clock()
            return job

    def has_room(self) -> bool:
        """True when one more build may wait."""
        with self._wake:
            self._drop_dead_jobs()
            return self._waiting() < self.max_waiting

    def _busy(self) -> bool:
        return any(job.state == "running" for job in self._jobs.values())

    def _waiting(self) -> int:
        """Builds that wait behind another one: the head of the queue starts at once when nothing runs."""
        return max(0, len(self._queue) - (0 if self._busy() else 1))

    def start(self, name: str, ra: float, dec: float, fov: int) -> Job | None:
        """Queue a build, or join the one already there for `name`. None when the queue is full."""
        with self._wake:
            self._drop_dead_jobs()
            job = self._jobs.get(name)
            if job is not None and job.state != "failed":
                job.last_polled = self._clock()
                return job
            if self._waiting() >= self.max_waiting:
                return None
            job = Job(name=name, ra=ra, dec=dec, fov=fov, last_polled=self._clock())
            self._jobs[name] = job
            self._queue.append(job)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._work, name="tombaugh-build", daemon=True)
                self._worker.start()
            self._wake.notify_all()
            return job

    def counts(self) -> tuple[int, int]:
        """(builds running, builds waiting)."""
        with self._wake:
            self._drop_dead_jobs()
            busy = self._busy()
            return (1 if busy or self._queue else 0), self._waiting()

    def _work(self) -> None:
        while True:
            with self._wake:
                while not self._queue:
                    self._wake.wait()
                self._drop_dead_jobs()
                if not self._queue:
                    continue
                job = self._queue.popleft()
                job.state = "running"
            self._run(job)

    def _progress(self, job: Job) -> Callable[[str, int, int], None]:
        def report(stage: str, done: int, total: int) -> None:
            with self._wake:
                job.stage, job.done, job.total = stage, int(done), int(total)
                idle = self._clock() - job.last_polled
            if idle > self.idle_cancel_s:
                raise _Cancelled()

        return report

    def _run(self, job: Job) -> None:
        """Build one field and store it; the outcome is logged and, when it failed, kept for the next poll."""
        started = time.monotonic()
        ra0, dec0 = snap(job.ra, job.dec)
        error: tuple[int, str, str] | None = None
        outcome, key = "internal", ""
        held: list[str] = []  # the stored field that answers the listing, once `known` has found it

        def known(listing_key: str) -> bool:
            field = cache.field_for_listing(ra0, dec0, job.fov, listing_key)
            if field is not None:
                held.append(field)
            return field is not None

        try:
            cache = self._cache()
            try:
                manifest, frames, stats = self._build(
                    job.ra,
                    job.dec,
                    job.fov,
                    progress=self._progress(job),
                    deadline_s=self.deadline_s,
                    known=known,
                )
            except AlreadyBuilt as same:  # the archive lists the same exposures as last time
                key = held[-1] if held else same.key
                cache.remember(ra0, dec0, job.fov, key, listing_key=same.key)
                outcome = "unchanged"
            except _Cancelled:
                outcome = "cancelled"
            except http.UpstreamError as exc:
                stale = cache.lookup(ra0, dec0, job.fov, max_age_s=None)
                if stale is not None:  # the archive is down: keep serving what is there, retry soon
                    cache.remember(ra0, dec0, job.fov, stale, age_s=REQUEST_TTL_S - RETRY_STALE_S)
                    outcome, key = "stale", stale
                else:
                    outcome = "upstream_unavailable"
                    error = (503, "upstream_unavailable", UPSTREAM_DOWN_MESSAGE)
                log.warning("build %s: upstream error: %s", job.name, exc)
            else:
                if stats.exposures:  # what the spectrum of this field will measure (see Service.spectrum)
                    exposures = _pack(spectra.exposures_to_json(stats.exposures))
                    cache.put_derived(manifest.key, EXPOSURES_NAME, exposures)
                cache.put(manifest.key, manifest.model_dump_json().encode("utf-8"), frames or None)
                incomplete = stats.timed_out > 0 or stats.failed > 0 or stats.legacy_incomplete
                cache.remember(
                    ra0,
                    dec0,
                    job.fov,
                    manifest.key,
                    newest_mjd=stats.newest_found_mjd,
                    age_s=REQUEST_TTL_S - RETRY_INCOMPLETE_S if incomplete else 0.0,
                    listing_key=None if incomplete else stats.listing_key or None,
                )
                outcome, key = manifest.status, manifest.key
        except Exception:  # the worker thread must survive any single build
            log.exception("build %s failed", job.name)
            error = (500, "internal", "The build failed unexpectedly. Try again.")
        finally:
            with self._wake:
                if error is None:
                    self._jobs.pop(job.name, None)
                else:
                    job.state, job.error = "failed", error
                    job.expires = self._clock() + ERROR_TTL_S
            seconds = round(time.monotonic() - started, 3)
            _log("job", request=job.name, outcome=outcome, key=key, seconds=seconds)


# -------------------------------------------------------------------------------------- upstream probes
def probe_irsa_sia() -> None:
    """One small image search at IRSA; raises when it does not answer with an SIA table."""
    params = {"COLLECTION": "spherex_dr1", "POS": PROBE_POSITION, "RESPONSEFORMAT": "csv", "MAXREC": "1"}
    deadline = http.Deadline(PROBE_DEADLINE_S)
    response = http.get(SIA_URL, params=params, tries=1, timeout=PROBE_TIMEOUT, deadline=deadline)
    parse_sia_csv_counted(response.content.decode("utf-8", "replace"), "spherex_dr1")


def probe_s3() -> None:
    """One listing of a single key of the public bucket; raises when the bucket does not answer."""
    url = f"https://{BUCKET}.s3.{REGION}.amazonaws.com/"
    params = {"list-type": "2", "max-keys": "1"}
    http.get(url, params=params, tries=1, timeout=PROBE_TIMEOUT, deadline=http.Deadline(PROBE_DEADLINE_S))


DEFAULT_PROBES: dict[str, Callable[[], None]] = {"irsa_sia": probe_irsa_sia, "s3": probe_s3}


class UpstreamProbes:
    """Health of the upstreams, checked in a background thread and remembered for five minutes."""

    def __init__(
        self,
        checks: Mapping[str, Callable[[], None]],
        *,
        max_age_s: float = PROBE_MAX_AGE_S,
        enabled: bool = True,
    ) -> None:
        self._checks = dict(checks)
        self._max_age_s = max_age_s
        self._enabled = enabled
        self._lock = threading.Lock()
        self._results = {name: UpstreamHealth(ok=False, latency_ms=None, checked_at=None) for name in checks}
        self._checked: float | None = None  # monotonic seconds of the last round
        self._running = False

    def snapshot(self) -> dict[str, UpstreamHealth]:
        """The last results, at once. A new round starts in the background when they are too old.

        Before the first round has finished every upstream reads ok false with `checked_at` null.
        """
        with self._lock:
            stale = self._checked is None or time.monotonic() - self._checked > self._max_age_s
            if self._enabled and stale and not self._running:
                self._running = True
                threading.Thread(target=self._round, name="tombaugh-probe", daemon=True).start()
            return dict(self._results)

    def _round(self) -> None:
        try:
            for name, check in self._checks.items():
                started = time.monotonic()
                try:
                    check()
                    ok = True
                except Exception as exc:  # noqa: BLE001 - any failure means "not ok"
                    ok = False
                    log.warning("upstream %s is not answering: %s", name, exc)
                latency = round((time.monotonic() - started) * 1000.0)
                with self._lock:
                    self._results[name] = UpstreamHealth(ok=ok, latency_ms=latency, checked_at=_utc_now())
        finally:
            with self._lock:
                self._checked = time.monotonic()
                self._running = False


# ------------------------------------------------------------------------------- overlays and spectra
@dataclass(frozen=True)
class FieldRef:
    """A field that exists here: its content key and manifest, built (disk cache) or recorded."""

    key: str
    manifest: Manifest
    recorded: bool


class Busy(Exception):
    """Every spectrum slot is taken (HTTP 429)."""


@dataclass(frozen=True)
class SpectrumResult:
    """A measured spectrum: its JSON, gzip-compressed, and what it lacks when it is not complete."""

    body_gz: bytes
    missing: int = 0  # exposures not read (failed, or past the deadline) or without a point-spread function
    requested: int = 0

    @property
    def complete(self) -> bool:
        return self.missing == 0


class SingleFlight:
    """One computation per name at a time: later callers of the same name wait for the first one's result."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: dict[str, Future] = {}

    def run(self, name: str, compute: Callable[[], object], wait_s: float) -> object:
        with self._lock:
            future = self._running.get(name)
            owner = future is None
            if owner:
                future = self._running[name] = Future()
        if not owner:
            return future.result(timeout=wait_s)  # raises what the first caller raised
        try:
            result = compute()
        except BaseException as exc:
            future.set_exception(exc)
            raise
        else:
            future.set_result(result)
            return result
        finally:
            with self._lock:
                self._running.pop(name, None)


# --------------------------------------------------------------------------------------------- service
class Service:
    """Everything the routes share: settings, recorded fields, cache, build queue, limiter and probes.

    `overlays`, `measure` and `discover` replace the catalogue queries (`catalogs.overlays_for_manifest`),
    the photometry (`photometry.measure_with_stats`) and the archive search (`discovery.discover`); tests
    pass stand-ins.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        cache: FieldCache | None = None,
        build: BuildFn = build_field_for_service,
        probes: UpstreamProbes | None = None,
        overlays: OverlaysFn = catalogs.overlays_for_manifest,
        measure: MeasureFn = photometry.measure_with_stats,
        discover: DiscoverFn = discover,
    ) -> None:
        self.settings = settings
        self.fixtures = Fixtures(settings.fixtures_dir or default_fixtures_dir())
        self._cache = cache
        self._cache_lock = threading.Lock()
        self.builder = Builder(lambda: self.cache, build)
        self.limiter = RateLimiter(settings.rate_burst, settings.rate_per_minute)
        self.probes = probes or UpstreamProbes(DEFAULT_PROBES, enabled=settings.probe_upstreams)
        self._overlays_fn = overlays
        self._measure_fn = measure
        self._discover_fn = discover
        self._flights = SingleFlight()
        self._overlays_tried: dict[str, float] = {}  # key -> monotonic time of the last catalogue query
        self._spectrum_slots = threading.BoundedSemaphore(SPECTRUM_SLOTS)

    @property
    def cache(self) -> FieldCache:
        """The disk cache, opened on first use so that importing this module writes nothing."""
        with self._cache_lock:
            if self._cache is None:
                self._cache = FieldCache()
            return self._cache

    # ---------------------------------------------------------------- who is asking
    def secret_ok(self, request: Request) -> bool:
        """True when no proxy secret is configured, or the request carries the right one."""
        secret = self.settings.proxy_secret
        if not secret:
            return True
        given = request.headers.get(SECRET_HEADER, "")
        return hmac.compare_digest(given.encode("utf-8"), secret.encode("utf-8"))

    def client_of(self, request: Request) -> str:
        """The address a build is charged to: the proxy's client address when the secret matched."""
        if self.settings.proxy_secret and self.secret_ok(request):
            forwarded = request.headers.get(CLIENT_IP_HEADER, "").strip()
            if forwarded:
                return forwarded[:64]
        return request.client.host if request.client else "unknown"

    # ---------------------------------------------------------------- answers
    def fixture_manifest(self, name: str) -> Response:
        fixture = self.fixtures.get(name)
        if fixture is None:
            return error_response(404, "not_found", "There is no recorded field of that name.")
        return _json_bytes(fixture.manifest)

    def _frame_copies(self, key: str) -> list[tuple[str, bytes]]:
        """(SHA-256 of the uncompressed bytes, gzip bytes) of every frame file held under a content key.

        The disk cache's copy comes first, then a recorded field's. They differ when the same exposures
        were stacked by two states of the pipeline or of the archive.
        """
        copies: list[tuple[str, bytes]] = []
        manifest, body = self.cache.get_field(key)
        if body is not None:
            try:
                document = json.loads(manifest or b"null")
            except ValueError:
                document = None
            copies.append((_recorded_sha256(document), body))
        recorded = self.fixtures.by_key(key)
        if recorded is not None:
            copies.append((recorded.sha256, recorded.frames_gz))
        return copies

    def frames(self, key: str, version: str | None = None) -> Response:
        """The frame file of a content key, or of a recorded field by its name.

        `version` is the `v` of a manifest's frame URL (`tombaugh.build.frames_url`): only the copy whose
        SHA-256 starts with it is served, so a manifest is never paired with another build's frames. A
        request without it gets the first copy, as before.
        """
        missing = error_response(404, "not_found", "There is no frame file for that key.")
        if not isinstance(key, str) or (not is_key(key) and FIXTURE_NAME.fullmatch(key) is None):
            return missing
        named = self.fixtures.get(key)
        if named is not None:
            return _frames_response(named.frames_gz, FIXTURE_ALIAS_CACHE_CONTROL)
        if not is_key(key):
            return missing
        copies = self._frame_copies(key)
        if version is not None:
            copies = [copy for copy in copies if version and frames_version(copy[0]) == version]
        return missing if not copies else _frames_response(copies[0][1], FRAMES_CACHE_CONTROL)

    def _cached_manifest(self, ra: float, dec: float, fov: int) -> Response | None:
        """HTTP 200 with the cached manifest of a request, carrying the request as it was made this time."""
        key = self.cache.lookup(ra, dec, fov)
        body = self.cache.get_manifest(key) if key is not None else None
        if body is None:
            return None
        document = json.loads(body)
        document["request"] = {"ra": ra, "dec": dec, "fov_arcmin": fov}
        return _json_bytes(json.dumps(document, separators=(",", ":")).encode("utf-8"))

    def field(self, ra: float, dec: float, fov: int, client: str) -> Response:
        """Contract section 7: the manifest (200), "building" (202), or an error."""
        cached = self._cached_manifest(ra, dec, fov)
        if cached is not None:
            return cached
        name = request_id(ra, dec, fov)
        job = self.builder.poll(name)
        if job is None:
            cached = self._cached_manifest(ra, dec, fov)  # the build may have finished a moment ago
            if cached is not None:
                return cached
            job = self._start(name, ra, dec, fov, client)
            if isinstance(job, Response):
                return job
        if job.state == "failed" and job.error is not None:
            status, code, message = job.error
            return error_response(status, code, message)
        progress = Progress(stage=job.stage, done=job.done, total=job.total)
        body = BuildingResponse(progress=progress, retry_after_s=POLL_AFTER_S).model_dump()
        headers = {"Cache-Control": NO_STORE, "Retry-After": str(POLL_AFTER_S)}
        return JSONResponse(body, status_code=202, headers=headers)

    def _start(self, name: str, ra: float, dec: float, fov: int, client: str) -> Job | Response:
        """Start a cold build for `client`, or say why not (429)."""
        full = error_response(
            429,
            "busy",
            "The build queue is full. Try again shortly.",
            {"Retry-After": str(RETRY_AFTER_QUEUE_S)},
        )
        if not self.builder.has_room():
            return full
        wait = self.limiter.take(client)
        if wait > 0.0:
            seconds = max(1, math.ceil(wait))
            message = f"Too many new fields were requested from this address. Try again in {seconds} s."
            return error_response(429, "busy", message, {"Retry-After": str(seconds)})
        return self.builder.start(name, ra, dec, fov) or full

    def status(self) -> Response:
        """Contract section 7.4. Never waits for an upstream."""
        seen = [self.cache.newest_mjd(), self.fixtures.newest_mjd()]
        newest = max((value for value in seen if value is not None), default=None)
        active, queued = self.builder.counts()
        body = StatusResponse(
            pipeline_version=__version__,
            newest_exposure=(
                None if newest is None else NewestExposure(mjd=round(newest, 5), date=mjd_to_date(newest))
            ),
            upstreams=self.probes.snapshot(),
            cache=CacheStatus(
                used_mb=round((self.cache.used_bytes() + self.cache.derived_bytes()) / MB),
                free_mb=round(self.cache.free_bytes() / MB),
            ),
            builds=BuildsStatus(active=active, queued=queued),
        )
        return JSONResponse(body.model_dump(), headers={"Cache-Control": NO_STORE})

    # ---------------------------------------------------------------- fields by key
    def field_ref(self, key: str) -> FieldRef | None:
        """The field a key names: a built field in the disk cache, a recorded field with that content key, or
        a recorded field by its name (as frames.bin accepts); None for anything else."""
        if not isinstance(key, str):
            return None
        if is_key(key):
            body = self.cache.get_manifest(key)
            if body is not None:
                return FieldRef(key, Manifest.model_validate_json(body), recorded=False)
            fixture = self.fixtures.by_key(key)
            if fixture is not None:
                return FieldRef(key, Manifest.model_validate_json(fixture.manifest), recorded=True)
            return None
        if FIXTURE_NAME.fullmatch(key) is None:
            return None
        fixture = self.fixtures.get(key)
        if fixture is None or not is_key(fixture.key):
            return None
        return FieldRef(fixture.key, Manifest.model_validate_json(fixture.manifest), recorded=True)

    # ---------------------------------------------------------------- overlays (Contract 7.3)
    def _cached_overlays(self, key: str) -> OverlaysResponse | None:
        packed = self.cache.get_derived(key, OVERLAYS_NAME)
        if packed is None:
            return None
        try:
            return OverlaysResponse.model_validate_json(gzip.decompress(packed))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _final(answer: OverlaysResponse) -> bool:
        """Both catalogues answered: the answer holds for the key for good (both are fixed releases)."""
        return answer.upstreams.gaia == "ok" and answer.upstreams.catwise == "ok"

    def overlays(self, field: FieldRef) -> OverlaysResponse:
        """The catalogue sources of a field: cached when final, else asked again (at most every 5 minutes)."""
        cached = self._cached_overlays(field.key)
        if cached is not None and self._final(cached):
            return cached

        def fetch() -> OverlaysResponse:
            held = self._cached_overlays(field.key)  # another request may have just fetched it
            tried = self._overlays_tried.get(field.key)
            recent = tried is not None and time.monotonic() - tried < OVERLAYS_RETRY_S
            if held is not None and (self._final(held) or recent):
                return held
            started = time.monotonic()
            answer = self._overlays_fn(field.manifest, previous=held)
            self._overlays_tried[field.key] = time.monotonic()
            states = answer.upstreams
            if states.gaia != "unavailable" or states.catwise != "unavailable":
                self.cache.put_derived(field.key, OVERLAYS_NAME, _pack(answer.model_dump_json().encode()))
            _log(
                "overlays",
                key=field.key,
                gaia=states.gaia,
                catwise=states.catwise,
                n_gaia=len(answer.gaia),
                n_catwise=len(answer.catwise),
                seconds=round(time.monotonic() - started, 3),
            )
            return answer

        return self._flights.run(f"overlays/{field.key}", fetch, catalogs.DEADLINE_S + 10.0)

    def overlays_response(self, key: str, request: Request) -> Response:
        field = self.field_ref(key)
        if field is None:
            return error_response(404, "not_found", "There is no field with that key.")
        try:
            answer = self.overlays(field)
        except FutureTimeout:
            return _still_asking()
        cache_control = FINAL_CACHE_CONTROL if self._final(answer) else NO_STORE
        return _json_gz_response(_pack(answer.model_dump_json().encode()), request, cache_control)

    # ---------------------------------------------------------------- spectrum (Contract 7.1)
    def field_exposures(self, field: FieldRef) -> list[Exposure]:
        """The exposures a spectrum of the field measures, limited to the field's visits.

        The list stored with a built field; otherwise (a recorded field, or a field built before the list was
        kept) the archive is searched again at the field centre and sampled as a build samples, and the list
        is stored. Raises http.UpstreamError when the archive cannot be searched.
        """
        packed = self.cache.get_derived(field.key, EXPOSURES_NAME)
        exposures: list[Exposure] | None = None
        if packed is not None:
            try:
                exposures = spectra.exposures_from_json(gzip.decompress(packed))
            except (OSError, ValueError):
                exposures = None
        if exposures is None:
            centre = field.manifest.centre
            found = self._discover_fn(
                centre.ra, centre.dec, deadline=http.Deadline(SPECTRUM_DISCOVER_DEADLINE_S)
            )
            exposures = sample_exposures(found, MAX_EXPOSURES)
            self.cache.put_derived(field.key, EXPOSURES_NAME, _pack(spectra.exposures_to_json(exposures)))
        return spectra.within_visits(exposures, field.manifest.time_bins)

    def _measure(self, field: FieldRef, choice: spectra.Choice, name: str) -> SpectrumResult:
        """Measure one spectrum (holding a slot) and keep it when it is complete."""
        if not self._spectrum_slots.acquire(blocking=False):
            raise Busy()
        try:
            started = time.monotonic()
            exposures = self.field_exposures(field)
            target = choice.target
            response, stats = self._measure_fn(
                exposures,
                target.ra,
                target.dec,
                epoch=target.epoch,
                pmra=target.pmra,
                pmdec=target.pmdec,
                parallax=target.parallax,
                snapped_to=choice.snapped_to,
                neighbours=choice.neighbours,
                time_bins=field.manifest.time_bins,
                deadline=http.Deadline(SPECTRUM_DEADLINE_S),
            )
            missing = stats.failed + stats.timed_out + stats.skipped.get(photometry.NO_PSF, 0)
            result = SpectrumResult(_pack(response.model_dump_json().encode()), missing, stats.requested)
            if result.complete:
                self.cache.put_derived(field.key, name, result.body_gz)
            _log(
                "spectrum",
                key=field.key,
                target=choice.identity,
                state=response.state,
                points=len(response.points),
                requested=stats.requested,
                read=stats.read,
                off_detector=stats.off_detector,
                failed=stats.failed,
                timed_out=stats.timed_out,
                skipped=stats.skipped,
                cached=result.complete,
                seconds=round(time.monotonic() - started, 3),
            )
            return result
        finally:
            self._spectrum_slots.release()

    def spectrum_response(self, key: str, params: Mapping[str, str], request: Request) -> Response:
        """Contract 7.1: the spectrum at a position inside the field (200), or an error in the contract shape."""
        field = self.field_ref(key)
        if field is None:
            return error_response(404, "not_found", "There is no field with that key.")
        try:
            ra = _number(params, "ra", 0.0, 360.0)
            dec = _number(params, "dec", -90.0, 90.0)
        except BadRequest as exc:
            return error_response(400, "bad_request", str(exc))
        if not spectra.inside_field(field.manifest, ra, dec):
            return error_response(400, "bad_request", "'ra' and 'dec' must lie inside the field.")
        try:
            overlays = self.overlays(field)
        except FutureTimeout:
            return _still_asking()
        if "unavailable" in (overlays.upstreams.gaia, overlays.upstreams.catwise):
            return error_response(503, "upstream_unavailable", CATALOGUES_DOWN_MESSAGE)
        choice = spectra.choose(overlays, field.manifest, ra, dec)
        name = spectra.cache_name(choice.identity)
        cached = self.cache.get_derived(field.key, name)
        if cached is not None:
            return _json_gz_response(_for_this_click(cached, choice.snapped_to), request, FINAL_CACHE_CONTROL)
        try:
            result = self._flights.run(
                f"spectrum/{field.key}/{name}",
                lambda: self._measure(field, choice, name),
                SPECTRUM_JOIN_WAIT_S,
            )
        except Busy:
            message = "Other spectra are being measured. Try again shortly."
            headers = {"Retry-After": str(RETRY_AFTER_SPECTRUM_S)}
            return error_response(429, "busy", message, headers)
        except FutureTimeout:
            message = "This spectrum is still being measured. Try again shortly."
            return error_response(429, "busy", message, {"Retry-After": str(RETRY_AFTER_SPECTRUM_S)})
        except http.UpstreamError as exc:
            log.warning("spectrum %s %s: upstream error: %s", field.key, choice.identity, exc)
            return error_response(503, "upstream_unavailable", SPECTRUM_UPSTREAM_MESSAGE)
        body_gz = _for_this_click(result.body_gz, choice.snapped_to)  # a joined request may differ
        if result.complete:
            return _json_gz_response(body_gz, request, FINAL_CACHE_CONTROL)
        note = f"{result.missing} of {result.requested} exposures not measured; not cached"
        return _json_gz_response(body_gz, request, NO_STORE, {INCOMPLETE_HEADER: note})


# ------------------------------------------------------------------------------------------------ app
def _not_built(what: str) -> JSONResponse:
    return error_response(404, "not_found", f"The {what} endpoint is not built yet.")


def create_app(
    settings: Settings | None = None,
    *,
    cache: FieldCache | None = None,
    build: BuildFn = build_field_for_service,
    probes: UpstreamProbes | None = None,
    overlays: OverlaysFn = catalogs.overlays_for_manifest,
    measure: MeasureFn = photometry.measure_with_stats,
    discover: DiscoverFn = discover,
) -> FastAPI:
    """The FastAPI application. The keyword arguments replace the disk cache, the build, the probes, the
    catalogue queries, the photometry and the archive search (see `Service`)."""
    configure_logging()
    sys.setswitchinterval(SWITCH_INTERVAL_S)
    settings = settings or Settings.from_env()
    service = Service(
        settings,
        cache=cache,
        build=build,
        probes=probes,
        overlays=overlays,
        measure=measure,
        discover=discover,
    )
    app = FastAPI(title="Tombaugh API", version=__version__, docs_url=None, redoc_url=None)
    app.state.service = service

    @app.middleware("http")
    async def guard_and_log(request: Request, call_next: Callable) -> Response:
        started = time.perf_counter()
        path = request.url.path
        under_api = path == "/api" or path.startswith("/api/")
        if under_api and not service.secret_ok(request):
            response: Response = error_response(403, "bad_request", "This API answers only through its site.")
        else:
            response = await call_next(request)
        if path != "/healthz":
            _log(
                "request",
                method=request.method,
                path=path,
                query=request.url.query,
                status=response.status_code,
                ms=round((time.perf_counter() - started) * 1000.0, 1),
            )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET"],
        allow_headers=["*"],
        expose_headers=["Retry-After"],
        max_age=600,
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _CODE_BY_STATUS.get(exc.status_code, "bad_request" if exc.status_code < 500 else "internal")
        message = "There is nothing at this address." if exc.status_code == 404 else str(exc.detail)
        return error_response(exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, __: RequestValidationError) -> JSONResponse:
        return error_response(400, "bad_request", "The request is not valid.")

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled %s: %s", type(exc).__name__, exc)
        return error_response(500, "internal", "The API failed unexpectedly.")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"contract": CONTRACT_VERSION, "status": "ok"}

    @app.get("/api/status")
    def status() -> Response:
        return service.status()

    @app.get("/api/fields")
    def fields(request: Request) -> Response:
        params = request.query_params
        if "fixture" in params:
            return service.fixture_manifest(params["fixture"])
        try:
            ra, dec, fov = parse_position(params)
        except BadRequest as exc:
            return error_response(400, "bad_request", str(exc))
        return service.field(ra, dec, fov, service.client_of(request))

    @app.get("/api/fields/{key}/frames.bin")
    def frames(key: str, v: str | None = None) -> Response:
        return service.frames(key, v)

    @app.get("/api/fields/{key}/spectrum")
    def spectrum(key: str, request: Request) -> Response:
        return service.spectrum_response(key, request.query_params, request)

    @app.get("/api/fields/{key}/overlays")
    def overlays_route(key: str, request: Request) -> Response:
        return service.overlays_response(key, request)

    @app.get("/api/resolve")
    def resolve() -> Response:
        return _not_built("resolve")

    return app


app = create_app()
