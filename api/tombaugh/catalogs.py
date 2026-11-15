"""Catalogue overlays of a field (Contract v1.0, section 7.3): Gaia DR3 and CatWISE2020 sources.

The body of ``GET /api/fields/{key}/overlays``: every catalogue source that falls on the field's grid at one
of its visits, with its catalogue astrometry and, for a source moving faster than 50 mas/yr, where it is at
the middle of every time bin (``track``). The server computes the track so that propagation has a single
implementation; the viewer only projects the positions with ``grid.ts``.

Catalogues (column names and units read from the services themselves on 14 Nov 2026, never from memory)
--------------------------------------------------------------------------------------------------------
* **Gaia DR3** from the TAP services of ``tombaugh.tools.make_fixture`` (ARI Heidelberg
  ``gaiadr3.gaia_source``, then GAVO ``gaia.dr3lite``), with the same ADQL cone, row limit and timeouts.
  Columns checked in both services' TAP_SCHEMA: ``source_id``; ``ra``, ``dec`` (deg; GAVO: "Barycentric
  Right Ascension in ICRS at epoch J2016.0"); ``pmra`` (mas/yr, "multiplied by cos(δ)"), ``pmdec``
  (mas/yr); ``parallax`` (mas); ``radial_velocity`` (km/s); ``phot_g_mean_mag`` (mag).
* **CatWISE2020** at IRSA, table ``catwise_2020``, through IRSA's catalogue search program interface (Gator,
  ``/cgi-bin/Gator/nph-query``, IPAC table answer). Columns from IRSA's TAP_SCHEMA and its column page
  https://irsa.ipac.caltech.edu/data/WISE/CatWISE/gator_docs/catwise_colDescriptions.html: ``source_name``
  ("source hexagesimal designation"); ``ra_pm``, ``dec_pm`` (deg, "at epoch MJD=57170 (2015.405) from psf
  model incl. motion"); ``pmra``, ``pmdec``, ``sigpmra``, ``sigpmdec`` (arcsec/yr, "apparent motion", with
  an "uncorrected systematic in CatWISE2020" of "typically ... 10 mas per year"); ``w1mpro_pm``,
  ``w2mpro_pm`` (mag, "profile-fit photometry including motion"). Measured on 14 Nov 2026: ``pmra``
  already includes cos(dec) (five stars near Dec +66.8 agree with Gaia's ``pmra`` to a median 7 mas/yr;
  divided by cos(dec) they would be 53 mas/yr off). The same evening IRSA's TAP service answered schema
  queries but returned HTTP 502 or timed out on every data query, and its cone search (SCS) has no column
  selection and timed out on a 6 arcmin field; Gator answered that field in 2.6 s.

Positions
---------
Gaia: the astrometric place for an observer at the Earth's centre at the middle of each time bin, with
proper motion, parallax and (where Gaia has one) radial velocity applied by ERFA ``pmpx`` (SOFA's
catalogue-to-astrometric step: rectilinear space motion, parallax from the observer's barycentric position,
no aberration and no light deflection). The Earth's barycentric position comes from astropy
``get_body_barycentric(..., ephemeris="builtin")``: ERFA ``epv00``, an analytical series built into the
library, so no ephemeris file is ever downloaded (the package also turns IERS auto-download off; time-scale
conversions use only the bundled leap-second table). SPHEREx orbits the Earth; its offset from the geocentre
is not modelled. A missing or negative parallax is treated as zero, a missing proper motion as zero.

CatWISE: the catalogue position at MJD 57170. A CatWISE motion is used (proper motion alone, moved to each
time bin; CatWISE's ``par_pm`` is a rough estimate and is not used) only when it passes every check of
``catwise_tracks``, because most fast CatWISE motions in our two recorded fields are not real (measured on
14 Nov 2026 against Gaia DR3): around Barnard's Star (G = 8.19) CatWISE lists 205 unmatched "movers" above
5 sigma out to 488 arcsec from the star, and 60 of 1194 Gaia-matched sources there have a 5-sigma CatWISE
motion that Gaia does not see; WISE 0855 is listed four times along its WISE-era trail (three entries land
within 1.2 px of it in 2025-2026, the fourth 15 to 17 px away). The checks are therefore strict, and a
CatWISE source that fails them keeps its catalogue position without a track. Our choices, set on these two
fields only: other fields are unverified.

Published astrometry wins over CatWISE's (``published_matches``). An object whose published astrometry the
package holds (``make_fixture.TARGETS`` other than Gaia DR3 entries: WISE 0855, from SIMBAD quoting
Kirkpatrick et al. 2021) is moved by that astrometry, parallax included, and never by its CatWISE motion:
measured on 14 Nov 2026 in the 4.4-5.0 micron stack of each of the four visits, CatWISE's motion put the
WISE 0855 marker 3.3 to 3.7 arcsec (1.0 to 1.2 px) off the object, about its whole six-month motion. Its
most significant CatWISE entry carries that track; its other entries (the object listed again, within
``PUBLISHED_MATCH_ARCSEC`` of it at the CatWISE epoch) are left out, because their catalogue positions of
MJD 57170 lie about 83 arcsec from where the object is in the 2025-26 frames. A CatWISE entry farther from
the published position (WISE 0855's fourth entry, J085507.45-071437.8, 11 arcsec off at MJD 57170, with a
motion that fails ``catwise_tracks``) is not recognised and stays at its catalogue position.

A source is kept when its position lies on the grid (pixel centres -0.5 to n - 0.5) at the middle of at least
one time bin; a field without time bins is tested at ``epoch_ref``. The catalogue search radius covers the
grid's corner plus the largest known proper motion over the years between the catalogue epoch and the
visits.

Units: degrees (ICRS), mas/yr, mas, Julian years, MJD (UTC), arcsec, magnitudes.
"""

from __future__ import annotations

import csv
import io
import logging
import math
import re
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import astropy.units as u
import erfa
import numpy as np
from astropy.coordinates import get_body_barycentric
from astropy.io import ascii as astropy_ascii
from astropy.time import Time

from tombaugh import http
from tombaugh.build import EPOCH_REF
from tombaugh.grid import NATIVE_PIXSCALE_ARCSEC, Grid, sky_to_pixel
from tombaugh.models import (
    CatwiseSource,
    GaiaSource,
    Manifest,
    OverlaysResponse,
    OverlayUpstreams,
    TimeBin,
    TrackPoint,
)
from tombaugh.tools.make_fixture import GAIA_EPOCH, MAX_ROWS, TAP_SERVICES, TAP_TIMEOUT, TARGETS, Target

# fmt: off
__all__ = [
    "CATWISE_EPOCH_MJD", "CATWISE_MIN_PM_SNR", "EPHEMERIS", "FAST_MAS_YR", "CatwiseRow", "GaiaRow",
    "astrometric_positions", "catwise_epoch_jyear", "catwise_pm_snr", "catwise_query_params",
    "catwise_sources", "catwise_tracks", "earth_barycentric_au", "field_grid", "gaia_query_params",
    "gaia_sources", "overlays_for_manifest", "parse_catwise_ipac", "parse_gaia_csv", "published_matches",
    "published_positions", "published_targets", "query_catwise", "query_gaia", "search_radius_deg",
]
# fmt: on

log = logging.getLogger(__name__)

FAST_MAS_YR = 50.0  # Contract v1.0 section 7.3: a track only for sources moving faster than this
EPHEMERIS = "builtin"  # astropy: ERFA epv00 and plan94, no file; any JPL kernel would be downloaded
GRID_EDGE_PX = 0.5  # a source is on the grid when its pixel coordinates lie within [-0.5, n - 0.5]
COORD_DECIMALS = 7  # 1e-7 deg = 0.36 mas
MAS_PER_ARCSEC = 1000.0
MAS_TO_RAD = math.pi / (180.0 * 3600.0 * MAS_PER_ARCSEC)

# The largest proper motion we allow for when sizing the catalogue search: Barnard's Star in Gaia DR3
# (make_fixture.TARGETS, source 4472832130942575872), 10.39 arcsec/yr. That no catalogued source moves faster
# is the literature's statement, not checked here (unverified).
MAX_PM_ARCSEC_YR = math.hypot(TARGETS["barnard"].pmra, TARGETS["barnard"].pmdec) / MAS_PER_ARCSEC
SEARCH_SLACK_ARCSEC = 2.0  # rounding slack on top of the corner and the motion

GAIA_COLUMNS = ("source_id", "ra", "dec", "pmra", "pmdec", "parallax", "radial_velocity", "phot_g_mean_mag")

CATWISE_URL = "https://irsa.ipac.caltech.edu/cgi-bin/Gator/nph-query"
CATWISE_TABLE = "catwise_2020"
CATWISE_COLUMNS = (
    "source_name", "ra_pm", "dec_pm", "pmra", "pmdec", "sigpmra", "sigpmdec", "w1mpro_pm", "w2mpro_pm",
)  # fmt: skip
CATWISE_EPOCH_MJD = 57170.0  # IRSA column description of ra_pm, dec_pm: "at epoch MJD=57170 (2015.405)"
CATWISE_PM_SYSTEMATIC_MAS_YR = 10.0  # IRSA CatWISE2020 page: "typically ... 10 mas per year in motion"
# The checks a CatWISE motion must pass before it moves a marker (``catwise_tracks``); our choices, measured on
# the two recorded fields on 14 Nov 2026 (see the module docstring):
CATWISE_MIN_PM_SNR = 30.0  # at 30 sigma the WISE 0855 field keeps only WISE 0855's own entries
CATWISE_GAIA_MATCH_ARCSEC = 3.0  # a source Gaia holds gets Gaia's track, never CatWISE's
CATWISE_BRIGHT_G = 10.0  # a Gaia star this bright in the answer: no CatWISE track in the field ...
# ... because around Barnard's Star (G = 8.19) spurious CatWISE motions above 30 sigma reach the field's edge
CATWISE_DUPLICATE_PX = 2.0  # tracks this close at every visit are one object listed twice: one track kept
# A CatWISE entry is an object whose published astrometry the package holds (``published_matches``) when, at
# the CatWISE epoch, it lies within this of the published position (3": as CatWISE is matched to Gaia) and
# its CatWISE motion differs from the published one by less than PUBLISHED_PM_TOLERANCE of the published
# motion, so that a background star the object passes is never taken for it; or when its CatWISE track stays
# within one native pixel (NATIVE_PIXSCALE_ARCSEC) of the object at every visit. Our choices. Measured on
# 14 Nov 2026 for WISE 0855's three entries above 30 sigma: 0.41 to 1.21" at MJD 57170, motions 207 to 377
# mas/yr (2.5 to 4.6 percent) from the published 8151 mas/yr.
PUBLISHED_MATCH_ARCSEC = CATWISE_GAIA_MATCH_ARCSEC
PUBLISHED_PM_TOLERANCE = 0.5
CATWISE_NAME = re.compile(r"J\d{6}\.\d{2}[+-]\d{6}\.\d")  # e.g. J085508.34-071439.2, as Gator returns it
CATWISE_TIMEOUT = (5.0, 30.0)
CATWISE_TRIES = 4

DEADLINE_S = 30.0  # both catalogues are asked at the same time; neither may take longer than this
_ROWS_RETRIEVED = re.compile(r"^\\RowsRetrieved\s*=\s*(\d+)", re.MULTILINE)


# ------------------------------------------------------------------------------------------------ rows
@dataclass(frozen=True)
class GaiaRow:
    """One Gaia DR3 source as the catalogue gives it, at its epoch J2016.0."""

    source_id: str
    ra: float  # degrees
    dec: float
    pmra: float | None  # mas/yr, includes cos(dec)
    pmdec: float | None  # mas/yr
    parallax: float | None  # mas
    radial_velocity: float | None  # km/s
    g: float | None  # G magnitude


@dataclass(frozen=True)
class CatwiseRow:
    """One CatWISE2020 source as the catalogue gives it, at MJD 57170; motions converted to mas/yr."""

    id: str  # source_name
    ra: float  # degrees (ra_pm)
    dec: float  # degrees (dec_pm)
    pmra: float | None  # mas/yr, includes cos(dec) (measured, see the module docstring)
    pmdec: float | None
    sig_pmra: float | None  # mas/yr
    sig_pmdec: float | None
    w1: float | None  # w1mpro_pm, mag
    w2: float | None  # w2mpro_pm, mag


def _number(text: object) -> float | None:
    """A finite float from a catalogue cell, or None for an empty, null or non-numeric cell."""
    try:
        value = float(str(text).strip()) if text not in (None, "") else math.nan
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _times(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


# --------------------------------------------------------------------------------------------- parsing
def parse_gaia_csv(text: str) -> list[GaiaRow]:
    """Gaia DR3 rows of a TAP CSV answer with the columns of ``GAIA_COLUMNS``.

    Rows without a position or with a source_id that is not a number are dropped. Raises ValueError when
    the answer is not such a table (an error page, for example).
    """
    reader = csv.DictReader(io.StringIO(text))
    header = [name.strip().lower() for name in reader.fieldnames or []]
    missing = [name for name in GAIA_COLUMNS if name not in header]
    if missing:
        raise ValueError(f"not a Gaia TAP table: no column {', '.join(missing)}")
    reader.fieldnames = header
    rows: list[GaiaRow] = []
    for row in reader:
        ra, dec = _number(row.get("ra")), _number(row.get("dec"))
        source_id = (row.get("source_id") or "").strip()
        if ra is None or dec is None or not source_id.isdigit() or not -90.0 <= dec <= 90.0:
            continue
        rows.append(
            GaiaRow(
                source_id=source_id,
                ra=ra % 360.0,
                dec=dec,
                pmra=_number(row.get("pmra")),
                pmdec=_number(row.get("pmdec")),
                parallax=_number(row.get("parallax")),
                radial_velocity=_number(row.get("radial_velocity")),
                g=_number(row.get("phot_g_mean_mag")),
            )
        )
    return rows


def parse_catwise_ipac(text: str) -> list[CatwiseRow]:
    """CatWISE2020 rows of a Gator IPAC-table answer with the columns of ``CATWISE_COLUMNS``.

    Motions are converted from arcsec/yr to mas/yr. Rows without a motion-fit position or with a name that is
    not a CatWISE designation are dropped. Raises ValueError when the answer is not such a table, or when
    it holds fewer rows than its ``\\RowsRetrieved`` line announces.
    """
    if not text.lstrip().startswith("\\"):
        raise ValueError(f"not an IPAC table: {text.strip()[:120]!r}")
    try:
        table = astropy_ascii.read(text, format="ipac", guess=False)
    except Exception as exc:  # astropy raises several types for a malformed table
        raise ValueError(f"unreadable IPAC table: {exc}") from exc
    missing = [name for name in CATWISE_COLUMNS if name not in table.colnames]
    if missing:
        raise ValueError(f"not a CatWISE answer: no column {', '.join(missing)}")
    announced = _ROWS_RETRIEVED.search(text)
    if announced is not None and int(announced.group(1)) != len(table):
        raise ValueError(f"the answer announces {announced.group(1)} rows and holds {len(table)}")
    columns: dict[str, list] = {}
    for name in CATWISE_COLUMNS:
        values = np.ma.asarray(table[name])  # a null cell is masked
        if name == "source_name":
            columns[name] = [str(v).strip() for v in np.ma.filled(values.astype(str), "")]
        else:
            columns[name] = list(np.ma.filled(values.astype(np.float64), np.nan))
    rows: list[CatwiseRow] = []
    for i, name in enumerate(columns["source_name"]):
        ra, dec = _number(columns["ra_pm"][i]), _number(columns["dec_pm"][i])
        if ra is None or dec is None or CATWISE_NAME.fullmatch(name) is None or not -90.0 <= dec <= 90.0:
            continue
        rows.append(
            CatwiseRow(
                id=name,
                ra=ra % 360.0,
                dec=dec,
                pmra=_times(_number(columns["pmra"][i]), MAS_PER_ARCSEC),
                pmdec=_times(_number(columns["pmdec"][i]), MAS_PER_ARCSEC),
                sig_pmra=_times(_number(columns["sigpmra"][i]), MAS_PER_ARCSEC),
                sig_pmdec=_times(_number(columns["sigpmdec"][i]), MAS_PER_ARCSEC),
                w1=_number(columns["w1mpro_pm"][i]),
                w2=_number(columns["w2mpro_pm"][i]),
            )
        )
    return rows


# --------------------------------------------------------------------------------------------- queries
def _check_cone(ra: float, dec: float, radius_deg: float) -> None:
    if not (math.isfinite(ra) and math.isfinite(dec) and 0.0 <= ra <= 360.0 and -90.0 <= dec <= 90.0):
        raise ValueError(f"position out of range: ra={ra!r}, dec={dec!r}")
    if not (math.isfinite(radius_deg) and 0.0 < radius_deg <= 1.0):
        raise ValueError(f"radius_deg must be within (0, 1], got {radius_deg!r}")


def gaia_query_params(table: str, ra: float, dec: float, radius_deg: float) -> dict[str, str]:
    """TAP parameters of the Gaia cone: the query of ``make_fixture.query_gaia`` with more columns."""
    _check_cone(ra, dec, radius_deg)
    query = (
        f"SELECT {', '.join(GAIA_COLUMNS)} FROM {table} "
        f"WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.6f}, {dec:.6f}, {radius_deg:.6f}))"
    )
    return {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "MAXREC": str(MAX_ROWS), "QUERY": query}


def catwise_query_params(ra: float, dec: float, radius_deg: float) -> dict[str, str]:
    """Gator parameters of the CatWISE2020 cone (IPAC table answer, only the columns used)."""
    _check_cone(ra, dec, radius_deg)
    return {
        "catalog": CATWISE_TABLE,
        "spatial": "cone",
        "objstr": f"{ra:.6f} {dec:.6f}",
        "radius": f"{radius_deg * 3600.0:.2f}",
        "radunits": "arcsec",
        "outfmt": "1",  # IPAC table
        "selcols": ",".join(CATWISE_COLUMNS),
    }


def query_gaia(
    ra: float, dec: float, radius_deg: float, deadline: http.Deadline
) -> tuple[list[GaiaRow], str]:
    """Every Gaia DR3 source within ``radius_deg`` of a position: (rows at J2016.0, service URL).

    The services and tables of ``make_fixture.TAP_SERVICES``, ARI first, GAVO second. Raises
    ``http.UpstreamError`` when neither answers with a readable table, and when an answer reaches the row
    limit (a cut list is never served as a whole one). An empty table is a normal answer.
    """
    _check_cone(ra, dec, radius_deg)
    last_error: Exception | None = None
    for url, table in TAP_SERVICES:
        params = gaia_query_params(table, ra, dec, radius_deg)
        try:
            response = http.get(url, params=params, timeout=TAP_TIMEOUT, deadline=deadline)
            rows = parse_gaia_csv(response.content.decode("utf-8", "replace"))
        except http.DeadlineExceeded:
            raise
        except (http.UpstreamError, ValueError, csv.Error) as exc:
            last_error = exc
            continue
        if len(rows) >= MAX_ROWS:
            raise http.UpstreamError(f"the Gaia answer reached the {MAX_ROWS}-row limit", url=url)
        return rows, url
    raise http.UpstreamError(f"no Gaia service answered: {last_error}")


def query_catwise(
    ra: float, dec: float, radius_deg: float, deadline: http.Deadline
) -> tuple[list[CatwiseRow], str]:
    """Every CatWISE2020 source within ``radius_deg`` of a position: (rows at MJD 57170, service URL).

    One Gator request to IRSA (at most two IRSA requests are in flight process-wide, ``tombaugh.http``).
    The cone is on the catalogue's ``ra``, ``dec``. Raises ``http.UpstreamError`` when IRSA does not answer
    with a readable table.
    """
    params = catwise_query_params(ra, dec, radius_deg)
    response = http.get(
        CATWISE_URL, params=params, timeout=CATWISE_TIMEOUT, tries=CATWISE_TRIES, deadline=deadline
    )
    try:
        rows = parse_catwise_ipac(response.content.decode("utf-8", "replace"))
    except ValueError as exc:
        raise http.UpstreamError(f"unreadable CatWISE answer: {exc}", url=CATWISE_URL, status=200) from exc
    return rows, CATWISE_URL


# ------------------------------------------------------------------------------------------ astrometry
def earth_barycentric_au(times: Time) -> np.ndarray:
    """Barycentric position of the Earth's centre at ``times``, au, shape (n, 3), from ERFA epv00."""
    earth = get_body_barycentric("earth", times, ephemeris=EPHEMERIS)
    return np.atleast_2d(earth.xyz.to_value(u.au).T).reshape(-1, 3)


def _years_tdb(times: Time, epoch: Time) -> np.ndarray:
    """Julian years (365.25 days of TDB) from ``epoch`` to each of ``times``."""
    later, start = times.tdb, epoch.tdb
    days = (later.jd1 - start.jd1) + (later.jd2 - start.jd2)
    return np.atleast_1d(np.asarray(days, dtype=np.float64)) / 365.25


def astrometric_positions(
    ra: Sequence[float] | np.ndarray,
    dec: Sequence[float] | np.ndarray,
    pmra: Sequence[float | None] | np.ndarray,
    pmdec: Sequence[float | None] | np.ndarray,
    parallax: Sequence[float | None] | np.ndarray,
    radial_velocity: Sequence[float | None] | np.ndarray,
    epoch: Time,
    times: Time,
) -> tuple[np.ndarray, np.ndarray]:
    """Where catalogue sources appear from the Earth's centre at ``times``: (ra, dec), degrees, shape (n, t).

    ``ra``, ``dec`` in degrees at ``epoch``; ``pmra`` (includes cos dec) and ``pmdec`` in mas/yr;
    ``parallax`` in mas; ``radial_velocity`` in km/s. None or NaN counts as zero, and so does a negative
    parallax. ERFA ``pmpx`` applies space motion and parallax (see the module docstring); the observer is the
    Earth's centre from ERFA ``epv00``.
    """

    def column(values) -> np.ndarray:
        array = np.array([np.nan if v is None else v for v in values], dtype=np.float64)
        return np.where(np.isfinite(array), array, 0.0)

    ra_rad = np.radians(np.asarray(ra, dtype=np.float64))[:, None]
    dec_rad = np.radians(np.asarray(dec, dtype=np.float64))[:, None]
    cos_dec = np.cos(dec_rad)
    safe_cos = np.where(np.abs(cos_dec) > 1e-12, cos_dec, 1e-12)
    pr = column(pmra)[:, None] * MAS_TO_RAD / safe_cos  # ERFA wants dRA/dt, not cos(dec) dRA/dt
    pd = column(pmdec)[:, None] * MAS_TO_RAD
    px = np.maximum(column(parallax), 0.0)[:, None] / MAS_PER_ARCSEC  # arcsec
    rv = column(radial_velocity)[:, None]
    times = times.reshape(-1) if times.shape else times.reshape((1,))
    years = _years_tdb(times, epoch)[None, :]
    observer = earth_barycentric_au(times)[None, :, :]
    direction = erfa.pmpx(ra_rad, dec_rad, pr, pd, px, rv, years, observer)
    theta, phi = erfa.c2s(direction)
    return np.degrees(erfa.anp(theta)), np.degrees(phi)


# ------------------------------------------------------------------------------------------- the field
def field_grid(manifest: Manifest) -> Grid:
    """The in-process grid of a manifest (centre, size and scale as recorded)."""
    return Grid(manifest.centre.ra, manifest.centre.dec, manifest.grid.nx, manifest.grid.pixscale_arcsec)


def _visit_times(time_bins: Sequence[TimeBin]) -> tuple[list[int], Time]:
    """(time-bin ids, their mid times); with no time bin, no id and the single time ``epoch_ref``."""
    if not time_bins:
        return [], Time([EPOCH_REF], format="jyear", scale="tt")
    return [b.id for b in time_bins], Time([b.mjd_mid for b in time_bins], format="mjd", scale="utc")


def search_radius_deg(grid: Grid, time_bins: Sequence[TimeBin], catalogue_epoch_jyear: float) -> float:
    """Catalogue search radius around the grid centre, degrees.

    The distance from the centre to the outer corner of the grid's corner pixel, plus the path of the
    fastest known star (``MAX_PM_ARCSEC_YR``) over the years between the catalogue epoch and the farthest
    visit, plus a small slack.
    """
    _, times = _visit_times(time_bins)
    years = float(np.max(np.abs(times.tt.jyear - catalogue_epoch_jyear)))
    corner = grid.n / 2.0 * grid.pixscale * math.sqrt(2.0)
    return (corner + MAX_PM_ARCSEC_YR * years + SEARCH_SLACK_ARCSEC) / 3600.0


def _on_grid(grid: Grid, ra: np.ndarray, dec: np.ndarray) -> np.ndarray:
    """(n, t) booleans: the position lies on the grid."""
    x, y = sky_to_pixel(grid, ra, dec)
    x, y = np.asarray(x), np.asarray(y)
    low, high = -GRID_EDGE_PX, grid.n - 1 + GRID_EDGE_PX
    with np.errstate(invalid="ignore"):
        return (x >= low) & (x <= high) & (y >= low) & (y <= high)


def _round(value: float | None, decimals: int) -> float | None:
    return None if value is None else round(float(value), decimals)


def _track(ids: Sequence[int], ra: np.ndarray, dec: np.ndarray) -> list[TrackPoint]:
    return [
        TrackPoint(time_bin=tb, ra=round(float(r), COORD_DECIMALS), dec=round(float(d), COORD_DECIMALS))
        for tb, r, d in zip(ids, ra, dec, strict=True)
    ]


def _moves_fast(pmra: float | None, pmdec: float | None) -> bool:
    return pmra is not None and pmdec is not None and math.hypot(pmra, pmdec) > FAST_MAS_YR


def gaia_sources(rows: Sequence[GaiaRow], grid: Grid, time_bins: Sequence[TimeBin]) -> list[GaiaSource]:
    """The Gaia sources on the grid at one visit at least, brightest first.

    Each keeps its catalogue astrometry at J2016.0; one faster than 50 mas/yr gets a ``track`` (proper motion
    and parallax applied, one point per time bin).
    """
    if not rows:
        return []
    ids, times = _visit_times(time_bins)
    epoch = Time(GAIA_EPOCH, format="jyear", scale="tcb")  # Gaia DR3 reference epoch J2016.0 (TCB)
    ra, dec = astrometric_positions(
        [r.ra for r in rows],
        [r.dec for r in rows],
        [r.pmra for r in rows],
        [r.pmdec for r in rows],
        [r.parallax for r in rows],
        [r.radial_velocity for r in rows],
        epoch,
        times,
    )
    keep = _on_grid(grid, ra, dec).any(axis=1)
    sources: list[GaiaSource] = []
    for i in np.flatnonzero(keep):
        row = rows[i]
        track = _track(ids, ra[i], dec[i]) if ids and _moves_fast(row.pmra, row.pmdec) else None
        sources.append(
            GaiaSource(
                source_id=row.source_id,
                ra=round(row.ra, COORD_DECIMALS),
                dec=round(row.dec, COORD_DECIMALS),
                epoch=GAIA_EPOCH,
                pmra=_round(row.pmra, 3),
                pmdec=_round(row.pmdec, 3),
                parallax=_round(row.parallax, 3),
                g=_round(row.g, 3),
                track=track,
            )
        )
    sources.sort(key=lambda s: (s.g is None, s.g if s.g is not None else 0.0, s.source_id))
    return sources


def catwise_epoch_jyear() -> float:
    """The CatWISE2020 reference epoch, MJD 57170, as a Julian year (TT; the time scale is not stated)."""
    return float(Time(CATWISE_EPOCH_MJD, format="mjd", scale="tt").jyear)


def catwise_pm_snr(row: CatwiseRow) -> float | None:
    """Total CatWISE motion over its uncertainty, the IRSA-stated 10 mas/yr systematic added in quadrature.

    None when the catalogue gives no motion or no uncertainty.
    """
    if None in (row.pmra, row.pmdec, row.sig_pmra, row.sig_pmdec):
        return None
    total = math.hypot(row.pmra, row.pmdec)
    if total <= 0.0:
        return 0.0
    sigma_ra = math.hypot(row.sig_pmra, CATWISE_PM_SYSTEMATIC_MAS_YR)
    sigma_dec = math.hypot(row.sig_pmdec, CATWISE_PM_SYSTEMATIC_MAS_YR)
    return total / (math.hypot(row.pmra * sigma_ra, row.pmdec * sigma_dec) / total)


def _catwise_moved(rows: Sequence[CatwiseRow], times: Time) -> tuple[np.ndarray, np.ndarray]:
    """(ra, dec) of CatWISE rows at ``times`` by proper motion alone, degrees, shape (n, t)."""
    return astrometric_positions(
        [r.ra for r in rows],
        [r.dec for r in rows],
        [r.pmra for r in rows],
        [r.pmdec for r in rows],
        [None] * len(rows),
        [None] * len(rows),
        Time(catwise_epoch_jyear(), format="jyear", scale="tt"),
        times,
    )


def catwise_tracks(
    rows: Sequence[CatwiseRow],
    grid: Grid,
    time_bins: Sequence[TimeBin],
    gaia_rows: Sequence[GaiaRow] | None,
) -> np.ndarray:
    """Which CatWISE rows get a track (booleans, one per row). A row gets one only when all of these hold:

    * the field has time bins, and the Gaia answer is at hand to check against (``gaia_rows`` not None);
    * that answer holds no star brighter than G = ``CATWISE_BRIGHT_G``;
    * the motion is faster than 50 mas/yr and at least ``CATWISE_MIN_PM_SNR`` times its uncertainty;
    * no Gaia source lies within ``CATWISE_GAIA_MATCH_ARCSEC`` of it at the CatWISE epoch;
    * no more significant CatWISE track lies within ``CATWISE_DUPLICATE_PX`` of it at every time bin.
    """
    wanted = np.zeros(len(rows), dtype=bool)
    if not rows or not time_bins or gaia_rows is None:
        return wanted
    if any(g.g is not None and g.g < CATWISE_BRIGHT_G for g in gaia_rows):
        return wanted
    snr = [catwise_pm_snr(r) for r in rows]
    candidates = [
        i
        for i, r in enumerate(rows)
        if snr[i] is not None and snr[i] >= CATWISE_MIN_PM_SNR and _moves_fast(r.pmra, r.pmdec)
    ]
    if not candidates:
        return wanted
    if gaia_rows:
        epoch = Time([catwise_epoch_jyear()], format="jyear", scale="tt")
        g_ra, g_dec = astrometric_positions(
            [g.ra for g in gaia_rows],
            [g.dec for g in gaia_rows],
            [g.pmra for g in gaia_rows],
            [g.pmdec for g in gaia_rows],
            [g.parallax for g in gaia_rows],
            [g.radial_velocity for g in gaia_rows],
            Time(GAIA_EPOCH, format="jyear", scale="tcb"),
            epoch,
        )
        g_ra, g_dec = np.radians(g_ra[:, 0]), np.radians(g_dec[:, 0])
        unmatched = []
        for i in candidates:
            ra, dec = math.radians(rows[i].ra), math.radians(rows[i].dec)
            cos_sep = np.sin(dec) * np.sin(g_dec) + np.cos(dec) * np.cos(g_dec) * np.cos(g_ra - ra)
            separation = np.degrees(np.arccos(np.clip(cos_sep, -1.0, 1.0))) * 3600.0
            if not (separation < CATWISE_GAIA_MATCH_ARCSEC).any():
                unmatched.append(i)
        candidates = unmatched
    if not candidates:
        return wanted
    _, times = _visit_times(time_bins)
    ra, dec = _catwise_moved([rows[i] for i in candidates], times)
    x, y = (np.asarray(v) for v in sky_to_pixel(grid, ra, dec))
    kept: list[int] = []  # positions in `candidates`
    for k in sorted(range(len(candidates)), key=lambda k: -snr[candidates[k]]):
        if any((np.hypot(x[k] - x[j], y[k] - y[j]) < CATWISE_DUPLICATE_PX).all() for j in kept):
            continue
        kept.append(k)
    wanted[[candidates[k] for k in kept]] = True
    return wanted


def published_targets() -> list[Target]:
    """Objects whose published astrometry the package holds (``make_fixture.TARGETS``), Gaia DR3 entries left
    out: the Gaia list already moves those by their own Gaia astrometry."""
    return [target for target in TARGETS.values() if not target.source.startswith("Gaia DR3")]


def published_positions(
    target: Target, times: Time, *, parallax: bool = True
) -> tuple[np.ndarray, np.ndarray]:
    """(ra, dec) of a published target at ``times``, degrees, shape (t,): proper motion and, unless
    ``parallax`` is False, parallax from the Earth's centre (``astrometric_positions``; the epoch is a Julian
    year, its time scale taken as TT: a minute's difference moves WISE 0855 by 0.0002")."""
    ra, dec = astrometric_positions(
        [target.ra],
        [target.dec],
        [target.pmra],
        [target.pmdec],
        [target.parallax if parallax else None],
        [None],
        Time(target.epoch, format="jyear", scale="tt"),
        times,
    )
    return ra[0], dec[0]


def _arcsec_between(ra1: float, dec1: float, ra2: np.ndarray, dec2: np.ndarray) -> np.ndarray:
    """Angles from one position to many (degrees in), arcsec; the haversine form."""
    p1, p2 = math.radians(dec1), np.radians(dec2)
    a = np.sin((p2 - p1) / 2.0) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(np.radians(ra2 - ra1) / 2.0) ** 2
    return np.degrees(2.0 * np.arcsin(np.minimum(1.0, np.sqrt(a)))) * 3600.0


def published_matches(
    rows: Sequence[CatwiseRow], time_bins: Sequence[TimeBin], tracked: np.ndarray | None = None
) -> dict[int, Target]:
    """CatWISE rows that are an object of ``published_targets``: {row index: target}.

    A row matches when, at the CatWISE epoch, it lies within ``PUBLISHED_MATCH_ARCSEC`` of the target's
    published position (proper motion alone, as CatWISE fits no parallax) and its CatWISE motion is within
    ``PUBLISHED_PM_TOLERANCE`` of the published motion (any motion when the target moves slower than
    ``FAST_MAS_YR``); or when ``tracked`` (booleans from ``catwise_tracks``) gives it a CatWISE track that stays
    within one native pixel of the target at every visit.
    """
    targets = published_targets()
    found: dict[int, Target] = {}
    if not rows or not targets:
        return found
    epoch = Time([catwise_epoch_jyear()], format="jyear", scale="tt")
    ids, times = _visit_times(time_bins)
    ra = np.array([r.ra for r in rows], dtype=np.float64)
    dec = np.array([r.dec for r in rows], dtype=np.float64)
    for target in targets:
        t_ra, t_dec = published_positions(target, epoch, parallax=False)
        close = _arcsec_between(float(t_ra[0]), float(t_dec[0]), ra, dec) < PUBLISHED_MATCH_ARCSEC
        published_pm = math.hypot(target.pmra, target.pmdec)
        for i in np.flatnonzero(close):
            row = rows[i]
            agrees = (
                published_pm <= FAST_MAS_YR
                or row.pmra is not None
                and row.pmdec is not None
                and math.hypot(row.pmra - target.pmra, row.pmdec - target.pmdec)
                < PUBLISHED_PM_TOLERANCE * published_pm
            )
            if agrees:
                found[int(i)] = target
        if tracked is None or not ids or not tracked.any():
            continue
        candidates = [int(i) for i in np.flatnonzero(tracked) if int(i) not in found]
        if not candidates:
            continue
        v_ra, v_dec = published_positions(target, times)
        c_ra, c_dec = _catwise_moved([rows[i] for i in candidates], times)
        for k, i in enumerate(candidates):
            apart = [_arcsec_between(v_ra[j], v_dec[j], c_ra[k, j], c_dec[k, j]) for j in range(len(ids))]
            if max(float(value) for value in apart) <= NATIVE_PIXSCALE_ARCSEC:
                found[i] = target
    return found


def catwise_sources(
    rows: Sequence[CatwiseRow],
    grid: Grid,
    time_bins: Sequence[TimeBin],
    gaia_rows: Sequence[GaiaRow] | None = None,
) -> list[CatwiseSource]:
    """The CatWISE sources on the grid at one visit at least, brightest in W2 first.

    An object whose published astrometry the package holds (``published_matches``) keeps one entry, its most
    significant in motion, placed at each time bin by the published astrometry (parallax included) with a
    ``track``; its other entries are left out. Any other source that passes ``catwise_tracks`` (which needs the
    Gaia answer, ``gaia_rows``) is placed at each time bin by its CatWISE proper motion alone and gets a
    ``track``; every other source stays at its catalogue position.
    """
    if not rows:
        return []
    ids, times = _visit_times(time_bins)
    epoch_jyear = catwise_epoch_jyear()
    moving = catwise_tracks(rows, grid, time_bins, gaia_rows)
    matches = published_matches(rows, time_bins, moving)
    n_times = len(times)
    ra = np.repeat(np.array([[r.ra] for r in rows], dtype=np.float64), n_times, axis=1)
    dec = np.repeat(np.array([[r.dec] for r in rows], dtype=np.float64), n_times, axis=1)
    moving[list(matches)] = False  # never moved by a CatWISE motion
    if moving.any():
        ra[moving], dec[moving] = _catwise_moved([rows[i] for i in np.flatnonzero(moving)], times)
    published = np.zeros(len(rows), dtype=bool)
    left_out = np.zeros(len(rows), dtype=bool)
    for target in dict.fromkeys(matches.values()):
        entries = sorted(
            (i for i, t in matches.items() if t == target),
            key=lambda i: (-(catwise_pm_snr(rows[i]) or 0.0), rows[i].id),
        )
        first, others = entries[0], entries[1:]
        ra[first], dec[first] = published_positions(target, times)
        published[first] = True
        left_out[others] = True
        log.info(
            "overlays: CatWISE %s placed by the published astrometry of %s; %d other entries of it left out",
            rows[first].id,
            target.label,
            len(others),
        )
    keep = _on_grid(grid, ra, dec).any(axis=1) & ~left_out
    sources: list[CatwiseSource] = []
    for i in np.flatnonzero(keep):
        row = rows[i]
        track = _track(ids, ra[i], dec[i]) if ids and (moving[i] or published[i]) else None
        sources.append(
            CatwiseSource(
                id=row.id,
                ra=round(row.ra, COORD_DECIMALS),
                dec=round(row.dec, COORD_DECIMALS),
                epoch=round(epoch_jyear, 4),
                pmra=_round(row.pmra, 2),
                pmdec=_round(row.pmdec, 2),
                w1=_round(row.w1, 3),
                w2=_round(row.w2, 3),
                track=track,
            )
        )
    sources.sort(key=lambda s: (s.w2 is None, s.w2 if s.w2 is not None else 0.0, s.id))
    return sources


# ---------------------------------------------------------------------------------------------- answer
GaiaQuery = Callable[[float, float, float, http.Deadline], tuple[list[GaiaRow], str]]
CatwiseQuery = Callable[[float, float, float, http.Deadline], tuple[list[CatwiseRow], str]]


def _timed(label: str, call: Callable[[], tuple[list, str]]) -> tuple[list | None, str]:
    """Run one catalogue query: (rows, "") or (None, the reason it failed). Logs the time it took."""
    started = time.monotonic()
    try:
        rows, service = call()
    except (http.UpstreamError, ValueError) as exc:
        seconds = time.monotonic() - started
        log.warning("overlays: %s unavailable after %.2f s: %s", label, seconds, exc)
        return None, f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # a fault here must not take the other catalogue down with it
        log.exception("overlays: %s failed unexpectedly", label)
        return None, f"{type(exc).__name__}: {exc}"
    log.info(
        "overlays: %s answered %d rows from %s in %.2f s",
        label,
        len(rows),
        service,
        time.monotonic() - started,
    )
    return rows, ""


def overlays_for_manifest(
    manifest: Manifest,
    *,
    previous: OverlaysResponse | None = None,
    deadline_s: float = DEADLINE_S,
    gaia_query: GaiaQuery = query_gaia,
    catwise_query: CatwiseQuery = query_catwise,
) -> OverlaysResponse:
    """Contract section 7.3: the Gaia DR3 and CatWISE2020 sources of a field.

    Both catalogues are asked at the same time, within ``deadline_s`` seconds. When one cannot be reached
    the other is still returned: the missing one is an empty list marked "unavailable", or, when
    ``previous`` (an earlier answer for the SAME field key) holds a list for it, that list marked "stale".
    Never raises for an upstream failure.
    """
    grid = field_grid(manifest)
    bins = list(manifest.time_bins)
    deadline = http.Deadline(deadline_s)
    centre = (grid.ra0, grid.dec0)
    gaia_radius = search_radius_deg(grid, bins, GAIA_EPOCH)
    catwise_radius = search_radius_deg(grid, bins, catwise_epoch_jyear())
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="tombaugh-overlays") as pool:
        gaia_job = pool.submit(_timed, "gaia", lambda: gaia_query(*centre, gaia_radius, deadline))
        catwise_job = pool.submit(_timed, "catwise", lambda: catwise_query(*centre, catwise_radius, deadline))
        gaia_rows, _ = gaia_job.result()
        catwise_rows, _ = catwise_job.result()

    states: dict[str, str] = {}
    if gaia_rows is not None:
        gaia, states["gaia"] = gaia_sources(gaia_rows, grid, bins), "ok"
    elif previous is not None and previous.upstreams.gaia != "unavailable":
        gaia, states["gaia"] = list(previous.gaia), "stale"
    else:
        gaia, states["gaia"] = [], "unavailable"
    if catwise_rows is not None:  # without the Gaia answer no CatWISE motion can be checked: no CatWISE track
        catwise, states["catwise"] = catwise_sources(catwise_rows, grid, bins, gaia_rows), "ok"
    elif previous is not None and previous.upstreams.catwise != "unavailable":
        catwise, states["catwise"] = list(previous.catwise), "stale"
    else:
        catwise, states["catwise"] = [], "unavailable"
    return OverlaysResponse(gaia=gaia, catwise=catwise, upstreams=OverlayUpstreams(**states))
