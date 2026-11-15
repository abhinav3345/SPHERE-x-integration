"""Shared constants/helpers for the motion-faint (WISE 0855) probe."""
import sys, os, warnings
warnings.simplefilter("ignore")
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spx
from astropy import log as _alog
_alog.setLevel("ERROR")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = HERE + "/out/"
RA0, DEC0, HALF = 133.7600, -7.2421, 32          # fixed cutout centre (same values as 01_fetch.py -> cache hits)
# SIMBAD (simbad.harvard.edu, 2026-11-14) quoting Kirkpatrick+2021 (2021ApJS..253....7K): ICRS, ep=J2000
RA_J2000 = 15.0 * (8 + 55 / 60.0 + 16.53798 / 3600.0)
DEC_J2000 = -(7 + 14 / 60.0 + 49.3728 / 3600.0)
PMRA, PMDEC, PLX = -8123.7, 673.2, 439.0          # mas/yr, mas/yr, mas
RA_CH, DEC_CH = 133.795129, -7.245147             # challenge coordinates (WISE discovery-era position)
PIX = 6.15
BITS = {0: "TRANSIENT", 1: "OVERFLOW", 2: "SUR_ERROR", 6: "NONFUNC", 7: "DICHROIC", 9: "MISSING_DATA", 10: "HOT",
        11: "COLD", 12: "FULLSAMPLE", 14: "PHANMISS", 15: "NONLINEAR", 17: "PERSIST", 19: "OUTLIER", 20: "CROSSTALK",
        21: "SOURCE", 22: "GHOST", 23: "GHOST_FPA", 24: "GHOST_EXT", 25: "STREAK", 26: "BLOOM", 27: "SNOWBALL", 28: "HALO"}
BAD_BITS = [0, 1, 2, 6, 9, 10, 11, 15, 17, 19, 22, 23, 24, 25, 26, 27]
BADMASK = sum(1 << b for b in BAD_BITS)
SRC = 1 << 21


def predict(mjd):
    return spx.propagate(RA_J2000, DEC_J2000, PMRA, PMDEC, 2000.0, mjd, PLX)


def offset_arcsec(ra, dec, ra_ref, dec_ref):
    """(east, north) offset of (ra,dec) from (ra_ref,dec_ref) in arcsec."""
    return ((ra - ra_ref) * np.cos(np.radians(dec_ref)) * 3600.0, (dec - dec_ref) * 3600.0)
