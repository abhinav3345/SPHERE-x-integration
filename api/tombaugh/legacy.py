"""Then and now: AllWISE and 2MASS images on a field's grid, as "legacy" planes (Contract v1.0, section 5).

For one field (its `Grid`) and each band asked for, this module finds the survey's images at IRSA, cuts out
the field, resamples it onto EXACTLY the field's north-up grid and returns one `LegacyPlane` per band. A
legacy plane has no time bin and no wave bin, keeps its survey's own dates, and is never mixed into SPHEREx
frames. Only positions compare between surveys; brightness does not.

How, per band:

1. Discovery: IRSA SIA v2, per survey one circle around the field (four circles, one per quarter, for the 8'
   and 10' fields: larger circles got no answer). Only rows of subtype "science" whose access URL has the
   documented IBE layout are used. Images are chosen greedily, nearest image centre first, until a lattice
   of points over the field is covered (at most `MAX_IMAGES_PER_BAND`).
2. Cut-out: IRSA's IBE cut-out service, ``<image URL>?center=<ra>,<dec>&size=<s>arcsec``, gzip as served.
   The service clips the cut-out to its parent image.
3. Resampling: the image's own celestial WCS (built by `register.celestial_wcs`, as for SPHEREx) maps every
   grid pixel centre to the image; values are interpolated bilinearly, good pixels and their coverage
   separately, so a NaN never smears and never counts as zero (as `register.register`). A grid pixel with
   less than half its bilinear weight on good pixels is NaN ("no data").
4. Beams and pixel sizes. AllWISE Atlas images (1.375"/px) are used as published: on the grid their stars
   measured 8.7-8.9" FWHM in W1 and 9.9" in W2, against 9.8-10.2" for the SPHEREx stacks (Gaussian fits to
   10-16 stars per field, both recorded fields, 14 Nov 2026). 2MASS Atlas images (1.0"/px, resolution
   2.8-2.9") are first smoothed with a Gaussian to a resolution of 10"; sampling the sharp image every 3.075"
   would otherwise make stars flicker in brightness with their sub-pixel position.
5. Mosaic. When the field needs several images, each image's own background (clipped median over the field)
   is removed and its zero point brought to that of the first image; then pixels are filled image by image,
   the image covering most of the field first. Images are never averaged with each other, because two 2MASS
   scans can be years apart and a moving star would be drawn twice. Pixels no image covers stay NaN, and
   `LegacyPlane.coverage` and a warning say how much of the field that is.
6. Dates: `t_min` and `t_max` of the SIA rows (MJD), the span of every image that gave a pixel. An AllWISE
   Atlas image is a coadd of frames from several passes: its span is reported, never one date.
7. Scaling ("scaled": "field_stars", Contract section 5): one gain, the median ratio of aperture fluxes of
   unsaturated field stars found in both the plane and the paired SPHEREx frame (presets.json,
   `legacy_pairs`), brings the plane to that frame's brightness scale for display. It is not a photometric
   calibration and does not make brightness comparable: the bands, the beams and the epochs differ. Without
   a reference frame or without enough common stars the plane stays in the survey's own unit (DN) with
   `scaled` None, and a warning says so.

Sources, all read or measured on 14 Nov 2026:

* SIA v2: https://irsa.ipac.caltech.edu/ibe/sia.html names the collections ``wise_allwise`` and
  ``twomass_allsky`` and says new programmatic queries should use SIA v2 rather than the older interfaces (the
  older IBE search answered HTTP 502 when tried). Columns used: ``dataproduct_subtype``,
  ``energy_bandpassname``, ``obs_id``, ``access_url``, ``t_min``, ``t_max``, ``em_min``, ``em_max`` (metres),
  ``s_resolution`` (arcsec), ``t_exptime`` (s), ``s_ra``, ``s_dec``, ``s_region``. ``RESPONSEFORMAT=TSV`` is used
  because its rows split cleanly on tabs (the CSV answer carries unquoted JSON, see discovery.py).
* Band names in the SIA answers: ``W1`` and ``W2`` for AllWISE; ``J``, ``H`` and ``K`` for 2MASS (the
  contract's ``Ks``).
* Cut-outs: https://irsa.ipac.caltech.edu/ibe/cutouts.html (``center``, ``size``, ``gzip``; clipped to the
  parent image; HTTP 500 when the box misses the image entirely).
* URL layouts: https://irsa.ipac.caltech.edu/ibe/docs/wise/allwise/p3am_cdd/ and
  https://irsa.ipac.caltech.edu/ibe/docs/twomass/allsky/allsky/.
* Header keywords (real headers of both surveys): AllWISE ``BUNIT`` "DN", ``WAVELEN`` "effective wavelength
  of band" (3.368 and 4.618 micron), ``MAGZP`` "relative photometric zero point", ``MEDCOV`` "median
  depth-of-coverage" of the tile, ``DATEOBS1``/``DATEOBS2`` "earliest/latest frame", which equal the SIA
  ``t_min``/``t_max``; 2MASS ``MAGZP`` "Calibrated zero point from CALMAN", ``TIMER1`` "Read2-Read1 time"
  (1298 ms) with SIA ``t_exptime`` 7.8 s, so 6 exposures per Atlas image.
* Frames: the survey headers state FK5 at equinox J2000 (``EQUINOX = 2000``, no ``RADESYS``); their coordinates are
  used as ICRS. Measured with astropy on 14 Nov 2026: the two frames differ by 0.022-0.031" at four positions,
  1% of a grid pixel.
* The 10" resolution of the SPHEREx stacks: CLAUDE.md section 5 [MEASURED] and the manifest note of
  build.py ("resolution about 10\"").
* Measured from the venue: an AllWISE cut-out of 470" took 1.5-2.7 s (478 kB, 370 kB gzipped); 2MASS cut-outs
  of the same size 1.0-1.9 s (99-344 kB gzipped).

Units: degrees (ICRS), arcsec, micron, MJD days. Plane values are DN of the survey (background removed) or,
once scaled, the paired SPHEREx frame's MJy/sr scale (matched on field stars, display only).
"""

from __future__ import annotations

import io
import logging
import math
import re
import time
import zlib
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from astropy.io import fits
from scipy import ndimage

from tombaugh import http, presets
from tombaugh.discovery import SIA_URL
from tombaugh.frames import plane_offset
from tombaugh.grid import Grid, pixel_centres_sky, pixel_to_sky, sky_to_pixel
from tombaugh.models import Plane
from tombaugh.prepare import clipped_stats
from tombaugh.register import WORLD2PIX_TOLERANCE_PX, celestial_wcs
from tombaugh.timebins import mjd_to_date

log = logging.getLogger(__name__)

# ------------------------------------------------------------------------------------------- constants
LEGACY_BANDS: tuple[str, ...] = ("W1", "W2", "J", "H", "Ks")  # the order of presets.json legacy_pairs
TARGET_FWHM_ARCSEC = (
    10.0  # resolution of the SPHEREx stacks (CLAUDE.md section 5, measured); 2MASS is smoothed to it
)
FWHM_PER_SIGMA = 2.0 * math.sqrt(2.0 * math.log(2.0))  # Gaussian FWHM / sigma, 2.3548
MIN_COVERAGE = 0.5  # a grid pixel needs this bilinear weight on good image pixels (as register.py)
ROTATION_ALLOWANCE = (
    1.25  # cut-out side / field side: the field stays inside for up to 13 deg of image rotation
)
EDGE_MARGIN_NATIVE_PX = 2.0  # extra image pixels around the field for the bilinear interpolation
SMOOTH_MARGIN_SIGMAS = 4.0  # extra margin for the smoothing kernel, in kernel sigmas
COVER_LATTICE = 25  # points per side of the lattice used to decide which images cover the field
MAX_IMAGES_PER_BAND = 4
SIA_TRIES = 6
# Measured on 14 Nov 2026 at two positions: twomass_allsky answered in about 1 s for circles of 0.050 and
# 0.072 deg, and not at all for 0.085, 0.10 and 0.12 deg (HTTP 502, or no answer within 150 s).
SIA_MAX_RADIUS_DEG = 0.075
SIA_TIMEOUT = (5.0, 45.0)  # (connect, read) seconds; IRSA answered in 1 s, and sometimes not within 40 s
CUTOUT_TRIES = 6  # IRSA answered HTTP 503 four times in a row once on 14 Nov 2026
CUTOUT_TIMEOUT = (5.0, 30.0)
DEFAULT_DEADLINE_S = 60.0
MAX_WORKERS = 2  # IRSA allows 2 requests in flight (http.HOST_CONCURRENCY); more threads would only wait
MAX_GZIP_BYTES = 16 * 1024 * 1024  # a cut-out larger than this, compressed, is refused
MAX_FITS_BYTES = 64 * 1024 * 1024  # ... and larger than this once decompressed
MAX_IMAGE_SIDE = 8192  # pixels

# Field-star scaling ("scaled": "field_stars"). Radii in grid pixels of 3.075".
STAR_DETECT_NSIGMA = 20.0  # a reference peak must stand this far above the reference noise
STAR_FAINT_NSIGMA = 5.0  # peaks above this count as neighbours
STAR_MATCH_PX = 1.5  # the plane's peak must lie this close to the reference peak (static stars only)
STAR_APERTURE_PX = 4.0  # 12.3": most of the flux for a 10" beam
STAR_ANNULUS_PX = (7.0, 10.0)
STAR_NEIGHBOUR_PX = 8.0  # no other peak brighter than 10 percent of the star this close
STAR_NEIGHBOUR_SHARE = 0.10
STAR_MIN_SNR = 20.0
MIN_FIELD_STARS = 5

Mission = Literal["AllWISE", "2MASS"]


@dataclass(frozen=True)
class Survey:
    """One older survey as IRSA serves it."""

    mission: Mission
    collection: str  # SIA v2 COLLECTION
    sia_bands: Mapping[str, str]  # contract band -> SIA energy_bandpassname
    url: re.Pattern[str]  # an access URL this module will fetch
    smooth: bool  # smooth to TARGET_FWHM_ARCSEC before resampling


SURVEYS: dict[Mission, Survey] = {
    "AllWISE": Survey(
        mission="AllWISE",
        collection="wise_allwise",
        sia_bands={"W1": "W1", "W2": "W2"},
        url=re.compile(
            r"^https://irsa\.ipac\.caltech\.edu/ibe/data/wise/allwise/p3am_cdd/"
            r"(\d{2})/(\d{4})/(\d{4}[pm]\d{3}_ac51)/\3-w[12]-int-3\.fits$"
        ),
        smooth=False,
    ),
    "2MASS": Survey(
        mission="2MASS",
        collection="twomass_allsky",
        sia_bands={"J": "J", "H": "H", "Ks": "K"},
        url=re.compile(
            r"^https://irsa\.ipac\.caltech\.edu/ibe/data/twomass/allsky/allsky/"
            r"\d{6}[ns]/s\d{3}/image/[jhk]i\d{7}\.fits\.gz$"
        ),
        smooth=True,
    ),
}
_SIA_COLUMNS = (
    "dataproduct_subtype",
    "energy_bandpassname",
    "obs_id",
    "access_url",
    "t_min",
    "t_max",
    "em_min",
    "em_max",
    "s_resolution",
    "t_exptime",
    "s_ra",
    "s_dec",
    "s_region",
)
_OBS_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}")


# ----------------------------------------------------------------------------------------------- types
@dataclass(frozen=True)
class LegacyImage:
    """One survey image listed by SIA: where it is, what band, when, and its footprint."""

    mission: Mission
    band: str  # contract band: W1, W2, J, H or Ks
    obs_id: str
    url: str  # validated IBE access URL of the whole image
    mjd_min: float
    mjd_max: float
    lam_min: float  # micron
    lam_max: float  # micron
    resolution_arcsec: float  # SIA s_resolution
    exptime_s: float | None
    ra: float  # image centre, degrees
    dec: float
    region: tuple[tuple[float, float], ...]  # footprint polygon (ra, dec) in degrees; empty when unknown


@dataclass(frozen=True)
class FieldStarScale:
    """The gain that brings a legacy plane to the paired SPHEREx frame's scale, from common field stars."""

    gain: float  # reference units per plane unit (MJy/sr per DN)
    n_stars: int
    scatter: float  # robust fractional scatter of the star ratios


@dataclass
class LegacyPlane:
    """One legacy plane on the field's grid, ready for frames.bin (pass ``plane.data`` to encode_planes)."""

    mission: Mission
    band: str
    data: np.ndarray  # float32 (n, n), row 0 north, column 0 east, NaN = no data
    unit: str  # unit of `data`: the survey's ("DN") or "MJy/sr (matched on field stars)"
    native_unit: str  # the survey's own unit, "DN"
    gain: float | None  # data = native values x gain; None when not scaled
    n_stars: int  # field stars behind the gain (0 when not scaled)
    sigma: float  # robust noise of `data`, in `unit`
    lam_min: float  # micron
    lam_max: float
    lam_eff: float
    n_exposures: int
    mjd_min: float
    mjd_max: float
    coverage: float  # share of the field's pixels with data, 0..1
    images: list[str]  # obs_ids of the images that gave pixels, first one first
    resolution_arcsec: float  # of `data`: the survey's, or the smoothing target
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def mjd_mid(self) -> float:
        """Midpoint of the span, MJD days (a label for the span, not an epoch of the image)."""
        return 0.5 * (self.mjd_min + self.mjd_max)

    @property
    def scaled(self) -> Literal["field_stars"] | None:
        """The contract's ``scaled`` value: "field_stars" once the gain is applied, else None."""
        return "field_stars" if self.gain is not None else None

    def plane_model(self, index: int, grid: Grid) -> Plane:
        """The manifest entry of this plane at position ``index`` of frames.bin."""
        return Plane(
            index=index,
            kind="legacy",
            mission=self.mission,
            time_bin=None,
            wave_bin=None,
            band=self.band,
            lam_min=round(self.lam_min, 5),
            lam_max=round(self.lam_max, 5),
            lam_eff=round(self.lam_eff, 5),
            n_exposures=int(self.n_exposures),
            sigma=float(f"{self.sigma:.6g}"),
            mjd_mid=round(self.mjd_mid, 5),
            date_start=mjd_to_date(self.mjd_min),
            date_end=mjd_to_date(self.mjd_max),
            offset=plane_offset(index, grid.n, grid.n),
            scaled=self.scaled,
        )


@dataclass
class LegacyResult:
    """What `build_legacy_planes` made: planes in the order of `bands`, warnings, and what it cost.

    `bytes_downloaded` and `requests` come from the process-wide counters of `tombaugh.http`, so they include
    other requests made at the same time.
    """

    planes: list[LegacyPlane]
    warnings: list[str]
    seconds: float
    bytes_downloaded: int
    requests: int


@dataclass
class _Resampled:
    image: LegacyImage
    data: np.ndarray  # float64 (n, n), background removed, zero point of `magzp`
    magzp: float | None
    header: fits.Header
    coverage: float


# ------------------------------------------------------------------------------------------- pairs
def legacy_pair(band: str) -> dict:
    """The ``legacy_pairs`` entry of presets.json for a contract band (KeyError when unknown)."""
    for pair in presets.load_presets()["legacy_pairs"]:
        if pair["band"] == band:
            return pair
    raise KeyError(f"unknown legacy band {band!r}")


def mission_of(band: str) -> Mission:
    """AllWISE or 2MASS for a contract band, from presets.json."""
    mission = legacy_pair(band)["mission"]
    if mission not in SURVEYS:
        raise KeyError(f"presets.json names an unknown mission {mission!r}")
    return mission


def paired_reference(planes: Iterable, band: str) -> np.ndarray | None:
    """The paired SPHEREx frame of a legacy band, averaged over time bins, or None without data.

    ``planes`` are SPHEREx stacks with ``time_bin``, ``wave_bin`` and ``data`` (``StackedPlane``). For each time
    bin the frame is the contract's uniform-weight mean over the preset's wave bins with a finite pixel
    (Contract section 4); the reference is the mean of those frames where they are finite. It only serves to
    find and measure field stars.
    """
    wave_bins = presets.preset_wave_bins(legacy_pair(band)["spherex_preset"])
    if not isinstance(wave_bins, list):
        raise TypeError(f"the preset paired with {band} is not a single-band preset")
    chosen = set(wave_bins)
    by_time: dict[int, list[np.ndarray]] = defaultdict(list)
    for plane in planes:
        if plane.time_bin is not None and plane.wave_bin in chosen:
            by_time[int(plane.time_bin)].append(np.asarray(plane.data, dtype=np.float64))
    frames = [_finite_mean(by_time[t]) for t in sorted(by_time)]
    if not frames:
        return None
    reference = _finite_mean(frames)
    return reference if np.isfinite(reference).any() else None


def _finite_mean(arrays: Sequence[np.ndarray]) -> np.ndarray:
    stack = np.stack(arrays)
    finite = np.isfinite(stack)
    count = finite.sum(axis=0)
    total = np.where(finite, stack, 0.0).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count > 0, total / np.maximum(count, 1), np.nan)


# ------------------------------------------------------------------------------------------- discovery
def _field_side_arcsec(grid: Grid) -> float:
    return grid.n * grid.pixscale


def search_radius_deg(grid: Grid) -> float:
    """SIA search circle: the half-diagonal of the field, degrees."""
    return _field_side_arcsec(grid) / 2.0 * math.sqrt(2.0) / 3600.0


def search_circles(grid: Grid) -> list[tuple[float, float, float]]:
    """SIA circles (ra, dec, radius in degrees) that together cover the field.

    One circle around the whole field when its radius is at most `SIA_MAX_RADIUS_DEG`; otherwise one circle
    around each quarter of the field (8' and 10' fields), because larger circles get no answer.
    """
    radius = search_radius_deg(grid)
    if radius <= SIA_MAX_RADIUS_DEG:
        return [(grid.ra0, grid.dec0, radius)]
    quarter = grid.n / 4.0
    circles = []
    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        ra, dec = pixel_to_sky(grid, grid.cx + dx * quarter, grid.cy + dy * quarter)
        circles.append((ra, dec, radius / 2.0))
    return circles


def _parse_region(text: str) -> tuple[tuple[float, float], ...]:
    """Vertices of an SIA ``s_region`` "POLYGON [ICRS] ra dec ra dec ..." (degrees); empty when unreadable."""
    tokens = text.replace(",", " ").split()
    if len(tokens) < 7 or tokens[0].upper() != "POLYGON":
        return ()
    numbers = tokens[1:]
    if numbers and not _is_number(numbers[0]):
        numbers = numbers[1:]  # the frame name, "ICRS"
    try:
        values = [float(v) for v in numbers]
    except ValueError:
        return ()
    if len(values) % 2 or len(values) < 6 or not all(math.isfinite(v) for v in values):
        return ()
    vertices = list(zip(values[0::2], values[1::2], strict=True))
    if len(vertices) > 3 and vertices[0] == vertices[-1]:
        vertices.pop()  # the closing vertex repeats the first
    return tuple(vertices)


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def parse_sia_tsv(text: str, mission: Mission) -> tuple[list[LegacyImage], dict[str, int]]:
    """Science images of an SIA v2 TSV answer for one survey, and how many rows were dropped, by reason.

    Rows of other subtypes (uncertainty, coverage, artefact tables) are expected and counted as
    ``not_science``. Raises ValueError when ``text`` is not an SIA table.
    """
    survey = SURVEYS[mission]
    band_of = {sia: band for band, sia in survey.sia_bands.items()}
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("empty SIA answer")
    header = [name.strip() for name in lines[0].lstrip("﻿").split("\t")]
    missing = [name for name in _SIA_COLUMNS if name not in header]
    if missing:
        raise ValueError(f"not an SIA table: no column {', '.join(missing)}")
    images: list[LegacyImage] = []
    dropped: dict[str, int] = defaultdict(int)
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) != len(header):
            dropped["malformed_row"] += 1
            continue
        row = {name: cell.strip() for name, cell in zip(header, cells, strict=True)}
        outcome = _image(row, survey, band_of)
        if isinstance(outcome, LegacyImage):
            images.append(outcome)
        else:
            dropped[outcome] += 1
    images.sort(key=lambda image: (image.band, image.obs_id))
    return images, dict(dropped)


def _image(row: dict[str, str], survey: Survey, band_of: Mapping[str, str]) -> LegacyImage | str:
    """The validated image of one SIA row, or the reason the row is dropped."""
    if row["dataproduct_subtype"].lower() != "science":
        return "not_science"
    band = band_of.get(row["energy_bandpassname"])
    if band is None:
        return "other_band"
    url = row["access_url"]
    if survey.url.fullmatch(url) is None:
        return "unexpected_url"
    try:
        http.check_url(url)
    except ValueError:
        return "foreign_host"
    if _OBS_ID.fullmatch(row["obs_id"]) is None:
        return "bad_obs_id"
    try:
        t_min, t_max = float(row["t_min"]), float(row["t_max"])
        em_min, em_max = float(row["em_min"]), float(row["em_max"])
        resolution = float(row["s_resolution"])
        ra, dec = float(row["s_ra"]), float(row["s_dec"])
    except ValueError:
        return "bad_number"
    numbers = (t_min, t_max, em_min, em_max, resolution, ra, dec)
    if not all(math.isfinite(v) for v in numbers) or t_max < t_min or not 0.0 < em_min < em_max:
        return "bad_number"
    try:
        exptime: float | None = float(row["t_exptime"])
    except ValueError:
        exptime = None
    if exptime is not None and not (math.isfinite(exptime) and exptime > 0.0):
        exptime = None
    return LegacyImage(
        mission=survey.mission,
        band=band,
        obs_id=row["obs_id"],
        url=url,
        mjd_min=t_min,
        mjd_max=t_max,
        lam_min=em_min * 1e6,
        lam_max=em_max * 1e6,
        resolution_arcsec=resolution,
        exptime_s=exptime,
        ra=ra,
        dec=dec,
        region=_parse_region(row["s_region"]),
    )


def query_sia(
    mission: Mission, circle: tuple[float, float, float], *, deadline: http.Deadline | None = None
) -> list[LegacyImage]:
    """Science images of one survey meeting one circle (ra, dec, radius in degrees). Raises UpstreamError."""
    survey = SURVEYS[mission]
    ra, dec, radius = circle
    pos = f"circle {ra:.6f} {dec:.6f} {radius:.6f}"
    params = {"COLLECTION": survey.collection, "POS": pos, "RESPONSEFORMAT": "TSV"}
    response = http.get(SIA_URL, params=params, timeout=SIA_TIMEOUT, tries=SIA_TRIES, deadline=deadline)
    try:
        images, dropped = parse_sia_tsv(response.content.decode("utf-8", "replace"), mission)
    except ValueError as exc:
        raise http.UpstreamError(
            f"unreadable SIA answer for {survey.collection}: {exc}", url=SIA_URL
        ) from exc
    faults = {reason: n for reason, n in dropped.items() if reason not in ("not_science", "other_band")}
    if faults:
        log.warning("SIA %s: dropped %d row(s): %s", survey.collection, sum(faults.values()), faults)
    return images


def merge_images(parts: Iterable[Sequence[LegacyImage]]) -> list[LegacyImage]:
    """One entry per (band, obs_id) from several SIA answers, sorted by (band, obs_id)."""
    unique: dict[tuple[str, str], LegacyImage] = {}
    for images in parts:
        for image in images:
            unique.setdefault((image.band, image.obs_id), image)
    return [unique[key] for key in sorted(unique)]


# ------------------------------------------------------------------------------------- choosing images
def _lattice(grid: Grid, points: int = COVER_LATTICE) -> tuple[np.ndarray, np.ndarray]:
    """Grid-pixel coordinates (x, y) of a square lattice spanning the field's outer pixel edges."""
    edge = np.linspace(-0.5, grid.n - 0.5, points)
    xs, ys = np.meshgrid(edge, edge)
    return xs.ravel(), ys.ravel()


def _inside(polygon: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Which points lie inside a convex polygon (vertices (k, 2) in order, either sense), edges included."""
    signs = []
    for i in range(len(polygon)):
        (x1, y1), (x2, y2) = polygon[i], polygon[(i + 1) % len(polygon)]
        signs.append((x2 - x1) * (ys - y1) - (y2 - y1) * (xs - x1))
    cross = np.stack(signs)
    return np.all(cross >= 0.0, axis=0) | np.all(cross <= 0.0, axis=0)


def image_cover(image: LegacyImage, grid: Grid) -> np.ndarray | None:
    """Which lattice points of the field the image's footprint covers; None when the footprint is unknown."""
    if len(image.region) < 3:
        return None
    ra = [vertex[0] for vertex in image.region]
    dec = [vertex[1] for vertex in image.region]
    x, y = sky_to_pixel(grid, ra, dec)
    polygon = np.column_stack([np.atleast_1d(x), np.atleast_1d(y)])
    if not np.isfinite(polygon).all():
        return None
    return _inside(polygon, *_lattice(grid))


def choose_images(images: Sequence[LegacyImage], grid: Grid) -> tuple[list[LegacyImage], float]:
    """Images of ONE band that together cover the field, and the share of the lattice they cover (0..1).

    Nearest image centre first; an image is taken only when it covers lattice points not yet covered, up to
    `MAX_IMAGES_PER_BAND`. Images without a readable footprint are taken last, if room is left.
    """

    def distance(image: LegacyImage) -> float:
        x, y = sky_to_pixel(grid, image.ra, image.dec)
        return math.hypot(x - grid.cx, y - grid.cy) if math.isfinite(x) and math.isfinite(y) else math.inf

    ordered = sorted(images, key=lambda image: (distance(image), image.obs_id))
    chosen: list[LegacyImage] = []
    unknown: list[LegacyImage] = []
    covered = np.zeros(COVER_LATTICE * COVER_LATTICE, dtype=bool)
    for image in ordered:
        cover = image_cover(image, grid)
        if cover is None:
            unknown.append(image)
            continue
        if len(chosen) < MAX_IMAGES_PER_BAND and (cover & ~covered).any():
            chosen.append(image)
            covered |= cover
    for image in unknown:
        if len(chosen) < MAX_IMAGES_PER_BAND and not covered.all():
            chosen.append(image)
    return chosen, float(covered.mean())


# ------------------------------------------------------------------------------------------- cut-outs
def cutout_side_arcsec(grid: Grid, image: LegacyImage, pixscale_arcsec: float) -> float:
    """Side of the square cut-out asked for: the field with room for image rotation and the kernels."""
    margin = EDGE_MARGIN_NATIVE_PX * pixscale_arcsec
    if SURVEYS[image.mission].smooth:
        margin += SMOOTH_MARGIN_SIGMAS * kernel_sigma_arcsec(image.resolution_arcsec)
    return math.ceil(_field_side_arcsec(grid) * ROTATION_ALLOWANCE + 2.0 * margin)


def cutout_params(grid: Grid, side_arcsec: float) -> dict[str, str]:
    """Query parameters of an IBE cut-out centred on the field (gzip as served)."""
    return {"center": f"{grid.ra0:.6f},{grid.dec0:.6f}", "size": f"{side_arcsec:.0f}arcsec", "gzip": "true"}


# Native pixel scales, arcsec, used only to size the cut-out before its header is read (SIA s_pixel_scale:
# 1.375 for AllWISE, 1.000 for 2MASS); the resampling uses the WCS of the file itself.
_PIXSCALE_HINT = {"AllWISE": 1.375, "2MASS": 1.0}


def _gunzip(raw: bytes) -> bytes:
    """The FITS bytes of a cut-out: gunzipped when gzip, with a size limit; plain FITS passes through."""
    if len(raw) > MAX_GZIP_BYTES:
        raise ValueError(f"cut-out of {len(raw)} bytes exceeds the limit")
    if raw[:2] != b"\x1f\x8b":
        return raw
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    data = inflater.decompress(raw, MAX_FITS_BYTES)
    if inflater.unconsumed_tail:
        raise ValueError("cut-out larger than the decompression limit")
    return data


def read_cutout(raw: bytes) -> tuple[fits.Header, np.ndarray]:
    """Header and float64 image of a cut-out (gzip or plain FITS); NaN stays NaN. Raises ValueError."""
    data = _gunzip(raw)
    if not data.startswith(b"SIMPLE  ="):
        raise ValueError("not a FITS file")
    with fits.open(io.BytesIO(data), memmap=False, lazy_load_hdus=False) as hdus:
        hdu = hdus[0]
        header = hdu.header.copy()
        if header.get("NAXIS") != 2 or hdu.data is None:
            raise ValueError("the cut-out is not a 2-D image")
        image = np.asarray(hdu.data, dtype=np.float64)
    if image.ndim != 2 or max(image.shape) > MAX_IMAGE_SIDE or min(image.shape) < 2:
        raise ValueError(f"unexpected cut-out shape {image.shape}")
    return header, image


def _header_text(header: fits.Header) -> str:
    return header.tostring(sep="\n")


def native_pixscale_arcsec(header: fits.Header) -> float:
    """Mean pixel scale of the image at its reference pixel, arcsec (from its WCS)."""
    wcs = celestial_wcs(_header_text(header))
    scales = wcs.proj_plane_pixel_scales()
    return float(np.mean([abs(s.to_value("deg")) for s in scales])) * 3600.0


# ------------------------------------------------------------------------------------- beams and grids
def kernel_sigma_arcsec(native_fwhm_arcsec: float, target_fwhm_arcsec: float = TARGET_FWHM_ARCSEC) -> float:
    """Sigma of the Gaussian that takes a beam of `native_fwhm` to `target_fwhm` (both FWHM, arcsec)."""
    if not 0.0 < native_fwhm_arcsec < target_fwhm_arcsec:
        return 0.0
    return math.sqrt(target_fwhm_arcsec**2 - native_fwhm_arcsec**2) / FWHM_PER_SIGMA


def smooth(image: np.ndarray, sigma_px: float) -> np.ndarray:
    """Gaussian smoothing that ignores NaN: good pixels and their weights are smoothed separately.

    A pixel with less than half its kernel weight on good pixels becomes NaN. ``sigma_px`` in image pixels.
    """
    if sigma_px <= 0.0:
        return np.asarray(image, dtype=np.float64)
    good = np.isfinite(image)
    filled = np.where(good, image, 0.0).astype(np.float64)
    options = {"sigma": sigma_px, "mode": "constant", "cval": 0.0, "truncate": 4.0}
    total = ndimage.gaussian_filter(filled, **options)
    weight = ndimage.gaussian_filter(good.astype(np.float64), **options)
    out = np.full(image.shape, np.nan)
    ok = weight >= MIN_COVERAGE
    out[ok] = total[ok] / weight[ok]
    return out


def resample(image: np.ndarray, header: fits.Header, grid: Grid) -> np.ndarray:
    """Bilinear resampling of an image onto the grid through its own celestial WCS.

    Returns float64 (n, n), row 0 north and column 0 east, NaN where the bilinear coverage by good pixels is
    below one half. Pixel values are interpolated, not summed: a surface brightness stays one.
    """
    wcs = celestial_wcs(_header_text(header))
    ra, dec = pixel_centres_sky(grid)
    x, y = wcs.all_world2pix(ra, dec, 0, tolerance=WORLD2PIX_TOLERANCE_PX, maxiter=50, quiet=True)
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    outside = ~(np.isfinite(x) & np.isfinite(y))
    coords = np.stack([np.where(outside, -10.0, y), np.where(outside, -10.0, x)])
    good = np.isfinite(image)
    filled = np.where(good, image, 0.0)
    options = {"order": 1, "mode": "constant", "cval": 0.0, "prefilter": False}
    weighted = ndimage.map_coordinates(filled, coords, **options)
    coverage = ndimage.map_coordinates(good.astype(np.float64), coords, **options)
    out = np.full(grid.shape, np.nan)
    covered = (coverage >= MIN_COVERAGE) & ~outside
    out[covered] = weighted[covered] / coverage[covered]
    return out


def _magzp(header: fits.Header) -> float | None:
    value = header.get("MAGZP")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def prepare_image(image: LegacyImage, raw: bytes, grid: Grid) -> _Resampled:
    """One downloaded cut-out on the grid: smoothed (2MASS), resampled, its background removed."""
    header, data = read_cutout(raw)
    if SURVEYS[image.mission].smooth:
        sigma_px = kernel_sigma_arcsec(image.resolution_arcsec) / native_pixscale_arcsec(header)
        data = smooth(data, sigma_px)
    on_grid = resample(data, header, grid)
    background, _, n_sky = clipped_stats(on_grid)
    if n_sky == 0:
        return _Resampled(image, on_grid, _magzp(header), header, 0.0)
    on_grid = on_grid - background
    return _Resampled(image, on_grid, _magzp(header), header, float(np.isfinite(on_grid).mean()))


def mosaic(parts: Sequence[_Resampled]) -> tuple[np.ndarray, list[_Resampled]]:
    """Fill the grid image by image, most-covering first, on the first image's zero point.

    Returns the mosaic (float64, NaN where no image has data) and the parts that gave at least one pixel,
    in fill order. Images are never averaged with each other.
    """
    ordered = sorted(parts, key=lambda part: (-part.coverage, part.image.obs_id))
    ordered = [part for part in ordered if part.coverage > 0.0]
    if not ordered:
        raise ValueError("no image has data on the grid")
    out = np.full(ordered[0].data.shape, np.nan)
    reference_zp = ordered[0].magzp
    used: list[_Resampled] = []
    for part in ordered:
        factor = 1.0
        if reference_zp is not None and part.magzp is not None:
            factor = 10.0 ** (0.4 * (reference_zp - part.magzp))  # m = MAGZP - 2.5 log10(DN)
        fill = np.isnan(out) & np.isfinite(part.data)
        if fill.any():
            out[fill] = part.data[fill] * factor
            used.append(part)
    return out, used


# ---------------------------------------------------------------------------------------- field stars
def _peaks(image: np.ndarray, threshold: float) -> tuple[np.ndarray, np.ndarray]:
    """Rows and columns of local maxima (3 x 3) above `threshold`; NaN never peaks."""
    filled = np.where(np.isfinite(image), image, -np.inf)
    local = ndimage.maximum_filter(filled, size=3, mode="constant", cval=-np.inf)
    rows, cols = np.nonzero((filled == local) & (filled > threshold))
    return rows, cols


def aperture_flux(image: np.ndarray, x: float, y: float) -> tuple[float, float] | None:
    """(flux, noise) in an aperture of `STAR_APERTURE_PX` around (x, y) less the annulus median.

    Units: the image's unit times pixels. None when the aperture holds a NaN or the annulus is mostly NaN.
    """
    radius = STAR_ANNULUS_PX[1] + 1
    r0, r1 = math.floor(y - radius), math.ceil(y + radius) + 1
    c0, c1 = math.floor(x - radius), math.ceil(x + radius) + 1
    if r0 < 0 or c0 < 0 or r1 > image.shape[0] or c1 > image.shape[1]:
        return None
    box = image[r0:r1, c0:c1]
    rows, cols = np.indices(box.shape, dtype=np.float64)
    distance = np.hypot(cols + c0 - x, rows + r0 - y)
    aperture = distance <= STAR_APERTURE_PX
    annulus = (distance >= STAR_ANNULUS_PX[0]) & (distance <= STAR_ANNULUS_PX[1])
    if not np.isfinite(box[aperture]).all():
        return None
    ring = box[annulus]
    ring = ring[np.isfinite(ring)]
    if ring.size < 0.5 * annulus.sum():
        return None
    sky, sky_sigma, _ = clipped_stats(ring)
    if not math.isfinite(sky):
        return None
    n = int(aperture.sum())
    flux = float(box[aperture].sum() - n * sky)
    noise = float(sky_sigma * math.sqrt(n * (1.0 + n / ring.size))) if sky_sigma > 0 else math.inf
    return flux, noise


def field_star_scale(data: np.ndarray, reference: np.ndarray) -> tuple[FieldStarScale | None, str]:
    """Gain from `data` (a legacy plane) to `reference` (the paired SPHEREx frame) on common field stars.

    A star is a peak of the reference at least 20 sigma high, with a peak of the plane within 1.5 pixels
    (so moving stars drop out), no NaN in either aperture (saturated cores drop out), no other peak brighter
    than a tenth of it within 8 pixels in either image, and S/N of 20 or more in both. The gain is the median
    of the flux ratios. Returns (scale, "") or (None, the reason).
    """
    if data.shape != reference.shape:
        raise ValueError(f"plane {data.shape} and reference {reference.shape} differ in shape")
    _, sigma_ref, _ = clipped_stats(reference)
    _, sigma_dat, _ = clipped_stats(data)
    if not (sigma_ref > 0.0 and sigma_dat > 0.0):
        return None, "no noise estimate"
    neighbours = []
    for image, sigma in ((reference, sigma_ref), (data, sigma_dat)):
        rows, cols = _peaks(image, STAR_FAINT_NSIGMA * sigma)
        neighbours.append((rows, cols, image[rows, cols]))
    data_rows, data_cols, _ = neighbours[1]
    ratios: list[float] = []
    for row, col in zip(*_peaks(reference, STAR_DETECT_NSIGMA * sigma_ref), strict=True):
        near = np.hypot(data_rows - row, data_cols - col) <= STAR_MATCH_PX
        if not near.any():
            continue
        if any(
            _crowded(row, col, image, n_rows, n_cols, values)
            for image, (n_rows, n_cols, values) in zip((reference, data), neighbours, strict=True)
        ):
            continue
        ref = aperture_flux(reference, float(col), float(row))
        dat = aperture_flux(data, float(col), float(row))
        if ref is None or dat is None:
            continue
        if ref[0] < STAR_MIN_SNR * ref[1] or dat[0] < STAR_MIN_SNR * dat[1]:
            continue
        ratios.append(ref[0] / dat[0])
    if len(ratios) < MIN_FIELD_STARS:
        return None, f"{len(ratios)} usable field stars in common, {MIN_FIELD_STARS} needed"
    values = np.array(ratios)
    gain = float(np.median(values))
    scatter = float(1.4826 * np.median(np.abs(values - gain)) / gain)
    if not (math.isfinite(gain) and gain > 0.0):
        return None, "the field stars gave no positive gain"
    return FieldStarScale(gain=gain, n_stars=len(ratios), scatter=scatter), ""


def _crowded(row: int, col: int, image: np.ndarray, rows: np.ndarray, cols: np.ndarray, values) -> bool:
    """True when another peak brighter than a tenth of the star lies within `STAR_NEIGHBOUR_PX`."""
    peak = image[row, col] if np.isfinite(image[row, col]) else -np.inf
    distance = np.hypot(rows - row, cols - col)
    near = (distance > STAR_MATCH_PX) & (distance <= STAR_NEIGHBOUR_PX)
    return bool((values[near] > STAR_NEIGHBOUR_SHARE * peak).any())


# ------------------------------------------------------------------------------------------- planes
def _n_exposures(used: Sequence[_Resampled]) -> int:
    """Exposures behind a typical pixel, from the first image's own metadata (see the module docstring)."""
    first = used[0]
    if first.image.mission == "AllWISE":
        medcov = first.header.get("MEDCOV")  # median depth-of-coverage of the tile, frames
        try:
            return max(1, round(float(medcov)))
        except (TypeError, ValueError):
            return 1
    timer = first.header.get("TIMER1")  # Read2-Read1 time, ms: one 2MASS exposure
    try:
        return max(1, round(float(first.image.exptime_s) / (float(timer) / 1000.0)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 1


def _lam_eff(used: Sequence[_Resampled]) -> float:
    """Effective wavelength, micron: AllWISE header WAVELEN, else the middle of the SIA band limits."""
    first = used[0]
    value = first.header.get("WAVELEN")
    try:
        lam = float(value)
    except (TypeError, ValueError):
        lam = math.nan
    if math.isfinite(lam) and first.image.lam_min <= lam <= first.image.lam_max:
        return lam
    return 0.5 * (first.image.lam_min + first.image.lam_max)


def assemble_plane(
    band: str, parts: Sequence[_Resampled], grid: Grid, reference: np.ndarray | None
) -> LegacyPlane:
    """One band's plane from its resampled images, scaled on field stars when a reference frame is given."""
    native, used = mosaic(parts)
    first = used[0].image
    coverage = float(np.isfinite(native).mean())
    _, native_sigma, _ = clipped_stats(native)
    span = (min(p.image.mjd_min for p in used), max(p.image.mjd_max for p in used))
    unit = str(used[0].header.get("BUNIT", "DN")).strip() or "DN"
    if first.mission == "2MASS":
        unit = "DN"  # 2MASS Atlas headers carry no BUNIT; their zero point MAGZP is in DN
    plane = LegacyPlane(
        mission=first.mission,
        band=band,
        data=native.astype(np.float32),
        unit=unit,
        native_unit=unit,
        gain=None,
        n_stars=0,
        sigma=float(native_sigma),
        lam_min=first.lam_min,
        lam_max=first.lam_max,
        lam_eff=_lam_eff(used),
        n_exposures=_n_exposures(used),
        mjd_min=span[0],
        mjd_max=span[1],
        coverage=coverage,
        images=[part.image.obs_id for part in used],
        resolution_arcsec=TARGET_FWHM_ARCSEC if SURVEYS[first.mission].smooth else first.resolution_arcsec,
    )
    label = f"{first.mission} {band}"
    dates = f"{mjd_to_date(span[0])} to {mjd_to_date(span[1])}"
    how = (
        f'smoothed from {first.resolution_arcsec:g}" to {TARGET_FWHM_ARCSEC:g}" resolution'
        if SURVEYS[first.mission].smooth
        else "as published"
    )
    plane.notes.append(
        f"{label}: {len(used)} archive image(s) ({', '.join(plane.images)}), {dates}, {how}, resampled "
        "bilinearly onto the field grid. Only positions compare with SPHEREx; brightness does not."
    )
    if len(used) > 1:
        plane.notes.append(f"{label}: a mosaic; each pixel comes from one image, never an average of images.")
    if coverage < 1.0:
        plane.warnings.append(
            f"{label}: {100.0 * (1.0 - coverage):.0f}% of the field has no data from the survey."
        )
    if reference is None:
        plane.warnings.append(
            f"{label}: not scaled on field stars (no paired SPHEREx frame); values in {unit}."
        )
        return plane
    scale, reason = field_star_scale(native, reference)
    if scale is None:
        plane.warnings.append(f"{label}: not scaled on field stars ({reason}); values in {unit}.")
        return plane
    plane.data = (native * scale.gain).astype(np.float32)
    plane.gain = scale.gain
    plane.n_stars = scale.n_stars
    plane.sigma = float(native_sigma * scale.gain)
    plane.unit = "MJy/sr (matched on field stars)"
    plane.notes.append(
        f"{label}: brightness matched to the paired SPHEREx frame on {scale.n_stars} field stars "
        f"(scatter {100.0 * scale.scatter:.0f}%), for display only: not a calibration."
    )
    return plane


# --------------------------------------------------------------------------------------------- build
def build_legacy_planes(
    grid: Grid,
    bands: Sequence[str] = LEGACY_BANDS,
    *,
    references: Mapping[str, np.ndarray | None] | Callable[[str], np.ndarray | None] | None = None,
    deadline: http.Deadline | None = None,
) -> LegacyResult:
    """Legacy planes of a field for `bands` (contract names), in that order, with honest warnings.

    `references` gives, per band, the paired SPHEREx frame on the same grid (see `paired_reference`); a band
    without one is returned unscaled. Network: one SIA request per survey (four for 8' and 10' fields) and one
    cut-out per chosen image, at most two at a time, all within `deadline` (default 60 s). A band whose survey
    cannot be read, or whose images all fail, gives no plane and a warning; nothing is ever made up. Raises
    KeyError for a band that presets.json does not pair, before anything is sent.
    """
    started = time.monotonic()
    before = http.stats()
    limit = deadline if deadline is not None else http.Deadline(DEFAULT_DEADLINE_S)
    for band in bands:
        mission_of(band)  # raises KeyError for an unknown band before anything is sent
    warnings: list[str] = []
    missions = sorted({mission_of(band) for band in bands})

    found: dict[Mission, list[LegacyImage]] = {}
    circles = search_circles(grid)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="tombaugh-legacy") as pool:
        futures = {
            mission: [pool.submit(query_sia, mission, circle, deadline=limit) for circle in circles]
            for mission in missions
        }
        for mission, parts in futures.items():
            try:
                found[mission] = merge_images(part.result() for part in parts)
            except (http.UpstreamError, ValueError) as exc:
                warnings.append(f"{mission}: archive unavailable ({_short(exc)}); no {mission} plane.")

    jobs: list[tuple[str, LegacyImage]] = []
    for band in bands:
        mission = mission_of(band)
        if mission not in found:
            continue
        chosen, _ = choose_images([image for image in found[mission] if image.band == band], grid)
        if not chosen:
            warnings.append(f"{mission} {band}: no image of the archive covers this field.")
        jobs.extend((band, image) for image in chosen)

    parts: dict[str, list[_Resampled]] = defaultdict(list)
    failed: dict[str, list[str]] = defaultdict(list)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="tombaugh-legacy") as pool:
        futures = [(band, image, pool.submit(_fetch_and_prepare, image, grid, limit)) for band, image in jobs]
        for band, image, future in futures:
            try:
                parts[band].append(future.result())
            except Exception as exc:  # an image that cannot be fetched or read is reported, never fatal
                if not isinstance(exc, (http.UpstreamError, ValueError, OSError)):
                    log.exception("legacy image %s could not be read", image.obs_id)
                failed[band].append(f"{image.obs_id}: {_short(exc)}")

    planes: list[LegacyPlane] = []
    for band in bands:
        mission = mission_of(band)
        if failed.get(band):
            warnings.append(
                f"{mission} {band}: {len(failed[band])} image(s) not read ({'; '.join(failed[band])})."
            )
        usable = [part for part in parts.get(band, []) if part.coverage > 0.0]
        if not usable:
            if band in parts or failed.get(band):
                warnings.append(f"{mission} {band}: no data on this field; no plane.")
            continue
        reference = references(band) if callable(references) else (references or {}).get(band)
        plane = assemble_plane(band, usable, grid, reference)
        warnings.extend(plane.warnings)
        planes.append(plane)

    after = http.stats()
    return LegacyResult(
        planes=planes,
        warnings=warnings,
        seconds=time.monotonic() - started,
        bytes_downloaded=after["bytes"] - before["bytes"],
        requests=after["requests"] - before["requests"],
    )


def _fetch_and_prepare(image: LegacyImage, grid: Grid, deadline: http.Deadline) -> _Resampled:
    side = cutout_side_arcsec(grid, image, _PIXSCALE_HINT[image.mission])
    response = http.get(
        image.url,
        params=cutout_params(grid, side),
        timeout=CUTOUT_TIMEOUT,
        tries=CUTOUT_TRIES,
        deadline=deadline,
    )
    return prepare_image(image, response.content, grid)


def _short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:160]
