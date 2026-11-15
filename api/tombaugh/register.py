"""Registration: resample one prepared exposure onto the contract grid (north up, east left).

For every output pixel centre the grid gives (ra, dec); the exposure's full celestial WCS, SIP distortion
included, maps that to native detector pixels; the image is then resampled bilinearly. Good pixels and their
coverage are resampled separately and divided, so a NaN never smears into its neighbours and never counts as
zero. Surface brightness (MJy/sr) is preserved; nothing is sharpened.

The SIP terms of a real SPHEREx header move positions by several native pixels and are never dropped.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from scipy import ndimage
from scipy.interpolate import RectBivariateSpline

from tombaugh.grid import Grid, pixel_centres_sky, pixel_to_sky
from tombaugh.types import Cutout

MIN_COVERAGE = 0.5  # an output pixel needs at least this bilinear weight on good native pixels
LATTICE_STEP_PX = 8  # output pixels between nodes of the coarse mapping lattice
MIN_LATTICE_GRID = 17  # smaller grids are mapped pixel by pixel
WORLD2PIX_TOLERANCE_PX = 1e-6

# Cards of the primary celestial WCS and its SIP distortion. Building the WCS from these alone gives the
# same pixel coordinates as the whole 275-card IMAGE header (checked on real headers) four times faster;
# the alternate WCSes ("A" pixel list, "W" wavelength table) are not needed here.
_WCS_CARD = re.compile(
    r"^(NAXIS[12]?|WCSAXES|CTYPE[12]|CUNIT[12]|CRPIX[12]|CRVAL[12]|CDELT[12]|CROTA[12]"
    r"|PC[12]_[12]|CD[12]_[12]|PV[12]_\d+|LONPOLE|LATPOLE|RADESYS|RADECSYS|EQUINOX"
    r"|[AB]P?_ORDER|[AB]P?_\d+_\d+|[AB]P?_DMAX)\s*="
)
# Lookup-table distortions need the file's extra HDUs, which a header alone cannot supply. SPHEREx Level-2
# images do not use them; a header that does is refused rather than registered without its distortion.
_LOOKUP_DISTORTION_CARD = re.compile(r"^(CPDIS|CQDIS|D2IMDIS)\d")


def _cards(header_text: str) -> list[str]:
    """Split header text into cards: newline-separated, or the raw FITS block of 80-character cards."""
    if "\n" in header_text:
        return [line for line in header_text.split("\n") if line.strip()]
    return [header_text[i : i + 80] for i in range(0, len(header_text), 80)]


def celestial_wcs(header_text: str) -> WCS:
    """Celestial TAN-SIP WCS of an IMAGE header in full-detector pixels (astropy; 0-based with origin=0)."""
    all_cards = _cards(header_text)
    if any(_LOOKUP_DISTORTION_CARD.match(card) for card in all_cards):
        raise ValueError(
            "header uses a lookup-table distortion, which cannot be applied from the header alone"
        )
    cards = [card for card in all_cards if _WCS_CARD.match(card)]
    if not cards:
        raise ValueError("header text holds no celestial WCS cards")
    wcs = WCS(fits.Header.fromstring("\n".join(cards), sep="\n"))
    if wcs.naxis != 2 or not wcs.has_celestial:
        raise ValueError("header does not describe a two-axis celestial WCS")
    declares_sip = any("-SIP" in str(ctype) for ctype in wcs.wcs.ctype)
    if declares_sip and wcs.sip is None:
        raise ValueError("header declares SIP distortion but its coefficients are missing")
    return wcs


def _world_to_detector(wcs: WCS, ra: np.ndarray, dec: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sky (degrees) to 0-based full-detector pixel coordinates through the full WCS, SIP included."""
    x, y = wcs.all_world2pix(ra, dec, 0, tolerance=WORLD2PIX_TOLERANCE_PX, maxiter=50, quiet=True)
    return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)


def _read_only(*arrays: np.ndarray) -> tuple[np.ndarray, ...]:
    for array in arrays:
        array.setflags(write=False)
    return arrays


@lru_cache(maxsize=8)
def _centres(grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    """Sky position (degrees) of every output pixel centre, cached per grid."""
    return _read_only(*pixel_centres_sky(grid))


@lru_cache(maxsize=8)
def _lattice(grid: Grid) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Lattice node positions (output pixels, both axes) and the sky position (degrees) of every node."""
    count = max(4, math.ceil((grid.n - 1) / LATTICE_STEP_PX) + 1)
    nodes = np.linspace(0.0, grid.n - 1.0, count)
    cols, rows = np.meshgrid(nodes, nodes)
    ra, dec = pixel_to_sky(grid, cols, rows)
    return _read_only(nodes, ra, dec)


def native_coordinates(cut: Cutout, grid: Grid, *, direct: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Where each output pixel centre falls in the cutout: (x, y) in window pixels, each of shape (n, n).

    ``x`` indexes columns of ``cut.image`` and ``y`` its rows. By default the WCS is evaluated on a coarse
    lattice (every 8th output pixel) and interpolated with a bicubic spline, which agrees with the direct
    mapping to far better than 0.02 native pixel (see the tests); ``direct=True`` maps every pixel.
    """
    wcs = celestial_wcs(cut.wcs_header)
    x = y = None
    if not direct and grid.n >= MIN_LATTICE_GRID:
        nodes, ra, dec = _lattice(grid)
        x_nodes, y_nodes = _world_to_detector(wcs, ra, dec)
        if np.isfinite(x_nodes).all() and np.isfinite(y_nodes).all():
            every = np.arange(grid.n, dtype=np.float64)
            x = RectBivariateSpline(nodes, nodes, x_nodes, kx=3, ky=3)(every, every)
            y = RectBivariateSpline(nodes, nodes, y_nodes, kx=3, ky=3)(every, every)
    if x is None or y is None:
        ra, dec = _centres(grid)
        x, y = _world_to_detector(wcs, ra, dec)
    return x - cut.x0, y - cut.y0


def register(cut: Cutout, sci: np.ndarray, grid: Grid, *, direct: bool = False) -> np.ndarray:
    """Resample ``sci`` (the prepared image of ``cut``, native pixels, MJy/sr) onto ``grid``.

    Returns a float32 array of shape (n, n), row 0 north and column 0 east, NaN where the bilinear coverage
    by good native pixels is below 0.5 (off the window, masked, or saturated core).
    """
    sci = np.asarray(sci)
    if sci.ndim != 2 or sci.shape != np.shape(cut.image):
        raise ValueError(f"sci shape {sci.shape} differs from the cutout image shape {np.shape(cut.image)}")
    x, y = native_coordinates(cut, grid, direct=direct)
    outside = ~(np.isfinite(x) & np.isfinite(y))
    coords = np.stack([np.where(outside, -10.0, y), np.where(outside, -10.0, x)])

    good = np.isfinite(sci)
    filled = np.where(good, sci, 0.0).astype(np.float64)
    options = {"order": 1, "mode": "constant", "cval": 0.0, "prefilter": False}
    weighted = ndimage.map_coordinates(filled, coords, **options)
    coverage = ndimage.map_coordinates(good.astype(np.float64), coords, **options)

    out = np.full(grid.shape, np.nan, dtype=np.float32)
    covered = coverage >= MIN_COVERAGE
    out[covered] = (weighted[covered] / coverage[covered]).astype(np.float32)
    return out
