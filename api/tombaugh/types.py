"""In-process types shared by the reader, the pipeline and the API (Contract v1, section 9).

The data/backend owner maintains this file. The reader produces `Cutout`s; the pipeline turns them into `StackedPlane`s.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Exposure:
    """One detector image of one SPHEREx pointing, as listed by IRSA SIA."""

    obs_id: str  # e.g. "2025W19_1B_0116_1"
    det: int  # 1..6
    mjd: float  # mid-exposure MJD (UTC) from SIA t_min/t_max
    collection: str  # e.g. "spherex_dr1"
    bucket: str  # "nasa-irsa-spherex"
    region: str  # "us-east-1"
    key: str  # object key in the bucket
    s_region: str = ""  # footprint polygon from SIA (ICRS), may be empty

    @property
    def url(self) -> str:
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{self.key}"

    @property
    def uid(self) -> str:
        return f"{self.obs_id}/D{self.det}"


@dataclass
class Cutout:
    """A pixel window of one exposure in native detector pixels (not yet registered)."""

    exposure: Exposure
    image: np.ndarray  # float32 (h, w), MJy/sr, zodiacal light NOT subtracted, NaN off-detector
    flags: np.ndarray | None  # int32 (h, w) SPHEREx bit mask; None if not fetched
    x0: int  # detector column of image[:, 0] (0-based; may be negative when the window hangs off the edge)
    y0: int  # detector row of image[0, :] (0-based)
    wcs_header: str  # FITS header text of the IMAGE HDU: celestial TAN-SIP WCS in full-detector pixels
    lam: float  # central wavelength at the field centre, micron
    dlam: float  # bandwidth at the field centre, micron
    mjd: float  # MJD-AVG from the header
    psf_fwhm: float  # arcsec, header PSF_FWHM
    zodi_level: float | None = None  # median of the ZODI model over the window, MJy/sr
    sky_var: float | None = None  # median VARIANCE over the window, (MJy/sr)^2
    version: str = ""  # pipeline VERSION keyword if known


@dataclass
class StackedPlane:
    """One (time bin, wave bin) stack on the contract grid, ready to encode into frames.bin."""

    time_bin: int
    wave_bin: int
    data: np.ndarray  # float32 (ny, nx), row 0 north, column 0 east, MJy/sr, NaN = no data
    n_exposures: int
    sigma: float  # robust noise of the plane, MJy/sr
    lam_eff: float  # weighted mean wavelength of the contributing exposures, micron
    mjd_mid: float
    mjd_min: float
    mjd_max: float
