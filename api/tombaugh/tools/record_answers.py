"""Record the answers of /overlays and /spectrum for a recorded field (Contract v1.0, section 8).

    cd api && uv run python -m tombaugh.tools.record_answers wise0855
    cd api && uv run python -m tombaugh.tools.record_answers barnard

The recorded field ``cache/fixtures/<name>/`` (``manifest.json`` and ``frames.bin``, made by ``make_fixture``) is
read, never rebuilt or changed. Its two answers are asked of the service of ``tombaugh.main``, run in this
process (``create_app`` with the real catalogue queries, archive search and photometry, so that every upstream
request goes through ``tombaugh.http``), the way the page asks them, by the field's content key:

    GET /api/fields/<key>/overlays
    GET /api/fields/<key>/spectrum?ra=<request ra>&dec=<request dec>     the manifest's request position

Each final answer is written into an envelope, ``<out>/<name>/overlays.json`` or ``spectrum.json``: compact JSON
with one trailing newline, whose ``response`` is the route's body byte for byte:

    {"contract": "1.0", "kind": "recorded_answer", "route": "overlays" | "spectrum", "field": "<name>",
     "key": "<manifest key>", "pipeline_version": "<manifest provenance>", "recorded_at": "YYYY-MM-DDTHH:MM:SSZ",
     "request": {} | {"ra": <deg>, "dec": <deg>}, "response": <the body>}

Final means: HTTP 200, a body that the contract's model accepts and serialises back to the same bytes, and,
for overlays, both catalogues "ok"; for a spectrum, no ``X-Tombaugh-Incomplete`` header. Any other answer is
refused: its file is left as it was and the command exits 1. Nothing is asked when the running package is not
the pipeline version that made the field (its manifest's ``provenance.pipeline_version``): an answer of other
code is not that field's answer.

The disk cache is a new empty folder, removed afterwards, unless ``--cache`` names one, so that an answer comes
from the archives and catalogues, never from an earlier run. Nothing is fetched from an address given on the
command line: the field is named from a fixed list.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import logging
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from tombaugh import CONTRACT_VERSION, __version__
from tombaugh.cache import FieldCache, write_atomic
from tombaugh.main import INCOMPLETE_HEADER, Settings, configure_logging, create_app, default_fixtures_dir
from tombaugh.models import Manifest, OverlaysResponse, SpectrumResponse
from tombaugh.tools.make_fixture import TARGETS

KIND = "recorded_answer"
ROUTES = ("overlays", "spectrum")
MODELS: dict[str, type[OverlaysResponse | SpectrumResponse]] = {
    "overlays": OverlaysResponse,
    "spectrum": SpectrumResponse,
}
RESPONSE_JOIN = b',"response":'  # joins the envelope's other fields to the route's body
ASK_HEADERS = {"Accept-Encoding": "identity"}  # the body uncompressed, exactly as the route makes it


class RecordError(RuntimeError):
    """The field cannot be recorded at all (missing, unreadable, or of another pipeline version)."""


@dataclass
class Outcome:
    """What became of one route's answer: written to `path`, or `refused` with the reason."""

    route: str
    status: int
    seconds: float
    path: Path | None = None
    refused: str = ""
    details: dict = field(default_factory=dict)


def utc_now() -> str:
    """The current UTC time in the envelope's form, YYYY-MM-DDTHH:MM:SSZ."""
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def request_of(route: str, manifest: Manifest) -> dict[str, float]:
    """The envelope's `request`: none for overlays; for a spectrum, the manifest's request position (degrees)."""
    if route == "overlays":
        return {}
    return {"ra": manifest.request.ra, "dec": manifest.request.dec}


def envelope(route: str, name: str, manifest: Manifest, recorded_at: str, body: bytes) -> bytes:
    """The bytes of a recorded answer: the envelope's fields in their fixed order, then `body` as served."""
    head = {
        "contract": CONTRACT_VERSION,
        "kind": KIND,
        "route": route,
        "field": name,
        "key": manifest.key,
        "pipeline_version": manifest.provenance.pipeline_version,
        "recorded_at": recorded_at,
        "request": request_of(route, manifest),
    }
    text = json.dumps(head, separators=(",", ":"), ensure_ascii=False)
    return text[:-1].encode("utf-8") + RESPONSE_JOIN + body + b"}\n"


def refusal(route: str, status: int, headers: Mapping[str, str], body: bytes) -> str:
    """Why an answer is not final and must not be recorded; "" when it may be."""
    if status != 200:
        return f"HTTP {status}: {body[:300].decode('utf-8', 'replace')}"
    named = {name.lower(): value for name, value in headers.items()}
    if route == "spectrum" and INCOMPLETE_HEADER.lower() in named:
        return f"incomplete: {named[INCOMPLETE_HEADER.lower()]}"
    try:
        answer = MODELS[route].model_validate_json(body)
    except ValidationError as exc:
        return f"not a contract answer: {exc.error_count()} validation errors, first {exc.errors()[0]['msg']}"
    if answer.model_dump_json().encode("utf-8") != body:
        return "the body is not the contract model's own JSON (a key added, lost or written differently)"
    if isinstance(answer, OverlaysResponse):
        states = answer.upstreams
        if (states.gaia, states.catwise) != ("ok", "ok"):
            return f"not final: Gaia {states.gaia}, CatWISE {states.catwise}"
    return ""


def _details(answer: OverlaysResponse | SpectrumResponse) -> dict:
    if isinstance(answer, OverlaysResponse):
        return {
            "gaia": len(answer.gaia),
            "catwise": len(answer.catwise),
            "tracks": {
                "gaia": sum(1 for s in answer.gaia if s.track),
                "catwise": sum(1 for s in answer.catwise if s.track),
            },
        }
    snapped = answer.target.snapped_to
    return {
        "state": answer.state,
        "method": answer.method.kind,
        "snapped_to": snapped.model_dump() if snapped is not None else None,
        "points": len(answer.points),
        "binned": len(answer.binned),
    }


def load_manifest(fixtures_dir: Path, name: str) -> Manifest:
    """The manifest of the recorded field `name`. Raises RecordError when the field is not there whole."""
    folder = fixtures_dir / name
    if not (folder / "manifest.json").is_file() or not (folder / "frames.bin").is_file():
        raise RecordError(f"{folder} does not hold a recorded field (manifest.json and frames.bin)")
    try:
        return Manifest.model_validate_json((folder / "manifest.json").read_bytes())
    except (OSError, ValidationError) as exc:
        raise RecordError(f"{folder / 'manifest.json'} cannot be read: {exc}") from exc


def record(
    name: str,
    *,
    fixtures_dir: Path,
    out_dir: Path,
    cache_dir: Path,
    routes: Sequence[str] = ROUTES,
    **app_options: Callable,
) -> list[Outcome]:
    """Ask the service for the answers of the recorded field `name` and write each final one under `out_dir`.

    `fixtures_dir` holds the recorded fields; `cache_dir` is the service's disk cache. `app_options` go to
    `create_app` (tests pass stand-ins for the catalogues, the archive search and the photometry; by default
    the real ones answer). Raises RecordError when the field is missing or is not of this pipeline version.
    """
    from fastapi.testclient import TestClient  # needs httpx, a development dependency (uv sync), as the tests

    manifest = load_manifest(fixtures_dir, name)
    made_by = manifest.provenance.pipeline_version
    if made_by != __version__:
        raise RecordError(
            f"the field was made by pipeline {made_by} and this is {__version__}: record the field again "
            "(make_fixture) before its answers"
        )
    settings = Settings(fixtures_dir=fixtures_dir, probe_upstreams=False)
    app = create_app(settings, cache=FieldCache(cache_dir), **app_options)
    client = TestClient(app, raise_server_exceptions=False)
    outcomes: list[Outcome] = []
    for route in routes:
        request = request_of(route, manifest)
        params = {coordinate: repr(value) for coordinate, value in request.items()}
        started = time.monotonic()
        response = client.get(f"/api/fields/{manifest.key}/{route}", params=params, headers=ASK_HEADERS)
        recorded_at = utc_now()
        body = response.content
        outcome = Outcome(route, response.status_code, round(time.monotonic() - started, 1))
        outcome.refused = refusal(route, response.status_code, response.headers, body)
        if not outcome.refused:
            path = out_dir / name / f"{route}.json"
            write_atomic(path, envelope(route, name, manifest, recorded_at, body))
            outcome.path = path
            outcome.details = _details(MODELS[route].model_validate_json(body))
        outcomes.append(outcome)
    return outcomes


def _logs_to_stderr() -> None:
    """The service writes its JSON log lines to standard output; here they go to standard error, so that
    standard output holds only the summary."""
    configure_logging()
    for handler in logging.getLogger("tombaugh").handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setStream(sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Command line: record the answers of one recorded field and print a JSON summary."""
    parser = argparse.ArgumentParser(prog="python -m tombaugh.tools.record_answers", description=__doc__)
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.add_argument("name", choices=sorted(TARGETS))
    parser.add_argument(
        "--fixtures", type=Path, default=None, help="folder of the recorded fields (default: the service's)"
    )
    parser.add_argument("--out", type=Path, default=None, help="folder to write into (default: --fixtures)")
    parser.add_argument("--cache", type=Path, default=None, help="disk cache folder (default: a new one)")
    parser.add_argument("--only", choices=ROUTES, default=None, help="record this answer only")
    args = parser.parse_args(argv)
    _logs_to_stderr()
    fixtures_dir = args.fixtures or default_fixtures_dir()
    routes = (args.only,) if args.only else ROUTES
    try:
        with contextlib.ExitStack() as stack:
            cache_dir = args.cache or Path(
                stack.enter_context(tempfile.TemporaryDirectory(prefix="tombaugh-"))
            )
            outcomes = record(
                args.name,
                fixtures_dir=fixtures_dir,
                out_dir=args.out or fixtures_dir,
                cache_dir=cache_dir,
                routes=routes,
            )
    except RecordError as exc:
        print(f"record_answers {args.name}: {exc}", file=sys.stderr)
        return 1
    summary = [
        {
            "route": o.route,
            "status": o.status,
            "seconds": o.seconds,
            "written": str(o.path) if o.path else None,
            "refused": o.refused or None,
            **o.details,
        }
        for o in outcomes
    ]
    print(json.dumps({"field": args.name, "answers": summary}, indent=2))
    return 0 if all(o.path is not None for o in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
