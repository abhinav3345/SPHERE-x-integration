"""Quick-look spectrophotometry at one sky position: the body of GET /api/fields/{key}/spectrum.

Contract v1.0, section 7.1. SPHEREx images a sky position at one wavelength per exposure, so the spectrum of a
source is one flux density per exposure against that exposure's wavelength at the source, about 0.75 to 5 micron.
For every exposure this module:

1. puts the source on the detector through the exposure's full celestial WCS (SIP included), at the position its
   catalogue proper motion gives for the exposure's mid-time;
2. takes the local background as the 3-sigma-clipped median of the native pixels 5 to 9 pixels from the source
   that carry no bit of the background mask;
3. measures the flux on NATIVE pixels, never on the resampled grid: an aperture of radius 2 pixels divided by the
   share of the point-spread function inside it ("aperture"), or, when a caller names catalogued neighbours
   within 15 arcsec, a joint fit of the point-spread function of the target and of each neighbour at their fixed
   catalogue positions ("joint_psf");
4. converts MJy/sr to microjansky with the solid angle of the pixel at the source, from the same full WCS;
5. gives the error as the statistical error in quadrature with 3 percent of the flux.

A binned value's error also holds, in quadrature, a background term per detector (BACKGROUND_FLOOR_UJY) and
the bin's measured annulus skew (`_Point.background_skew`): the sky under a faint source is uncertain by tens of
microjansky (measured on 14 Nov 2026: -16 to -35 microjansky per detector at the emptiest positions of the WISE
0855 field, -49 to -241 at those of the crowded Barnard field), and averaging the exposures of a bin does not
remove it.

The point-spread function is the EPSF extension of the Level-2 file itself (an effective PSF per zone of the
detector, 5 times oversampled). Measured on 14 Nov 2026: that table is byte-identical in every file of a detector
(detectors 1, 3, 4, 6; DR1 and QR3; processing runs l2b-v27-2026-197 to l2b-v27-2026-246), so it is read once per
detector and processing version and kept in memory.

States of the answer (Contract 7.1), strongest first:

* "no_data": no exposure covers the position with the whole aperture on the detector;
* "saturated": the core of the source (pixels within 1 pixel) is blank in more than half of the exposures that see
  it: no flux is offered, ``points`` is empty;
* "indicative": the core is blank or carries OVERFLOW in at least a tenth of the exposures that see it: points
  come back, those with OVERFLOW on the core with quality "saturated" (also in the other states);
* "contaminated": a catalogued neighbour within 15 arcsec could not be fitted jointly (closer than 3 arcsec, or no
  point-spread function): the aperture holds its light too;
* "ok".

``binned`` combines the points of quality "good" only, per time bin and wavelength bin (the 24 bins of Contract
section 4); flagged and saturated points are shown, never averaged into a value that looks reliable.

Units: degrees (ICRS), mas/yr, Julian years, MJD days, micron, MJy/sr for images, microjansky for flux densities,
native detector pixels of about 6.15 arcsec for radii. Nothing is fetched from an address a user gave: windows and
point-spread functions come from the exposure's own object in the public bucket, through ``tombaugh.http``.
"""

from __future__ import annotations

import io
import logging
import math
import re
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field

import numpy as np
from astropy.io import fits
from astropy.time import Time
from scipy import ndimage

from tombaugh import http, presets, remote_fits
from tombaugh.build import EPOCH_REF
from tombaugh.models import (
    BinnedPoint,
    Neighbour,
    SnappedTo,
    SpectrumMethod,
    SpectrumPoint,
    SpectrumResponse,
    SpectrumTarget,
    TimeBin,
    TimeSpan,
)
from tombaugh.prepare import (
    CLIP_NSIGMA,
    MASK_BKG,
    MASK_HARD,
    MASK_PHOT,
    OVERFLOW,
    bit_mask,
    clipped_stats,
    core_mask,
)
from tombaugh.register import celestial_wcs
from tombaugh.timebins import assign_time_bins
from tombaugh.tools.make_fixture import propagate  # the package's one proper-motion implementation
from tombaugh.types import Cutout, Exposure

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------------- the method
# Aperture, annulus and systematic floor: docs/plan.md, section 5, item 8 ("aperture r = 2 px / 0.96 as
# fallback, 5-9 px annulus, error sqrt(stat^2 + (0.03 F)^2)"), measured in the morning prototype
# science/prototypes/variability_phot.py (R_AP, R_IN, R_OUT) on 14 Nov 2026.
APERTURE_RADIUS_PX = 2.0
ANNULUS_PX = (5.0, 9.0)
SYSTEMATIC_FLOOR = 0.03
NEIGHBOUR_RADIUS_ARCSEC = 15.0  # Contract 7.1: a catalogued neighbour within 15" is fitted or flagged
# Our choice, not a measurement: two point sources closer than about half a native pixel cannot be told apart
# with fixed positions (their models correlate by more than 0.8 for the 7.4 to 9.0 arcsec PSF of prepare.py).
MIN_FIT_SEPARATION_ARCSEC = 3.0
CORE_RADIUS_PX = 1.0  # the core of a source: native pixels whose centre lies within 1 pixel of it
SATURATED_SHARE = 0.5  # "saturated" when the core is blank in more than this share of the exposures seeing it
# "indicative" when the core is blank or carries OVERFLOW in at least this share of the exposures seeing it. Our
# choice after a measurement of 14 Nov 2026: at 3 of 14 empty positions a single exposure of about 215 had a
# blank core (a saturated hit, not a source), which must not label a whole spectrum. Such points stay marked.
INDICATIVE_SHARE = 0.1
# Statistical errors are multiplied by this. Measured on 14 Nov 2026 on 3,117 measurements at 14 empty positions
# of the two recorded fields (at least 25" from 2MASS and AllWISE sources, 15" from CatWISE sources brighter than
# W1 = 17, 10" from any): the robust standard deviation of flux/error was 1.143 before this factor.
ERROR_SCALE = 1.15
MIN_ANNULUS_PIXELS = 20  # as in the prototype (variability_phot.py: "if ann.sum() < 20: return None")
# The background term of a BINNED value, microjansky per detector, in quadrature with its statistical error and
# the 3 percent floor. The local background under a faint source is not known to better than this, and a binned
# value inherits that offset in full (it is the same sky in every exposure of the bin, so it does not average
# down). Measured on 14 Nov 2026 on all 258 real windows of the WISE 0855 field, with this module unchanged
# (a one-off measurement script, not kept in the repository): at the four positions farthest from any
# catalogued source (20 to 25" from every Gaia, CatWISE, 2MASS and AllWISE source) the inverse-variance mean
# of the good points was D1 -15.6 +- 7.4, D2 -22.3 +- 5.9, D3 -24.1 +- 5.3, D4 -21.9 +- 4.8, D5 -34.5 +- 11.2
# and D6 -18.4 +- 18.0 microjansky; at the nine positions at least 18" from catalogued sources, the
# per-detector means scattered from position to position by 16 to 28 microjansky (D1-D4) and 23 to 36 (D5-D6)
# beyond their statistical errors; at 39 positions of a regular grid at least 10" from catalogued sources the
# per-detector medians were -7.4 to +1.0 microjansky. WISE 0855 itself reads -15 to -31 microjansky below 2.4
# micron. Our choice: 25 microjansky on detectors 1-4 and 35 on 5-6. A crowded field is worse (the annulus
# skew below).
BACKGROUND_FLOOR_UJY = {1: 25.0, 2: 25.0, 3: 25.0, 4: 25.0, 5: 35.0, 6: 35.0}
# In a crowded field the annulus holds the light of faint sources and its median sits above the sky between
# them. Each exposure measures by how much (`_Point.background_skew`): the clipped mean minus the clipped
# median of the annulus, times the flux that one unit of background moves the measurement by. A binned value
# carries the size of the weighted mean of these in quadrature too. Measured on 14 Nov 2026 (a one-off
# measurement script, not kept in the repository; aperture method): at the four emptiest positions of the
# Barnard field (10 to 13" from catalogued sources), whose good points read -49 to -241 microjansky on
# average, the median of this term per exposure was +48 to +268 microjansky; at 43 positions at least 10" from
# catalogued sources in the WISE 0855 field, -3 to +5. It is a term of the error, not a correction: it does
# not predict the offsets of the sparse field (correlation +0.05 over those 43 positions).
WINDOW_HALF_PX = 11  # 23 x 23 native pixels: the 9-pixel annulus plus 2 pixels for motion and rounding
READ_WORKERS = 16  # as for a field build (tombaugh.build.READ_WORKERS)
POSITION_STEP_DAYS = 0.1  # positions are computed at the exposure time rounded to this (< 0.003" for Barnard)
# The variance of the median of n normal samples is pi sigma^2 / (2 n) for large n (a standard result of
# statistics: the asymptotic efficiency of the sample median); used for the error of the background.
MEDIAN_VARIANCE_FACTOR = math.pi / 2.0
MAX_CONDITION = 1e4  # a joint fit whose normal matrix is worse conditioned than this is not trusted
EPSF_GRACE_S = 2.0  # how long to wait for point-spread functions in flight once the deadline has passed
# The reader gives the wavelength at the window's read position; it is reused for a source within this many
# pixels of the window centre. Measured on 14 Nov 2026 from the EPSF tables' CWAVE: the wavelength changes by at
# most 0.0004 micron per pixel (detector 3; 0.00003 on detector 6), so the error stays below 0.001 micron, a
# fiftieth of a channel's bandwidth. Further away, remote_fits.wavelength_at is evaluated (30 ms a call).
LAMBDA_REUSE_PX = 2.0

# --------------------------------------------------------------------------- the point-spread function table
# The EPSF extension of a SPHEREx Level-2 file, as read on 14 Nov 2026 from files of all six detectors: a binary
# table, one row per zone of the detector (441 zones of 97.14 x 97.14 pixels; 451 zones of 185.45 x 49.76 pixels
# on detector 3), columns BINX, BINY, XCENTER, YCENTER, XWIDTH, YWIDTH, NSTAR, NEFF_MEAN, CWAVE, CBAND and EPSF
# (1089 doubles, TDIM '(33,33)', "x-fast then y"), header OVSMPX = OVSMPY = 5. Every stamp sums to 1 and peaks
# at index (16, 16); XCENTER and YCENTER are 0-based IMAGE pixels (zone 0 of a 97.14-pixel tiling sits at
# 48.07). CWAVE agrees with the spectral WCS at (XCENTER, YCENTER) to a median 0.0003 to 0.0007 micron on
# detectors 1, 3 and 4 when the coordinates are taken as they are, and worse with x mirrored (detector 4:
# 0.0019 micron): so no flip is applied to the zone centres, although the header says "MWIR pixels flipped on X
# to match SWIR view". Mirroring the stamps of detectors 4 to 6 in x changed the measured flux ratios below by
# 0.0002, so the stamps are not mirrored either.
#
# How a stamp becomes native pixels: an effective PSF already includes the pixel response, so the share of the
# flux in a native pixel is the stamp SAMPLED at the pixel centre. Measured on 14 Nov 2026 on 1,543 exposures of
# four unsaturated field stars (WISE 0855 and Barnard fields, CatWISE positions through the full WCS): sampled
# stamps leave a residual RMS of 1.8 percent of the peak, summing the 5 x 5 cells of a pixel instead leaves 3.5
# percent and is worse in 92 percent of the exposures; the best-fitting position offset is 0.000 pixel (median,
# 0.1-pixel steps). The sampled model puts 1.2 percent too little light between 2 and 3 pixels (flux in a 3-pixel
# aperture over flux in a 2-pixel one, each corrected: 1.012 median; 1.007 to 1.025 by detector).
EPSF_ROW_BYTES = 8752
PSF_SIDE = 33
PSF_OVERSAMPLE = 5
PSF_CENTRE = 16.0  # stamp index of the source position, both axes
_PSF_RADIUS_PX = (PSF_SIDE - 1) / 2.0 / PSF_OVERSAMPLE  # 3.2 native pixels: the stamp's half-width
_PSF_VERSION = re.compile(r"^(l\d[a-z]?-v\d+)")  # "l2b-v27" of "l2b-v27-2026-197"

# Saturation is recognised by these bits on the core (Explanatory Supplement bits, see tombaugh.prepare).
_OVERFLOW = bit_mask(OVERFLOW)

QUALITY_GOOD, QUALITY_FLAGGED, QUALITY_SATURATED = "good", "flagged", "saturated"


class PsfUnavailable(RuntimeError):
    """The point-spread function table of a file could not be read or does not have the measured layout."""


# --------------------------------------------------------------------------------------------- sources
@dataclass(frozen=True)
class Source:
    """A position on the sky, with catalogue astrometry when known.

    ``ra``, ``dec`` (degrees) are the position at ``epoch`` (Julian year). Without ``epoch`` or without a proper
    motion the position is fixed. ``pmra`` includes cos(dec); proper motions are mas/yr, parallax mas (kept for
    the answer: positions are moved by proper motion alone, so the yearly parallax ellipse, at most the parallax,
    is left out: 0.44" for WISE 0855 and 0.55" for Barnard's Star, a tenth of a native pixel).
    """

    ra: float
    dec: float
    epoch: float | None = None
    pmra: float | None = None
    pmdec: float | None = None
    parallax: float | None = None
    catalog: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        if not (math.isfinite(self.ra) and math.isfinite(self.dec) and 0.0 <= self.ra <= 360.0):
            raise ValueError(f"ra must be a finite number of degrees from 0 to 360, got {self.ra!r}")
        if not -90.0 <= self.dec <= 90.0:
            raise ValueError(f"dec must be a number of degrees from -90 to 90, got {self.dec!r}")

    @property
    def moves(self) -> bool:
        """True when the position changes with time: an epoch and a non-zero, finite proper motion."""
        if self.epoch is None:
            return False
        pm = [value for value in (self.pmra, self.pmdec) if value is not None]
        return bool(pm) and all(math.isfinite(v) for v in pm) and any(v != 0.0 for v in pm)

    def position_at_year(self, jyear: float) -> tuple[float, float]:
        """Position (degrees) at a Julian year."""
        if not self.moves:
            return float(self.ra), float(self.dec)
        assert self.epoch is not None
        return propagate(self.ra, self.dec, self.pmra or 0.0, self.pmdec or 0.0, self.epoch, jyear)


def mjd_to_jyear(mjd: float) -> float:
    """Julian year of an MJD (astropy's definition of the Julian epoch)."""
    return float(Time(float(mjd), format="mjd").jyear)


class _Positions:
    """Positions of one source at exposure times, computed once per POSITION_STEP_DAYS."""

    def __init__(self, source: Source) -> None:
        self.source = source
        self._at: dict[int, tuple[float, float]] = {}

    def at(self, mjd: float) -> tuple[float, float]:
        if not self.source.moves:
            return float(self.source.ra), float(self.source.dec)
        step = round(float(mjd) / POSITION_STEP_DAYS)
        found = self._at.get(step)
        if found is None:
            found = self._at[step] = self.source.position_at_year(mjd_to_jyear(step * POSITION_STEP_DAYS))
        return found


def separation_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Angle between two positions (degrees in), arcsec; the haversine form, exact at small separations."""
    p1, p2 = math.radians(dec1), math.radians(dec2)
    dp, dl = p2 - p1, math.radians(ra2 - ra1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return math.degrees(2.0 * math.asin(min(1.0, math.sqrt(a)))) * 3600.0


# ------------------------------------------------------------------------------------- PSF table and library
@dataclass(frozen=True)
class PsfTable:
    """The EPSF table of one detector: zone centres (0-based detector pixels), CWAVE (micron) and stamps.

    ``stamps`` is (zones, 33, 33), indexed [zone, y, x], 5 times oversampled, each summing to 1. A stamp may be
    NaN when only part of a table was recorded (offline tests); such a zone counts as unavailable.
    """

    det: int
    xcenter: np.ndarray
    ycenter: np.ndarray
    cwave: np.ndarray
    stamps: np.ndarray

    def zone(self, x: float, y: float) -> int:
        """Index of the zone whose centre is nearest detector pixel (x, y)."""
        return int(np.argmin((self.xcenter - x) ** 2 + (self.ycenter - y) ** 2))

    def stamp(self, x: float, y: float) -> np.ndarray | None:
        """The stamp of the zone nearest (x, y), oriented like the IMAGE array; None when it is not available."""
        stamp = self.stamps[self.zone(x, y)]
        return stamp if np.isfinite(stamp).all() else None


def _check(condition: bool, what: str) -> None:
    if not condition:
        raise PsfUnavailable(what)


def parse_psf_table(raw: bytes, det: int) -> PsfTable:
    """The table of an EPSF extension: `raw` is its header followed by its data, as stored in the file."""
    header_len = remote_fits._header_end(raw)  # the reader's FITS block helper
    _check(header_len is not None, "no FITS header at the EPSF offset")
    header = fits.Header.fromstring(raw[:header_len].decode("ascii", "replace"))
    _check(str(header.get("XTENSION", "")).strip() == "BINTABLE", "the EPSF extension is not a binary table")
    _check(str(header.get("EXTNAME", "")).strip() == "EPSF", "no EPSF extension at the expected offset")
    _check(str(header.get("DETECTOR", "")).strip() == str(det), "the EPSF table is of another detector")
    _check(header.get("NAXIS1") == EPSF_ROW_BYTES, "EPSF rows have an unexpected width")
    _check(
        header.get("OVSMPX") == PSF_OVERSAMPLE and header.get("OVSMPY") == PSF_OVERSAMPLE, "EPSF oversampling"
    )
    names = [str(header.get(f"TTYPE{i}", "")).strip() for i in range(1, int(header.get("TFIELDS", 0)) + 1)]
    for name in ("XCENTER", "YCENTER", "CWAVE", "EPSF"):
        _check(name in names, f"the EPSF table has no column {name}")
    column = names.index("EPSF") + 1
    _check(
        str(header.get(f"TDIM{column}", "")).replace(" ", "") == f"({PSF_SIDE},{PSF_SIDE})",
        "EPSF stamp shape",
    )
    rows = int(header["NAXIS2"])
    _check(len(raw) >= header_len + rows * EPSF_ROW_BYTES, "the EPSF table is cut short")
    body = raw[header_len : header_len + rows * EPSF_ROW_BYTES]
    body += b"\0" * (-len(body) % remote_fits.BLOCK)
    blob = remote_fits._EMPTY_PRIMARY + raw[:header_len] + body  # behind an empty primary header
    with fits.open(io.BytesIO(blob)) as hdus:
        data = hdus[1].data
        stamps = np.array(data["EPSF"], dtype=np.float64).reshape(rows, PSF_SIDE, PSF_SIDE)
        table = PsfTable(
            det=int(det),
            xcenter=np.array(data["XCENTER"], dtype=np.float64),
            ycenter=np.array(data["YCENTER"], dtype=np.float64),
            cwave=np.array(data["CWAVE"], dtype=np.float64),
            stamps=stamps,
        )
    sums = stamps.sum(axis=(1, 2))
    _check(bool(np.all(np.abs(sums - 1.0) < 1e-3)), "EPSF stamps do not sum to 1")
    return table


def fetch_psf_table(exposure: Exposure, deadline: http.Deadline | None = None) -> PsfTable:
    """The EPSF table of an exposure's file, read from the public bucket in two requests.

    The extension sits just before the last one (WCS-WAVE), so its offset follows from the object size and the
    measured sizes in tombaugh.remote_fits; its header is checked before anything is trusted. Raises
    PsfUnavailable for another layout and http.UpstreamError when the bucket cannot be read.
    """
    det = int(exposure.det)
    _check(det in remote_fits.EPSF_DATA_BYTES, f"no EPSF layout known for detector {det}")
    total = http.get_range(exposure.url, 0, remote_fits.BLOCK, deadline=deadline).total
    _check(total is not None, "the bucket did not state the object size")
    size = remote_fits.EPSF_HEADER_BYTES + remote_fits.EPSF_DATA_BYTES[det]
    start = total - remote_fits.WAVE_HDU_BYTES - size
    _check(start > 0, "the object is too small to hold an EPSF extension")
    raw = http.get_range(exposure.url, start, start + size, deadline=deadline)
    return parse_psf_table(bytes(raw), det)


def psf_key(exposure: Exposure) -> tuple[int, str]:
    """Cache key of an exposure's EPSF table: (detector, processing version such as "l2b-v27")."""
    version = remote_fits.key_version(exposure.key)
    found = _PSF_VERSION.match(version)
    return int(exposure.det), (found.group(1) if found else version)


class PsfLibrary:
    """EPSF tables per (detector, processing version), read once and kept for the life of the process.

    Thread-safe. `fetch` reads one table for an exposure (default: `fetch_psf_table`); pass None for a library
    that only holds tables given to `put` (offline tests).
    """

    def __init__(self, fetch: Callable[[Exposure, http.Deadline | None], PsfTable] | None = fetch_psf_table):
        self._fetch = fetch
        self._lock = threading.Lock()
        self._tables: dict[tuple[int, str], PsfTable] = {}

    def put(self, key: tuple[int, str], table: PsfTable) -> None:
        with self._lock:
            self._tables[key] = table

    def get(self, exposure: Exposure) -> PsfTable | None:
        """The table of an exposure's file if it is held; never fetches."""
        with self._lock:
            return self._tables.get(psf_key(exposure))

    def ensure(self, exposures: Iterable[Exposure], deadline: http.Deadline | None = None) -> dict[str, str]:
        """Read the tables the exposures need and do not have yet, at most 6 at a time.

        Returns {"<det>/<version>": reason} for each table that could not be read. Waits at most until the
        deadline (plus EPSF_GRACE_S for reads in flight).
        """
        wanted: dict[tuple[int, str], Exposure] = {}
        for exposure in exposures:
            key = psf_key(exposure)
            if key not in wanted and self.get(exposure) is None:
                wanted[key] = exposure
        if not wanted or self._fetch is None:
            return {f"{d}/{v}": "not available offline" for d, v in wanted} if wanted else {}
        failures: dict[str, str] = {}
        pool = ThreadPoolExecutor(max_workers=min(6, len(wanted)), thread_name_prefix="tombaugh-psf")
        try:
            jobs = {pool.submit(self._fetch, exposure, deadline): key for key, exposure in wanted.items()}
            timeout = None if deadline is None else deadline.remaining() + EPSF_GRACE_S
            done, _ = wait(jobs, timeout=timeout)
            for job, key in jobs.items():
                name = f"{key[0]}/{key[1]}"
                if job not in done:
                    failures[name] = "deadline"
                    continue
                try:
                    self.put(key, job.result())
                except (http.UpstreamError, PsfUnavailable, ValueError) as exc:
                    failures[name] = f"{type(exc).__name__}: {exc}"[:200]
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return failures


DEFAULT_PSF_LIBRARY = PsfLibrary()


# --------------------------------------------------------------------------------------- pixel geometry
_SUB = 16  # subpixels per axis when computing the overlap of a pixel with the aperture
_SUB_OFFSETS = (np.arange(_SUB) + 0.5) / _SUB - 0.5


def aperture_weights(shape: tuple[int, int], xs: float, ys: float, radius: float) -> np.ndarray:
    """Fraction of each pixel inside a circle of `radius` pixels centred at (xs, ys) (column, row).

    Pixel centres sit at integer coordinates. Each pixel is cut into 16 x 16 subpixels; a subpixel counts when its
    centre is inside the circle.
    """
    h, w = shape
    weights = np.zeros(shape, dtype=np.float64)
    c0, c1 = max(0, math.floor(xs - radius - 1)), min(w, math.ceil(xs + radius + 1) + 1)
    r0, r1 = max(0, math.floor(ys - radius - 1)), min(h, math.ceil(ys + radius + 1) + 1)
    if c0 >= c1 or r0 >= r1:
        return weights
    sx = (np.arange(c0, c1)[:, None] + _SUB_OFFSETS[None, :]) - xs  # (columns, sub)
    sy = (np.arange(r0, r1)[:, None] + _SUB_OFFSETS[None, :]) - ys  # (rows, sub)
    inside = (sy[:, None, :, None] ** 2 + sx[None, :, None, :] ** 2) <= radius * radius
    weights[r0:r1, c0:c1] = inside.mean(axis=(2, 3))
    return weights


def distance_map(shape: tuple[int, int], xs: float, ys: float) -> np.ndarray:
    """Distance in pixels of every pixel centre from (xs, ys) (column, row)."""
    rows, cols = np.indices(shape, dtype=np.float64)
    return np.hypot(cols - xs, rows - ys)


def psf_model(stamp: np.ndarray, shape: tuple[int, int], xs: float, ys: float) -> np.ndarray:
    """Native-pixel image of a unit-flux point source at (xs, ys) (column, row) from an EPSF stamp.

    The stamp is evaluated with a bicubic spline at every native pixel within its reach and normalised so that
    those pixels sum to 1, also where the window cuts them off (so a fitted amplitude is the source's flux).
    """
    reach = _PSF_RADIUS_PX + 0.5
    cols = np.arange(math.floor(xs - reach), math.ceil(xs + reach) + 1)
    rows = np.arange(math.floor(ys - reach), math.ceil(ys + reach) + 1)
    u = PSF_CENTRE + PSF_OVERSAMPLE * (cols - xs)
    v = PSF_CENTRE + PSF_OVERSAMPLE * (rows - ys)
    grid_v, grid_u = np.meshgrid(v, u, indexing="ij")
    box = ndimage.map_coordinates(stamp, [grid_v, grid_u], order=3, mode="constant", cval=0.0)
    total = float(box.sum())
    model = np.zeros(shape, dtype=np.float64)
    if not total > 0.0:
        return model
    box = box / total
    h, w = shape
    r_in = (rows >= 0) & (rows < h)
    c_in = (cols >= 0) & (cols < w)
    if r_in.any() and c_in.any():
        model[np.ix_(rows[r_in], cols[c_in])] = box[np.ix_(r_in, c_in)]
    return model


def pixel_solid_angle(wcs, x: float, y: float) -> float:
    """Solid angle (sr) of the detector pixel at 0-based (x, y), from the full WCS (SIP included)."""
    xs = np.array([x + 0.5, x - 0.5, x, x], dtype=np.float64)
    ys = np.array([y, y, y + 0.5, y - 0.5], dtype=np.float64)
    ra, dec = wcs.all_pix2world(xs, ys, 0)
    cos_dec = math.cos(math.radians(float(np.mean(dec))))
    dra_x = ((ra[0] - ra[1] + 180.0) % 360.0 - 180.0) * cos_dec
    dra_y = ((ra[2] - ra[3] + 180.0) % 360.0 - 180.0) * cos_dec
    area_deg2 = abs(dra_x * (dec[2] - dec[3]) - (dec[0] - dec[1]) * dra_y)
    return area_deg2 * (math.pi / 180.0) ** 2


# ------------------------------------------------------------------------------------- one exposure
@dataclass
class _Point:
    """One exposure's measurement of the target. Flux and errors in microjansky."""

    exposure: Exposure
    lam: float
    dlam: float
    mjd: float
    flux: float
    err_stat: float
    flags: int
    quality: str
    correction: float  # share of the PSF model inside the aperture (divided out only by the aperture method)
    background_skew: float = 0.0  # microjansky: the annulus's clipped mean minus median, as flux (signed)


# Reasons an exposure gives no point (counted in SpectrumStats.skipped).
EDGE = "edge"  # the aperture or the core is not on the detector or not in the window
BLANK_CORE = "blank_core"  # a saturated core: no value on the core
MASKED = "masked"  # a pixel of the aperture has no value, not because of saturation
NO_BACKGROUND = "no_background"  # fewer than MIN_ANNULUS_PIXELS usable annulus pixels
NO_PSF = "no_psf"  # no point-spread function for this exposure
NO_NOISE = "no_noise"  # neither VARIANCE nor the annulus gave a noise
FIT_FAILED = "fit_failed"  # the joint fit had too few pixels or was degenerate
BAD_HEADER = "bad_header"  # the WCS could not be used


def _background(
    image: np.ndarray, flags: np.ndarray | None, dist: np.ndarray
) -> tuple[float, float, int, float] | None:
    """(background MJy/sr, variance of one pixel (MJy/sr)^2, pixels used, skew MJy/sr) from the annulus, or None.

    The background is the 3-sigma-clipped median; the skew is the mean of the values that clipping keeps minus
    that median (positive when faint sources in the annulus raise it; see the notes at BACKGROUND_FLOOR_UJY).
    """
    ring = (dist >= ANNULUS_PX[0]) & (dist <= ANNULUS_PX[1]) & np.isfinite(image)
    if flags is not None:
        clean = ring & ((flags & MASK_BKG) == 0)
        if int(clean.sum()) < MIN_ANNULUS_PIXELS:  # crowded: keep SOURCE pixels, still drop hard defects
            clean = ring & ((flags & MASK_HARD) == 0)
        ring = clean
    if int(ring.sum()) < MIN_ANNULUS_PIXELS:
        return None
    values = image[ring]
    median, sigma, kept = clipped_stats(values)
    if kept < MIN_ANNULUS_PIXELS or not math.isfinite(sigma):
        return None
    inside = values[np.abs(values - median) <= CLIP_NSIGMA * sigma]
    skew = float(inside.mean()) - median if inside.size else 0.0
    return median, sigma * sigma, kept, skew


def _pixel_variance(sky_var: float | None, ring_var: float) -> float:
    """Noise of one pixel, (MJy/sr)^2: the larger of the VARIANCE plane's median and the annulus scatter."""
    candidates = [v for v in (sky_var, ring_var) if v is not None and math.isfinite(v) and v > 0.0]
    return max(candidates) if candidates else math.nan


def _on_detector(cut: Cutout, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    return (
        (cols + cut.x0 >= 0)
        & (cols + cut.x0 < remote_fits.NX)
        & (rows + cut.y0 >= 0)
        & (rows + cut.y0 < remote_fits.NY)
    )


def _measure_exposure(
    cut: Cutout,
    target_radec: tuple[float, float],
    neighbour_radecs: Sequence[tuple[float, float]],
    psf: PsfTable | None,
) -> _Point | str:
    """The target's flux in one exposure, or the reason there is none."""
    image = np.asarray(cut.image, dtype=np.float64)
    flags = None if cut.flags is None else np.asarray(cut.flags).astype(np.int64, copy=False)
    shape = image.shape
    try:
        wcs = celestial_wcs(cut.wcs_header)
        ras = np.array([target_radec[0], *(p[0] for p in neighbour_radecs)], dtype=np.float64)
        decs = np.array([target_radec[1], *(p[1] for p in neighbour_radecs)], dtype=np.float64)
        xd, yd = wcs.all_world2pix(ras, decs, 0, tolerance=1e-6, maxiter=50, quiet=True)
    except (ValueError, ArithmeticError):
        return BAD_HEADER
    xd, yd = np.asarray(xd, dtype=np.float64), np.asarray(yd, dtype=np.float64)
    if not (np.isfinite(xd).all() and np.isfinite(yd).all()):
        return EDGE
    xs, ys = float(xd[0] - cut.x0), float(yd[0] - cut.y0)  # target in window pixels (column, row)
    r = APERTURE_RADIUS_PX
    h, w = shape
    if not (xs - r >= -0.5 and xs + r <= w - 0.5 and ys - r >= -0.5 and ys + r <= h - 0.5):
        return EDGE
    weights = aperture_weights(shape, xs, ys, r)
    in_aperture = weights > 0.0
    rows, cols = np.nonzero(in_aperture)
    if not _on_detector(cut, rows, cols).all():
        return EDGE
    dist = distance_map(shape, xs, ys)
    core = dist <= CORE_RADIUS_PX
    finite = np.isfinite(image)
    if flags is not None:
        if (~finite & core & core_mask(image, flags)).any():
            return BLANK_CORE
        overflow = bool(((flags[core] & _OVERFLOW) != 0).any())
        flags_or = int(np.bitwise_or.reduce(flags[in_aperture])) if in_aperture.any() else 0
        flagged = bool(((flags[in_aperture] & MASK_PHOT) != 0).any())
    else:
        overflow = flagged = False
        flags_or = 0
    if (~finite & core).any():
        return BLANK_CORE if flags is None else MASKED
    background = _background(image, flags, dist)
    if background is None:
        return NO_BACKGROUND
    bkg, ring_var, n_ring, skew = background
    var_pix = _pixel_variance(cut.sky_var, ring_var)
    if not math.isfinite(var_pix):
        return NO_NOISE
    var_bkg = MEDIAN_VARIANCE_FACTOR * ring_var / n_ring
    try:
        omega = pixel_solid_angle(wcs, float(xd[0]), float(yd[0]))
    except (ValueError, ArithmeticError):
        return BAD_HEADER
    to_ujy = omega * 1e12  # MJy/sr x sr = MJy; 1 MJy = 1e12 microjansky

    stamp = None if psf is None else psf.stamp(float(xd[0]), float(yd[0]))
    centre_x, centre_y = (w - 1) / 2.0, (h - 1) / 2.0  # the reader evaluated cut.lam within 0.5 px of here
    if math.hypot(xs - centre_x, ys - centre_y) <= LAMBDA_REUSE_PX:
        lam, dlam = float(cut.lam), float(cut.dlam)
    else:
        lam, dlam = remote_fits.wavelength_at(cut.exposure.det, cut.wcs_header, float(xd[0]), float(yd[0]))
    quality = QUALITY_SATURATED if overflow else (QUALITY_FLAGGED if flagged else QUALITY_GOOD)

    if neighbour_radecs:  # joint fit of the target and its neighbours at fixed positions
        if stamp is None:
            return NO_PSF
        positions = [(xs, ys)] + [
            (float(x - cut.x0), float(y - cut.y0)) for x, y in zip(xd[1:], yd[1:], strict=True)
        ]
        models = []
        region = np.zeros(shape, dtype=bool)
        for k, (px, py) in enumerate(positions):
            source_stamp = stamp if k == 0 else (psf.stamp(px + cut.x0, py + cut.y0) if psf else None)
            if source_stamp is None:
                return NO_PSF
            models.append(psf_model(source_stamp, shape, px, py))
            region |= distance_map(shape, px, py) <= r
        use = region & finite
        if flags is not None:
            use &= (flags & MASK_PHOT) == 0
        n_use = int(use.sum())
        if n_use < len(models) + 3:
            return FIT_FAILED
        design = np.stack([m[use] for m in models], axis=1)
        normal = design.T @ design
        if not np.isfinite(normal).all() or np.linalg.cond(normal) > MAX_CONDITION:
            return FIT_FAILED
        inverse = np.linalg.inv(normal)
        amplitudes = inverse @ (design.T @ (image[use] - bkg))
        gain = inverse @ design.T.sum(axis=1)  # how the fluxes move with the background
        var_flux = var_pix * inverse[0, 0] + var_bkg * gain[0] ** 2
        flux, err = float(amplitudes[0]), math.sqrt(max(var_flux, 0.0))
        correction = float((weights * models[0]).sum())  # reported only: the fit needs no aperture correction
        per_background = abs(float(gain[0]))  # flux moved by one unit of background
    else:  # aperture
        if not finite[in_aperture].all():
            return MASKED
        if stamp is None:
            return NO_PSF
        correction = float((weights * psf_model(stamp, shape, xs, ys)).sum())
        if not correction > 0.0:
            return NO_PSF
        area = float(weights.sum())
        total = float((weights * np.where(finite, image - bkg, 0.0)).sum())
        var_total = var_pix * float((weights * weights).sum()) + var_bkg * area * area
        flux, err = total / correction, math.sqrt(var_total) / correction
        per_background = area / correction
    return _Point(
        exposure=cut.exposure,
        lam=float(lam),
        dlam=float(dlam),
        mjd=float(cut.mjd),
        flux=flux * to_ujy,
        err_stat=err * to_ujy * ERROR_SCALE,
        flags=flags_or,
        quality=quality,
        correction=correction,
        background_skew=skew * per_background * to_ujy,
    )


# ----------------------------------------------------------------------------------------------- the answer
@dataclass
class SpectrumStats:
    """What one measurement did, for logs and reports. Durations in seconds."""

    requested: int = 0
    read: int = 0
    off_detector: int = 0
    failed: int = 0
    timed_out: int = 0
    measured: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    psf_failures: dict[str, str] = field(default_factory=dict)
    seconds: dict[str, float] = field(default_factory=dict)

    def as_log(self) -> dict:
        record = {"event": "spectrum", **self.__dict__}
        record["seconds"] = {name: round(value, 3) for name, value in self.seconds.items()}
        return record


def _error_with_floor(flux: float, err_stat: float) -> float:
    """The statistical error in quadrature with SYSTEMATIC_FLOOR of the flux (Contract 7.1)."""
    return math.hypot(err_stat, SYSTEMATIC_FLOOR * abs(flux))


def _assign_bins(points: Sequence[_Point], mjds_all: Sequence[float], time_bins: Sequence[TimeBin] | None):
    """Time-bin id of each point: the manifest's bin holding its time when given, else Contract section 3."""
    if time_bins:
        ids = []
        for point in points:
            best = min(
                time_bins,
                key=lambda b: max(b.mjd_start - point.mjd, point.mjd - b.mjd_end, 0.0),
            )
            ids.append(int(best.id))
        return ids
    if not points:
        return []
    bins = assign_time_bins(list(mjds_all))
    by_time = {round(m, 6): int(b) for m, b in zip(mjds_all, bins, strict=True)}
    return [by_time[round(point.mjd, 6)] for point in points]


def binned_error(flux: float, err_stat: float, det: int, skew: float = 0.0) -> float:
    """The error of a binned value (microjansky): its statistical error, SYSTEMATIC_FLOOR of the flux, the
    detector's BACKGROUND_FLOOR_UJY and the bin's weighted mean `background_skew`, all in quadrature."""
    return math.sqrt(
        err_stat**2 + (SYSTEMATIC_FLOOR * flux) ** 2 + BACKGROUND_FLOOR_UJY[int(det)] ** 2 + skew**2
    )


def _binned(points: Sequence[_Point], bins: Sequence[int]) -> list[BinnedPoint]:
    """Inverse-variance means of the "good" points per (time bin, wave bin); errors from `binned_error`.

    `lam_min` and `lam_max` are the wave bin's edges (Contract section 4), widened to the members' own
    wavelengths where a point at the target lies just beyond its detector's nominal range.
    """
    edges = {b.id: b for b in presets.wave_bins()}
    groups: dict[tuple[int, int], list[_Point]] = defaultdict(list)
    for point, time_bin in zip(points, bins, strict=True):
        if point.quality == QUALITY_GOOD and point.err_stat > 0.0:
            groups[(time_bin, presets.wave_bin_for(point.exposure.det, point.lam))].append(point)
    out: list[BinnedPoint] = []
    for (time_bin, wave_bin), members in sorted(groups.items()):
        weights = np.array([1.0 / p.err_stat**2 for p in members])
        flux = float((weights * [p.flux for p in members]).sum() / weights.sum())
        lam = float((weights * [p.lam for p in members]).sum() / weights.sum())
        skew = float((weights * [p.background_skew for p in members]).sum() / weights.sum())
        edge = edges[wave_bin]
        err = binned_error(flux, math.sqrt(1.0 / weights.sum()), edge.detector, skew)
        out.append(
            BinnedPoint(
                time_bin=time_bin,
                lam=round(lam, 5),
                lam_min=min(edge.lam_min, round(min(p.lam for p in members), 5)),
                lam_max=max(edge.lam_max, round(max(p.lam for p in members), 5)),
                flux_ujy=round(flux, 2),
                err_ujy=round(err, 2),
                n=len(members),
            )
        )
    return out


def measure_cutouts(
    cutouts: Sequence[Cutout],
    target: Source,
    *,
    neighbours: Sequence[Source] = (),
    snapped_to: SnappedTo | None = None,
    time_bins: Sequence[TimeBin] | None = None,
    psf: PsfLibrary | None = None,
    stats: SpectrumStats | None = None,
) -> SpectrumResponse:
    """The spectrum of `target` from windows already read (pure: no network).

    `cutouts` are windows of native pixels holding the target (`remote_fits.read_window(s)`, flags and levels
    included). `neighbours` are catalogued sources near the target; those within 15 arcsec at the mean epoch are
    fitted jointly with it, or, closer than 3 arcsec or without a point-spread function, reported as not fitted
    (state "contaminated"). `time_bins` are the field's bins (manifest); without them the bins are made from the
    cutouts' times as in Contract section 3. `psf` holds the EPSF tables (default: the process-wide library,
    which must already have them: this function does not fetch). `stats`, when given, is filled in.
    """
    stats = stats if stats is not None else SpectrumStats()
    library = psf if psf is not None else DEFAULT_PSF_LIBRARY
    mjds = [float(cut.mjd) for cut in cutouts]
    mid_year = mjd_to_jyear(float(np.mean(mjds))) if mjds else EPOCH_REF
    target_track = _Positions(target)
    mid_ra, mid_dec = target.position_at_year(mid_year)

    near: list[tuple[Source, float]] = []
    for source in neighbours:
        sra, sdec = source.position_at_year(mid_year)
        sep = separation_arcsec(mid_ra, mid_dec, sra, sdec)
        if sep <= NEIGHBOUR_RADIUS_ARCSEC:
            near.append((source, sep))
    fittable = [(s, sep) for s, sep in near if sep >= MIN_FIT_SEPARATION_ARCSEC]
    any_psf = any(library.get(cut.exposure) is not None for cut in cutouts)
    fit = bool(fittable) and any_psf
    fitted_sources = [s for s, _ in fittable] if fit else []
    tracks = [_Positions(s) for s in fitted_sources]

    points: list[_Point] = []
    skipped: dict[str, int] = defaultdict(int)
    n_blank = n_seen = 0
    for cut in cutouts:
        outcome = _measure_exposure(
            cut,
            target_track.at(cut.mjd),
            [track.at(cut.mjd) for track in tracks],
            library.get(cut.exposure),
        )
        if isinstance(outcome, _Point):
            points.append(outcome)
            n_seen += 1
        else:
            skipped[outcome] += 1
            if outcome == BLANK_CORE:
                n_blank += 1
                n_seen += 1
            elif outcome not in (EDGE, BAD_HEADER):
                n_seen += 1
    stats.measured = len(points)
    stats.skipped = dict(skipped)

    n_overflow = sum(p.quality == QUALITY_SATURATED for p in points)
    unfitted = [s for s, _ in near if s not in fitted_sources]
    if n_seen == 0 or (not points and n_blank == 0):
        state = "no_data"
    elif n_blank > SATURATED_SHARE * n_seen:
        state = "saturated"
    elif n_blank + n_overflow >= max(1.0, INDICATIVE_SHARE * n_seen):
        state = "indicative"
    elif unfitted:
        state = "contaminated"
    else:
        state = "ok"
    if state in ("saturated", "no_data"):
        points = []

    points.sort(key=lambda p: (p.mjd, p.lam))
    bins = _assign_bins(points, mjds, time_bins)
    order = sorted(range(len(points)), key=lambda i: (bins[i], points[i].lam, points[i].mjd))
    points = [points[i] for i in order]
    bins = [bins[i] for i in order]
    corrections = [p.correction for p in points]
    ref_ra, ref_dec = target.position_at_year(EPOCH_REF)
    return SpectrumResponse(
        state=state,
        target=SpectrumTarget(
            ra=round(ref_ra, 7),
            dec=round(ref_dec, 7),
            snapped_to=snapped_to,
            pmra=target.pmra,
            pmdec=target.pmdec,
            parallax=target.parallax,
            epoch=target.epoch,
        ),
        neighbours=[
            Neighbour(catalog=s.catalog, id=s.id, sep_arcsec=round(sep, 2), fitted=s in fitted_sources)
            for s, sep in near
        ],
        method=SpectrumMethod(
            kind="joint_psf" if fitted_sources else "aperture",
            radius_px=APERTURE_RADIUS_PX,
            encircled_energy=round(float(np.median(corrections)), 4) if corrections else 0.0,
            annulus_px=ANNULUS_PX,
            systematic_floor=SYSTEMATIC_FLOOR,
        ),
        time_span=(
            TimeSpan(
                mjd_min=round(min(p.mjd for p in points), 5), mjd_max=round(max(p.mjd for p in points), 5)
            )
            if points
            else None
        ),
        points=[
            SpectrumPoint(
                lam=round(p.lam, 5),
                dlam=round(p.dlam, 5),
                mjd=round(p.mjd, 5),
                det=int(p.exposure.det),
                time_bin=time_bin,
                flux_ujy=round(p.flux, 2),
                err_ujy=round(_error_with_floor(p.flux, p.err_stat), 2),
                flags=int(p.flags),
                quality=p.quality,
            )
            for p, time_bin in zip(points, bins, strict=True)
        ],
        binned=_binned(points, bins) if state not in ("saturated", "no_data") else [],
    )


def measure_with_stats(
    exposures: Sequence[Exposure],
    ra: float,
    dec: float,
    *,
    epoch: float | None = None,
    pmra: float | None = None,
    pmdec: float | None = None,
    parallax: float | None = None,
    snapped_to: SnappedTo | None = None,
    neighbours: Sequence[Source] = (),
    time_bins: Sequence[TimeBin] | None = None,
    deadline: http.Deadline | None = None,
    psf: PsfLibrary | None = None,
    workers: int = READ_WORKERS,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[SpectrumResponse, SpectrumStats]:
    """`measure`, also returning what it did (counts and seconds)."""
    started = time.monotonic()
    target = Source(ra=float(ra), dec=float(dec), epoch=epoch, pmra=pmra, pmdec=pmdec, parallax=parallax)
    todo = list(exposures)
    stats = SpectrumStats(requested=len(todo))
    library = psf if psf is not None else DEFAULT_PSF_LIBRARY
    mid_year = mjd_to_jyear(float(np.mean([e.mjd for e in todo]))) if todo else EPOCH_REF
    window_ra, window_dec = target.position_at_year(mid_year)

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="tombaugh-psf-wait") as side:
        psf_job = side.submit(library.ensure, todo, deadline)
        cutouts, failures = remote_fits.read_windows(
            todo,
            window_ra,
            window_dec,
            WINDOW_HALF_PX,
            workers=workers,
            deadline=deadline,
            progress=progress,
        )
        stats.seconds["read"] = time.monotonic() - started
        stats.psf_failures = psf_job.result()
    stats.seconds["psf_wait"] = time.monotonic() - started - stats.seconds["read"]
    stats.read = len(cutouts)
    for _, reason in failures:
        if reason == remote_fits.OFF_DETECTOR:
            stats.off_detector += 1
        elif reason == remote_fits.DEADLINE:
            stats.timed_out += 1
        else:
            stats.failed += 1
    if todo and not cutouts and stats.failed and not stats.off_detector:
        raise http.UpstreamError(f"none of the {len(todo)} exposures could be read")
    clock = time.monotonic()
    response = measure_cutouts(
        cutouts,
        target,
        neighbours=neighbours,
        snapped_to=snapped_to,
        time_bins=time_bins,
        psf=library,
        stats=stats,
    )
    stats.seconds["measure"] = time.monotonic() - clock
    stats.seconds["total"] = time.monotonic() - started
    log.info("spectrum %s", stats.as_log())
    if (
        stats.psf_failures
        and stats.skipped.get(NO_PSF)
        and not response.points
        and response.state == "no_data"
    ):
        # Not "no coverage": the exposures were there, the point-spread functions could not be read.
        raise http.UpstreamError(f"point-spread function tables could not be read: {stats.psf_failures}")
    return response, stats


def measure(
    exposures: Sequence[Exposure],
    ra: float,
    dec: float,
    *,
    epoch: float | None = None,
    pmra: float | None = None,
    pmdec: float | None = None,
    parallax: float | None = None,
    snapped_to: SnappedTo | None = None,
    neighbours: Sequence[Source] = (),
    time_bins: Sequence[TimeBin] | None = None,
    deadline: http.Deadline | None = None,
    psf: PsfLibrary | None = None,
    workers: int = READ_WORKERS,
    progress: Callable[[int, int], None] | None = None,
) -> SpectrumResponse:
    """Quick-look spectrophotometry of the source at (`ra`, `dec`): the body of Contract section 7.1.

    `exposures` are the field's exposures (discovery, sampled as for the build). `ra`, `dec` are ICRS degrees at
    Julian year `epoch` when a proper motion (`pmra` with cos dec, `pmdec`, mas/yr) is given, else a fixed
    position. `snapped_to` and `parallax` (mas) are passed through to the answer. `neighbours` are catalogued
    sources near the target (the caller queries the catalogues; this module never does). `time_bins` are the
    manifest's bins, so that points carry the field's time-bin ids. One window of 23 x 23 native pixels is read
    per exposure (`remote_fits.read_windows`), and the EPSF table of each detector the first time it is needed.

    `deadline` bounds the reads: what was read when it expires is measured, so fewer points come back. Raises
    ValueError for a position out of range and http.UpstreamError when no exposure could be read at all.
    """
    response, _ = measure_with_stats(
        exposures,
        ra,
        dec,
        epoch=epoch,
        pmra=pmra,
        pmdec=pmdec,
        parallax=parallax,
        snapped_to=snapped_to,
        neighbours=neighbours,
        time_bins=time_bins,
        deadline=deadline,
        psf=psf,
        workers=workers,
        progress=progress,
    )
    return response
