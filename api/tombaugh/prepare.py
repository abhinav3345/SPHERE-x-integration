"""Per-exposure preparation: local background, pixel rejection and the exposure's weight.

Input is a ``Cutout`` in native detector pixels with the zodiacal light still in it. Output is the
background-subtracted image in MJy/sr with NaN at rejected pixels, ready for ``register``.

Flag masks are those of the SPHEREx Explanatory Supplement. The SOURCE bit is never a reason to reject.
Measured on real data: the ZODI model alone leaves residuals as large as the noise, so a local constant is
always subtracted; and a strict mask erases bright stars such as Barnard's Star, hence the core rule below.

The flags do not mark every bad pixel. Measured on the 618 exposures of the two recorded fields (14 Nov
2026), Level-2 images hold single pixels tens to tens of thousands of sigma below the sky, and single hot
pixels, with no bit of ``MASK_STACK`` set. A detector pixel returns to the same sky position whenever a
pointing is repeated, so comparing exposures does not remove them. Three rules that need one exposure only
catch them (``hole_mask``, ``spike_mask``, ``spill_mask``); each blanks pixels that no sky signal can produce
and leaves everything a point source or an extended source can.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from scipy import ndimage

from tombaugh.types import Cutout

# Bit masks (hexadecimal values from the Explanatory Supplement).
MASK_STACK = 0x3FD2CEC5  # pixels left out of stacks
MASK_PHOT = 0x3C028E44  # pixels left out of photometry
MASK_BKG = 0x3C2A8E47  # pixels left out of background estimates (includes SOURCE)

# Bit numbers of the FLAGS image.
TRANSIENT = 0
OVERFLOW = 1
SUR_ERROR = 2
NONFUNC = 6
DICHROIC = 7
MISSING_DATA = 9
HOT = 10
COLD = 11
NONLINEAR = 15
PERSIST = 17
OUTLIER = 19
SOURCE = 21
BLOOM = 26
SNOWBALL = 27
HALO = 28
SATELLITE_HALO = 29

FLAG_BITS: dict[str, int] = {
    "TRANSIENT": TRANSIENT,
    "OVERFLOW": OVERFLOW,
    "SUR_ERROR": SUR_ERROR,
    "NONFUNC": NONFUNC,
    "DICHROIC": DICHROIC,
    "MISSING_DATA": MISSING_DATA,
    "HOT": HOT,
    "COLD": COLD,
    "NONLINEAR": NONLINEAR,
    "PERSIST": PERSIST,
    "OUTLIER": OUTLIER,
    "SOURCE": SOURCE,
    "BLOOM": BLOOM,
    "SNOWBALL": SNOWBALL,
    "HALO": HALO,
    "SATELLITE_HALO": SATELLITE_HALO,
}


def bit_mask(*bit_numbers: int) -> int:
    """The integer mask with the given bit numbers set."""
    mask = 0
    for b in bit_numbers:
        mask |= 1 << int(b)
    return mask


MASK_CORE = bit_mask(OVERFLOW, BLOOM)  # marks a saturated core
MASK_HARD = bit_mask(NONFUNC, MISSING_DATA, HOT, COLD)  # hard defects: the pixel value means nothing
MASK_CORE_WAIVED = bit_mask(TRANSIENT, SUR_ERROR, BLOOM, HALO)  # not a reason to reject next to a core
MASK_STACK_NEAR_CORE = MASK_STACK & ~MASK_CORE_WAIVED

CORE_RADIUS_PX = 3.0  # native pixels around a core pixel where the lenient mask applies
RING_INNER_FRACTION = 0.6  # the background ring starts at 60 percent of the half-width
RING_MIN_FRACTION = 0.3  # below this share of clean ring pixels, fall back to a low percentile
RING_FALLBACK_PERCENTILE = 25.0
CLIP_NSIGMA = 3.0
MAD_TO_SIGMA = 1.4826
HOLE_NSIGMA = 10.0  # a pixel this far below the sky and below its neighbours holds no sky signal
SPIKE_NSIGMA = 15.0  # a lone pixel this far above the sky is tested for being sharper than any source
SPIKE_NEIGHBOUR_SHARE = 0.05  # ... which it is when no direct neighbour reaches this share of it
SPILL_NSIGMA = 100.0  # a rejected pixel this far above the sky spills charge into its direct neighbours

_DIRECT = ((-1, 0), (1, 0), (0, -1), (0, 1))  # (row, column) steps to the four direct neighbours
_AROUND = tuple((dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0))


@dataclass
class Prepared:
    """One exposure ready to register."""

    sci: np.ndarray  # float32 (h, w), MJy/sr, background-subtracted, NaN at rejected or missing pixels
    background: float  # the constant that was subtracted, MJy/sr
    weight: float  # inverse variance of one pixel, (MJy/sr)^-2; 0.0 when the noise is unknown
    n_saturated: int  # number of saturated-core pixels in the window


def clipped_stats(values, nsigma: float = CLIP_NSIGMA, max_iter: int = 10) -> tuple[float, float, int]:
    """Median and robust sigma of the finite values after iterative clipping.

    Each pass drops values farther than ``nsigma`` robust sigmas (1.4826 x MAD) from the median. Returns
    (median, sigma, number of values kept), in the units of the input; (nan, nan, 0) when nothing is finite.
    """
    v = np.asarray(values, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    if v.size == 0:
        return math.nan, math.nan, 0
    median = float(np.median(v))
    sigma = MAD_TO_SIGMA * float(np.median(np.abs(v - median)))
    for _ in range(max_iter):
        if sigma <= 0.0:
            break
        keep = np.abs(v - median) <= nsigma * sigma
        if keep.all():
            break
        v = v[keep]
        median = float(np.median(v))
        sigma = MAD_TO_SIGMA * float(np.median(np.abs(v - median)))
    return median, sigma, int(v.size)


@lru_cache(maxsize=32)
def _ring_mask_cached(shape: tuple[int, int], inner_fraction: float) -> np.ndarray:
    h, w = shape
    half_y, half_x = (h - 1) / 2.0, (w - 1) / 2.0
    rows, cols = np.indices(shape, dtype=np.float64)
    radius = np.hypot((cols - half_x) / max(half_x, 0.5), (rows - half_y) / max(half_y, 0.5))
    mask = radius > inner_fraction
    mask.setflags(write=False)
    return mask


def ring_mask(shape: tuple[int, int], inner_fraction: float = RING_INNER_FRACTION) -> np.ndarray:
    """Mask of the outer ring: pixels farther than ``inner_fraction`` of the half-width from the centre.

    The distance is Euclidean, so the ring includes the corners of the window. The array is read-only.
    """
    return _ring_mask_cached((int(shape[0]), int(shape[1])), float(inner_fraction))


def estimate_background(
    image: np.ndarray, flags: np.ndarray | None, zodi_level: float | None = None
) -> tuple[float, float]:
    """Local background of a window and the robust variance of its ring.

    Returns (background in MJy/sr, variance in (MJy/sr)^2). The variance is NaN when the ring gave no sample.
    Order of preference:
    1. the 3-sigma-clipped median of the finite ring pixels with ``(flags & MASK_BKG) == 0``;
    2. if those are fewer than 30 percent of the ring: the 25th percentile of the finite ring pixels without
       a hard defect (crowded fields, where a median would sit on the sources);
    3. without flags: the clipped median of the finite ring pixels;
    4. with an empty ring: ``zodi_level``, else the clipped median of whatever is finite in the window.
    """
    ring = ring_mask(image.shape)
    finite = np.isfinite(image)
    ring_finite = ring & finite
    n_ring = int(ring.sum())
    use_percentile = False
    if flags is None:
        sample = image[ring_finite]
    else:
        clean = ring_finite & ((flags & MASK_BKG) == 0)
        if n_ring > 0 and int(clean.sum()) >= RING_MIN_FRACTION * n_ring:
            sample = image[clean]
        else:
            sample = image[ring_finite & ((flags & MASK_HARD) == 0)]
            use_percentile = True

    if sample.size == 0:
        if zodi_level is not None and math.isfinite(zodi_level):
            return float(zodi_level), math.nan
        median, _, _ = clipped_stats(image[finite])
        return median, math.nan

    median, sigma, _ = clipped_stats(sample)
    background = (
        float(np.percentile(sample.astype(np.float64), RING_FALLBACK_PERCENTILE))
        if use_percentile
        else median
    )
    return background, sigma * sigma


def core_mask(image: np.ndarray, flags: np.ndarray) -> np.ndarray:
    """Saturated-core pixels: OVERFLOW or BLOOM set, or no value and touching (8-connected) such a pixel."""
    flagged = (flags & MASK_CORE) != 0
    if not flagged.any():
        return flagged
    touching = ndimage.binary_dilation(flagged, structure=np.ones((3, 3), dtype=bool))
    return flagged | (~np.isfinite(image) & touching)


def rejection_mask(image: np.ndarray, flags: np.ndarray, core: np.ndarray | None = None) -> np.ndarray:
    """Pixels to leave out of the stack.

    Within ``CORE_RADIUS_PX`` of a saturated-core pixel TRANSIENT, SUR_ERROR, BLOOM and HALO are not a reason
    to reject (otherwise bright stars vanish); everywhere else any bit of ``MASK_STACK`` rejects. SOURCE
    never rejects.
    """
    if core is None:
        core = core_mask(image, flags)
    strict = (flags & (MASK_STACK & ~bit_mask(SOURCE))) != 0
    if not core.any():
        return strict
    near_core = ndimage.distance_transform_edt(~core) <= CORE_RADIUS_PX
    lenient = (flags & (MASK_STACK_NEAR_CORE & ~bit_mask(SOURCE))) != 0
    return np.where(near_core, lenient, strict)


def _neighbours(sci: np.ndarray, steps: tuple[tuple[int, int], ...]) -> np.ndarray:
    """Each pixel's neighbours at the given (row, column) steps: shape (len(steps), h, w), NaN off the edge."""
    h, w = sci.shape
    padded = np.pad(np.asarray(sci, dtype=np.float64), 1, constant_values=np.nan)
    return np.stack([padded[1 + dr : 1 + dr + h, 1 + dc : 1 + dc + w] for dr, dc in steps])


def _median_of_finite(values: np.ndarray) -> np.ndarray:
    """Median along axis 0 of the finite values; NaN where there is none."""
    count = np.isfinite(values).sum(axis=0)
    ordered = np.sort(values, axis=0)  # NaN sorts to the end
    last = values.shape[0] - 1
    lower = np.clip((count - 1) // 2, 0, last)[None]
    upper = np.clip(count // 2, 0, last)[None]
    median = 0.5 * (
        np.take_along_axis(ordered, lower, axis=0)[0] + np.take_along_axis(ordered, upper, axis=0)[0]
    )
    return np.where(count > 0, median, np.nan)


def hole_mask(sci: np.ndarray, sigma: float) -> np.ndarray:
    """Pixels that read far below the sky, with their eight neighbours: no sky signal is that dark.

    A hole is a valid pixel more than ``HOLE_NSIGMA`` sigma below zero (the sky, once the background is
    subtracted) and also that far below the median of its valid neighbours, or without any valid neighbour.
    The second condition keeps a region that is dark as a whole, such as a background the constant
    over-subtracts: only a pixel that stands out from its surroundings is a defect. Its four direct
    neighbours share its charge (measured: 2 percent each around holes 320 and 385 sigma deep); all eight
    are blanked, which leaves no rim and costs about 0.05 percent of the pixels of the recorded fields.

    ``sci`` is background-subtracted, MJy/sr, NaN at pixels already rejected; ``sigma`` is the noise of one
    pixel, MJy/sr.
    """
    with np.errstate(invalid="ignore"):
        low = sci < -HOLE_NSIGMA * sigma  # NaN compares false
    if not low.any():
        return low
    rows, cols = np.nonzero(low)
    around = _median_of_finite(_neighbours(sci, _AROUND)[:, rows, cols])
    with np.errstate(invalid="ignore"):
        stands_out = ~np.isfinite(around) | (sci[rows, cols] < around - HOLE_NSIGMA * sigma)
    holes = np.zeros(sci.shape, dtype=bool)
    holes[rows[stands_out], cols[stands_out]] = True
    return ndimage.binary_dilation(holes, structure=np.ones((3, 3), dtype=bool))


def spike_mask(sci: np.ndarray, flags: np.ndarray, sigma: float) -> np.ndarray:
    """Lone pixels sharper than any point source: hot pixels and cosmic-ray hits the flags missed.

    A spike is more than ``SPIKE_NSIGMA`` sigma above the sky while each of its four direct neighbours stays
    below ``SPIKE_NEIGHBOUR_SHARE`` of it. The point-spread function is 7.4 to 9.0 arcsec wide (header
    PSF_FWHM), 1.2 to 1.5 native pixels, so a real source leaves far more in a neighbour (measured on 19,000
    peaks of real sources: a tenth of the peak at the 1st percentile). A pixel is judged only when all four
    neighbours are valid, and never when it carries SOURCE.

    ``sci`` is background-subtracted, MJy/sr, NaN at pixels already rejected; ``sigma`` is the noise of one
    pixel, MJy/sr.
    """
    brightest = _neighbours(sci, _DIRECT).max(axis=0)  # NaN as soon as one neighbour is not valid
    with np.errstate(invalid="ignore"):
        lone = (sci > SPIKE_NSIGMA * sigma) & (brightest < SPIKE_NEIGHBOUR_SHARE * sci)
    return lone & ((flags & bit_mask(SOURCE)) == 0)


def spill_mask(
    sci: np.ndarray, flags: np.ndarray, rejected: np.ndarray, core: np.ndarray, sigma: float
) -> np.ndarray:
    """The four direct neighbours of every rejected pixel that reads far above the sky.

    A rejected pixel more than ``SPILL_NSIGMA`` sigma above the sky spills charge into its neighbours
    (measured: 0.4 percent each around a pixel 3,200 sigma above the sky), which carry no rejecting flag
    for it. Next to a star the neighbours hold starlight, so a pixel carrying SOURCE, or within
    ``CORE_RADIUS_PX`` of a saturated core, spills nothing here.

    ``sci`` is background-subtracted, MJy/sr, still holding the values of the rejected pixels; ``sigma`` is
    the noise of one pixel, MJy/sr.
    """
    with np.errstate(invalid="ignore"):
        seeds = rejected & (sci > SPILL_NSIGMA * sigma) & ((flags & bit_mask(SOURCE)) == 0)
    if seeds.any() and core.any():
        seeds &= ndimage.distance_transform_edt(~core) > CORE_RADIUS_PX
    if not seeds.any():
        return seeds
    return ndimage.binary_dilation(seeds, structure=ndimage.generate_binary_structure(2, 1))


def _weight(sky_var: float | None, ring_var: float) -> float:
    """Inverse variance, (MJy/sr)^-2: from the VARIANCE image when positive, else from the ring, else 0.0."""
    if sky_var is not None and math.isfinite(sky_var) and sky_var > 0.0:
        return 1.0 / float(sky_var)
    if math.isfinite(ring_var) and ring_var > 0.0:
        return 1.0 / ring_var
    return 0.0


def prepare(cut: Cutout) -> Prepared:
    """Subtract the local background, blank rejected pixels and weigh one exposure.

    NaN in the input stays NaN: nothing is ever filled in. See ``estimate_background`` and ``rejection_mask``
    for the rules on flags, and ``spill_mask``, ``hole_mask`` and ``spike_mask`` for the pixels the flags
    miss. Those three need the noise of the exposure: with an unknown noise (weight 0.0) none of them
    applies. Without a FLAGS image only holes are blanked, because the other two rely on the SOURCE bit to
    leave catalogued sources alone.
    """
    image = np.asarray(cut.image)
    if image.ndim != 2:
        raise ValueError(f"cutout image must be 2-D, got shape {image.shape}")
    flags = None
    if cut.flags is not None:
        flags = np.asarray(cut.flags).astype(np.int64, copy=False)
        if flags.shape != image.shape:
            raise ValueError(f"flags shape {flags.shape} differs from image shape {image.shape}")

    background, ring_var = estimate_background(image, flags, cut.zodi_level)
    sci = (image.astype(np.float64) - background).astype(np.float32)
    sci[~np.isfinite(sci)] = np.nan
    weight = _weight(cut.sky_var, ring_var)
    sigma = 1.0 / math.sqrt(weight) if weight > 0.0 else math.nan  # noise of one pixel, MJy/sr
    n_saturated = 0
    if flags is not None:
        core = core_mask(image, flags)
        n_saturated = int(core.sum())
        rejected = rejection_mask(image, flags, core)
        if math.isfinite(sigma):
            rejected = rejected | spill_mask(sci, flags, rejected, core, sigma)
        sci[rejected] = np.nan
    if math.isfinite(sigma):
        defects = hole_mask(sci, sigma)
        if flags is not None:
            defects |= spike_mask(sci, flags, sigma)
        sci[defects] = np.nan
    return Prepared(sci=sci, background=float(background), weight=weight, n_saturated=n_saturated)
