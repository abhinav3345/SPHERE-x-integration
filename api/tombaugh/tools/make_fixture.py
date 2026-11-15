"""Record a real field as a fixture (Contract v1.0, section 8).

    cd api && uv run python -m tombaugh.tools.make_fixture wise0855
    cd api && uv run python -m tombaugh.tools.make_fixture barnard

Builds the field through the production pipeline (`tombaugh.build.build_field`, live archive, with the
older-survey planes of every band of `tombaugh.legacy.LEGACY_BANDS`, as the service builds) and writes
``cache/fixtures/<name>/manifest.json`` and ``frames.bin`` (uncompressed: the manifest's sha256 is over these
bytes); ``--out`` writes elsewhere. Nothing is hand-made, and nothing is written when the build or the
older surveys did not answer completely. The manifest gains ``fixture_stars``: three Gaia DR3 stars for
decoder and grid tests, chosen from the catalogue alone, never by looking at the pixels:

* inside the field, at least 10 output pixels from its edge;
* G magnitude from 12 to 15.5, and no source brighter than G = 10 within 60 arcsec;
* first choice: no other Gaia source within 20 arcsec, brightest first;
* where the sky does not offer three such stars, the list is completed, brightest first, with stars whose
  every Gaia neighbour within 20 arcsec is at least 3 magnitudes fainter in G (measured on 14 Nov 2026: the
  WISE 0855 field has two fully isolated stars in the magnitude range and the Barnard field, with 820 Gaia
  sources, has none);
* positions are moved to ``epoch_ref`` (2026.0) by proper motion.

Each field is centred where its object is at ``epoch_ref``, computed here from published astrometry by proper
motion alone (barycentric: the yearly parallax ellipse, under 0.6 arcsec for both objects, is left out).

Units: degrees (ICRS), mas/yr, Julian years, arcsec, output pixels of 3.075 arcsec.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import math
import sys
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time
from erfa import ErfaWarning

from tombaugh import http
from tombaugh.build import EPOCH_REF, BuildStats, build_field_with_stats
from tombaugh.cache import compress_frames, write_atomic
from tombaugh.grid import PIXSCALE_ARCSEC, Grid, sky_to_pixel, snap
from tombaugh.legacy import LEGACY_BANDS
from tombaugh.models import FixtureStar, Manifest

FOV_ARCMIN = 6
N_STARS = 3
G_MIN, G_MAX = 12.0, 15.5  # Gaia G magnitude range of a fixture star
ISOLATION_ARCSEC = 20.0  # no other Gaia source this close ...
ISOLATION_MIN_GAP_MAG = 3.0  # ... or, as second choice, none less than this many G magnitudes fainter
BRIGHT_G = 10.0  # a source brighter than this ...
BRIGHT_AVOID_ARCSEC = 60.0  # ... must be at least this far away
EDGE_MARGIN_PX = 10.0
GAIA_EPOCH = 2016.0  # reference epoch of Gaia DR3 positions, Julian year
QUERY_MARGIN_ARCSEC = 80.0  # catalogue search beyond the field corner: neighbours and fast movers
MAX_ROWS = 20000
DEADLINE_S = 300.0  # a fixture is recorded whole or not at all, so the build gets more time than the API
TAP_SERVICES = (
    ("https://gaia.ari.uni-heidelberg.de/tap/sync", "gaiadr3.gaia_source"),
    ("https://dc.g-vo.org/tap/sync", "gaia.dr3lite"),
)
TAP_TIMEOUT = (5.0, 60.0)
TAP_DEADLINE_S = 90.0


@dataclass(frozen=True)
class Target:
    """Published astrometry of the object a fixture is centred on."""

    label: str
    ra: float  # degrees at `epoch`
    dec: float
    epoch: float  # Julian year
    pmra: float  # mas/yr, includes cos(dec)
    pmdec: float  # mas/yr
    parallax: float  # mas (recorded for reference; not used for the field centre)
    source: str


TARGETS: dict[str, Target] = {
    # Astrometry used by science/prototypes/wise0855_common.py: SIMBAD, read on 14 Nov 2026, quoting
    # Kirkpatrick et al. 2021 (2021ApJS..253....7K); ICRS position at epoch J2000.
    "wise0855": Target(
        label="WISE J085510.83-071442.5",
        ra=15.0 * (8 + 55 / 60.0 + 16.53798 / 3600.0),
        dec=-(7 + 14 / 60.0 + 49.3728 / 3600.0),
        epoch=2000.0,
        pmra=-8123.7,
        pmdec=673.2,
        parallax=439.0,
        source="SIMBAD, quoting Kirkpatrick et al. 2021",
    ),
    "barnard": Target(
        label="Barnard's Star",
        ra=269.44850253,
        dec=4.73942005,
        epoch=2016.0,
        pmra=-801.551,
        pmdec=10362.394,
        parallax=546.976,
        source="Gaia DR3 4472832130942575872",
    ),
}


@dataclass(frozen=True)
class GaiaStar:
    """One Gaia DR3 source with its position moved to `epoch_ref`."""

    source_id: str
    ra: float  # degrees at epoch_ref
    dec: float
    g: float | None  # G magnitude; None when the catalogue has none


def default_out_dir() -> Path:
    """``cache/fixtures`` at the repository root, found relative to this package."""
    return Path(__file__).resolve().parents[3] / "cache" / "fixtures"


# ---------------------------------------------------------------------------------------- astrometry
def propagate(
    ra: float, dec: float, pmra: float, pmdec: float, epoch_from: float, epoch_to: float = EPOCH_REF
) -> tuple[float, float]:
    """Move a position by proper motion from one Julian year to another. Degrees in and out.

    `pmra` (already times cos dec) and `pmdec` are mas/yr. The motion follows a great circle
    (astropy `apply_space_motion`, as in the morning's prototype); parallax is not applied, so the result is
    the barycentric direction.
    """
    start = SkyCoord(
        ra * u.deg,
        dec * u.deg,
        pm_ra_cosdec=pmra * u.mas / u.yr,
        pm_dec=pmdec * u.mas / u.yr,
        obstime=Time(epoch_from, format="jyear"),
        frame="icrs",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ErfaWarning)  # "distance overridden": no distance is given on purpose
        moved = start.apply_space_motion(new_obstime=Time(epoch_to, format="jyear"))
    return float(moved.ra.deg), float(moved.dec.deg)


def target_centre(name: str) -> tuple[float, float]:
    """Where the named object is at `epoch_ref`, snapped to the contract's 4 decimals (degrees)."""
    target = TARGETS[name]
    return snap(*propagate(target.ra, target.dec, target.pmra, target.pmdec, target.epoch))


# --------------------------------------------------------------------------------------- Gaia catalogue
def _optional(text: str | None) -> float | None:
    try:
        value = float(text) if text not in (None, "") else math.nan
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def parse_gaia_csv(text: str) -> list[GaiaStar]:
    """Sources of a TAP CSV answer with columns source_id, ra, dec, pmra, pmdec, phot_g_mean_mag.

    Positions are moved from the Gaia DR3 epoch to `epoch_ref`; a source without a proper motion stays
    where the catalogue has it. Rows without a position are dropped.
    """
    stars: list[GaiaStar] = []
    for row in csv.DictReader(io.StringIO(text)):
        ra, dec = _optional(row.get("ra")), _optional(row.get("dec"))
        source_id = (row.get("source_id") or "").strip()
        if ra is None or dec is None or not source_id.isdigit():
            continue
        pmra, pmdec = _optional(row.get("pmra")), _optional(row.get("pmdec"))
        if pmra is not None and pmdec is not None:
            ra, dec = propagate(ra, dec, pmra, pmdec, GAIA_EPOCH)
        stars.append(GaiaStar(source_id=source_id, ra=ra, dec=dec, g=_optional(row.get("phot_g_mean_mag"))))
    return stars


def query_gaia(ra: float, dec: float, radius_deg: float) -> tuple[list[GaiaStar], str]:
    """Every Gaia DR3 source within `radius_deg` of a position: (sources at epoch_ref, service used).

    Asks the ARI Heidelberg TAP service and falls back to GAVO. Raises `http.UpstreamError` when both fail
    and RuntimeError when an answer is cut off at the row limit.
    """
    last_error: Exception | None = None
    for url, table in TAP_SERVICES:
        query = (
            f"SELECT source_id, ra, dec, pmra, pmdec, phot_g_mean_mag FROM {table} "
            f"WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.6f}, {dec:.6f}, {radius_deg:.6f}))"
        )
        params = {
            "REQUEST": "doQuery",
            "LANG": "ADQL",
            "FORMAT": "csv",
            "MAXREC": str(MAX_ROWS),
            "QUERY": query,
        }
        try:
            response = http.get(
                url, params=params, timeout=TAP_TIMEOUT, deadline=http.Deadline(TAP_DEADLINE_S)
            )
            stars = parse_gaia_csv(response.content.decode("utf-8", "replace"))
        except (http.UpstreamError, ValueError, csv.Error) as exc:
            last_error = exc
            continue
        if len(stars) >= MAX_ROWS:
            raise RuntimeError(f"the Gaia answer was cut off at {MAX_ROWS} rows")
        if stars:
            return stars, url
        last_error = http.UpstreamError(f"{url} returned no source", url=url)
    raise http.UpstreamError(f"no Gaia service answered: {last_error}")


def choose_fixture_stars(stars: Sequence[GaiaStar], grid: Grid, count: int = N_STARS) -> list[GaiaStar]:
    """The `count` fixture stars of a field, by the rules in this module's docstring.

    `stars` must hold every catalogue source in and around the field, at `epoch_ref`. Fully isolated stars
    come first, then stars with only much fainter neighbours, each group brightest first. Fewer than
    `count` are returned when the field does not have enough.
    """
    if not stars:
        return []
    xs, ys = sky_to_pixel(grid, [star.ra for star in stars], [star.dec for star in stars])
    limit = grid.n - 1 - EDGE_MARGIN_PX
    isolated: list[GaiaStar] = []
    nearly: list[GaiaStar] = []
    by_brightness = sorted(
        range(len(stars)), key=lambda i: (stars[i].g is None, stars[i].g, stars[i].source_id)
    )
    for i in by_brightness:
        g = stars[i].g
        if g is None or not G_MIN <= g <= G_MAX:
            continue
        if not (EDGE_MARGIN_PX <= xs[i] <= limit and EDGE_MARGIN_PX <= ys[i] <= limit):
            continue
        gap = neighbour_gap(i, stars, xs, ys)
        if gap == math.inf:
            isolated.append(stars[i])
        elif gap is not None and gap >= ISOLATION_MIN_GAP_MAG:
            nearly.append(stars[i])
    return (isolated + nearly)[:count]


def neighbour_gap(
    i: int, stars: Sequence[GaiaStar], xs: Sequence[float], ys: Sequence[float]
) -> float | None:
    """How isolated star `i` is, from the grid pixel positions `xs`, `ys` of all sources.

    Returns None when a source brighter than G = 10 lies within 60 arcsec; infinity when no other source
    lies within 20 arcsec; otherwise how many G magnitudes fainter than the star its brightest neighbour
    within 20 arcsec is (a neighbour without a magnitude counts as equally bright: 0).
    """
    gap = math.inf
    for j, other in enumerate(stars):
        if j == i:
            continue
        separation = math.hypot(xs[j] - xs[i], ys[j] - ys[i]) * PIXSCALE_ARCSEC
        if not math.isfinite(separation):
            continue
        if other.g is not None and other.g < BRIGHT_G and separation < BRIGHT_AVOID_ARCSEC:
            return None
        if separation < ISOLATION_ARCSEC:
            gap = min(gap, 0.0 if other.g is None else other.g - stars[i].g)
    return gap


def fixture_star_models(stars: Sequence[GaiaStar], grid: Grid) -> list[FixtureStar]:
    """The manifest entries of the chosen stars: position at epoch_ref and expected grid pixel (x, y)."""
    models: list[FixtureStar] = []
    for star in stars:
        ra, dec = round(star.ra, 7), round(star.dec, 7)
        x, y = sky_to_pixel(grid, ra, dec)
        models.append(FixtureStar(source_id=star.source_id, ra=ra, dec=dec, x=round(x, 3), y=round(y, 3)))
    return models


# ----------------------------------------------------------------------------------------------- record
def search_radius_deg(grid: Grid) -> float:
    """Catalogue search radius: the field corner plus a margin for neighbours and fast movers, degrees."""
    half_diagonal = (grid.n - 1) / 2.0 * grid.pixscale * math.sqrt(2.0)
    return (half_diagonal + QUERY_MARGIN_ARCSEC) / 3600.0


def record(name: str, out_dir: Path, deadline_s: float = DEADLINE_S) -> tuple[Manifest, bytes, BuildStats]:
    """Build the named field from the live archive and write its two fixture files under `out_dir`."""
    ra, dec = target_centre(name)
    grid = Grid.for_field(ra, dec, FOV_ARCMIN)
    catalogue, service = query_gaia(ra, dec, search_radius_deg(grid))
    stars = choose_fixture_stars(catalogue, grid)
    print(f"gaia: {len(catalogue)} sources from {service}, {len(stars)} chosen", file=sys.stderr)
    if len(stars) < N_STARS:
        raise RuntimeError(
            f"only {len(stars)} of {len(catalogue)} Gaia sources qualify as fixture stars: nothing was written"
        )
    manifest, frames, stats = build_field_with_stats(
        ra, dec, FOV_ARCMIN, deadline_s=deadline_s, legacy_bands=LEGACY_BANDS
    )
    if manifest.status != "ready" or stats.failed or stats.timed_out or stats.legacy_incomplete:
        raise RuntimeError(
            f"the build is not complete (status {manifest.status}, {stats.failed} failed downloads, "
            f"{stats.timed_out} not read in time, older surveys incomplete: {stats.legacy_incomplete}): "
            "nothing was written"
        )
    manifest.fixture_stars = fixture_star_models(stars, grid)
    folder = out_dir / name
    write_atomic(folder / "frames.bin", frames)
    text = json.dumps(manifest.model_dump(), indent=2, ensure_ascii=False) + "\n"
    write_atomic(folder / "manifest.json", text.encode("utf-8"))
    return manifest, frames, stats


def _summary(name: str, manifest: Manifest, frames: bytes, stats: BuildStats) -> dict:
    return {
        "fixture": name,
        "key": manifest.key,
        "centre": manifest.centre.model_dump(),
        "exposures": manifest.exposures.model_dump(),
        "seconds": {stage: round(value, 2) for stage, value in stats.seconds.items()},
        "http": stats.http,
        "planes": len(manifest.planes),
        "legacy_planes": [
            {"index": p.index, "mission": p.mission, "band": p.band, "dates": f"{p.date_start}..{p.date_end}"}
            for p in manifest.planes
            if p.kind == "legacy"
        ],
        "frames_bytes": len(frames),
        "frames_sha256": manifest.frames.sha256 if manifest.frames else None,
        "frames_gzip_bytes": len(compress_frames(frames)),
        "time_bins": [
            {
                "id": b.id,
                "dates": f"{b.date_start}..{b.date_end}",
                "n": b.n_exposures,
                "detectors": b.detectors,
            }
            for b in manifest.time_bins
        ],
        "warnings": manifest.warnings,
        "fixture_stars": [star.model_dump() for star in manifest.fixture_stars or []],
    }


def main(argv: list[str] | None = None) -> int:
    """Command line: record one named fixture and print a JSON summary of the build."""
    parser = argparse.ArgumentParser(prog="python -m tombaugh.tools.make_fixture", description=__doc__)
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.add_argument("name", choices=sorted(TARGETS))
    parser.add_argument("--out", type=Path, default=None, help="fixtures folder (default: cache/fixtures)")
    parser.add_argument("--deadline", type=float, default=DEADLINE_S, help="build deadline, seconds")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s"
    )
    try:
        manifest, frames, stats = record(args.name, args.out or default_out_dir(), args.deadline)
    except (RuntimeError, http.UpstreamError) as exc:
        print(f"make_fixture {args.name}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(_summary(args.name, manifest, frames, stats), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
