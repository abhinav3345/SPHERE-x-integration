"""The sky grid shared by every plane of a field (Contract v1.0, section 2).

A north-up gnomonic (TAN) projection centred on the field centre. Arrays are row-major: row 0 is the
northern edge and column 0 the eastern edge, so ``x`` grows to the west and ``y`` grows to the south.
Pixel centres sit at integer coordinates. This is the only Python implementation of the projection;
``web/src/player/grid.ts`` mirrors it and both are tested against ``docs/contract/vectors/grid.json``.

Units: sky positions in ICRS decimal degrees, pixel scales in arcsec, fields of view in arcmin.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

PIXSCALE_ARCSEC = 3.075  # output pixel, arcsec: half the native SPHEREx pixel
NATIVE_PIXSCALE_ARCSEC = 6.15  # native SPHEREx detector pixel, arcsec
ALLOWED_FOV = (3, 4, 5, 6, 8, 10)  # field sizes the API accepts, arcmin
ARCSEC_PER_RADIAN = 206264.806  # the constant written in the contract; do not "improve" it
SNAP_DECIMALS = 4  # field centres are rounded to 1e-4 deg (0.36 arcsec)
_MIN_COS_DISTANCE = 1e-12  # cos(angle from the centre) below which a position has no gnomonic image


def grid_size(fov_arcmin: float) -> int:
    """Number of pixels along one side of the grid for a field of view in arcmin.

    ``n = 2 * round(fov_arcsec / (2 * 3.075)) + 1``: always odd, so one pixel centre is the field centre.
    Rounds half up, like JavaScript's ``Math.round``. The formula accepts any positive size; the API layer
    is responsible for restricting requests to ``ALLOWED_FOV``.
    """
    fov_arcsec = float(fov_arcmin) * 60.0
    if not math.isfinite(fov_arcsec) or fov_arcsec <= 0.0:
        raise ValueError(f"fov_arcmin must be a positive number, got {fov_arcmin!r}")
    return 2 * math.floor(fov_arcsec / (2.0 * PIXSCALE_ARCSEC) + 0.5) + 1


def snap(ra: float, dec: float) -> tuple[float, float]:
    """Round a requested position (degrees) to the 4-decimal field centre, with ra wrapped into [0, 360)."""
    ra, dec = float(ra), float(dec)
    if not (math.isfinite(ra) and math.isfinite(dec)):
        raise ValueError("ra and dec must be finite numbers")
    if not -90.0 <= dec <= 90.0:
        raise ValueError(f"dec must lie in [-90, 90] degrees, got {dec!r}")
    ra_snapped = round(ra % 360.0, SNAP_DECIMALS) % 360.0  # 359.99996 rounds to 360.0, which is 0.0
    dec_snapped = round(dec, SNAP_DECIMALS)
    return ra_snapped + 0.0, dec_snapped + 0.0  # "+ 0.0" turns -0.0 into 0.0


@dataclass(frozen=True)
class Grid:
    """A field's grid: centre (``ra0``, ``dec0``) in degrees, ``n`` pixels a side, ``pixscale`` in arcsec."""

    ra0: float
    dec0: float
    n: int
    pixscale: float = PIXSCALE_ARCSEC

    def __post_init__(self) -> None:
        if int(self.n) != self.n or self.n < 1 or self.n % 2 == 0:
            raise ValueError(f"grid size must be a positive odd integer, got {self.n!r}")
        if not self.pixscale > 0.0:
            raise ValueError(f"pixscale must be positive, got {self.pixscale!r}")

    @property
    def cx(self) -> int:
        """Column of the pixel whose centre is exactly (ra0, dec0): (n - 1) / 2."""
        return (int(self.n) - 1) // 2

    @property
    def cy(self) -> int:
        """Row of the pixel whose centre is exactly (ra0, dec0): (n - 1) / 2."""
        return (int(self.n) - 1) // 2

    @property
    def shape(self) -> tuple[int, int]:
        """Array shape (ny, nx) of one plane."""
        return (int(self.n), int(self.n))

    @classmethod
    def for_field(cls, ra: float, dec: float, fov_arcmin: float) -> Grid:
        """The contract grid of a request: centre snapped to 4 decimals, size from ``grid_size``."""
        ra0, dec0 = snap(ra, dec)
        return cls(ra0=ra0, dec0=dec0, n=grid_size(fov_arcmin))


def _pixels_per_radian(grid: Grid) -> float:
    return ARCSEC_PER_RADIAN / grid.pixscale


def _unwrap(*values: np.ndarray) -> tuple:
    """Return Python floats for scalar inputs and arrays otherwise."""
    return tuple(float(v) if np.ndim(v) == 0 else v for v in values)


def sky_to_pixel(grid: Grid, ra, dec) -> tuple:
    """Sky position (degrees, scalars or arrays) to grid pixel coordinates (x, y).

    x is the column (0 at the eastern edge), y the row (0 at the northern edge). Positions 90 degrees or
    more from the field centre have no gnomonic image and come back as NaN.
    """
    alpha = np.radians(np.asarray(ra, dtype=np.float64))
    delta = np.radians(np.asarray(dec, dtype=np.float64))
    alpha0, delta0 = math.radians(grid.ra0), math.radians(grid.dec0)
    k = _pixels_per_radian(grid)
    dalpha = alpha - alpha0
    sin_d, cos_d = np.sin(delta), np.cos(delta)
    sin_d0, cos_d0 = math.sin(delta0), math.cos(delta0)
    cos_da = np.cos(dalpha)
    big_d = sin_d0 * sin_d + cos_d0 * cos_d * cos_da
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = cos_d * np.sin(dalpha) / big_d  # east positive
        eta = (cos_d0 * sin_d - sin_d0 * cos_d * cos_da) / big_d  # north positive
    visible = big_d > _MIN_COS_DISTANCE
    x = np.where(visible, grid.cx - k * xi, np.nan)
    y = np.where(visible, grid.cy - k * eta, np.nan)
    return _unwrap(x, y)


def pixel_to_sky(grid: Grid, x, y) -> tuple:
    """Grid pixel coordinates (scalars or arrays) to sky position (ra, dec) in degrees, ra in [0, 360)."""
    alpha0, delta0 = math.radians(grid.ra0), math.radians(grid.dec0)
    k = _pixels_per_radian(grid)
    xi = (grid.cx - np.asarray(x, dtype=np.float64)) / k
    eta = (grid.cy - np.asarray(y, dtype=np.float64)) / k
    rho = np.hypot(xi, eta)
    c = np.arctan(rho)
    sin_c, cos_c = np.sin(c), np.cos(c)
    sin_d0, cos_d0 = math.sin(delta0), math.cos(delta0)
    safe_rho = np.where(rho > 0.0, rho, 1.0)
    sin_delta = cos_c * sin_d0 + np.where(rho > 0.0, eta * sin_c * cos_d0 / safe_rho, 0.0)
    delta = np.arcsin(np.clip(sin_delta, -1.0, 1.0))  # equals delta0 when rho is 0
    alpha = alpha0 + np.arctan2(xi * sin_c, rho * cos_d0 * cos_c - eta * sin_d0 * sin_c)
    ra = np.degrees(alpha) % 360.0
    ra = np.where(ra >= 360.0, 0.0, ra)  # guard the float edge case (-1e-17) % 360 == 360
    return _unwrap(ra, np.degrees(delta))


def pixel_centres_sky(grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    """Sky position of every pixel centre: (ra2d, dec2d) in degrees.

    Both arrays have shape (n, n) and are indexed [row, column].
    """
    rows, cols = np.indices(grid.shape, dtype=np.float64)
    ra, dec = pixel_to_sky(grid, cols, rows)
    return ra, dec


def native_half_window(fov_arcmin: float) -> int:
    """Half-width, in native 6.15 arcsec pixels, of the detector window covering the field at any roll angle.

    ``ceil((fov_arcsec / 2) * sqrt(2) / 6.15) + 2``; the full window is ``2 * half + 1`` pixels a side.
    """
    fov_arcsec = float(fov_arcmin) * 60.0
    if not math.isfinite(fov_arcsec) or fov_arcsec <= 0.0:
        raise ValueError(f"fov_arcmin must be a positive number, got {fov_arcmin!r}")
    return math.ceil((fov_arcsec / 2.0) * math.sqrt(2.0) / NATIVE_PIXSCALE_ARCSEC) + 2
