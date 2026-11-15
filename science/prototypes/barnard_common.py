"""Common definitions for the motion-bright agent (Barnard's Star, eps Indi Ba/Bb)."""
import os, sys, json, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(SCR, "tools"))
import spx  # noqa: E402

OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

# Gaia DR3 (epoch 2016.0, ICRS), measured by 01_astrometry.py (gea.esac.esa.int TAP)
TARGETS = {
    "barnard": dict(name="Barnard's Star", gaia="Gaia DR3 4472832130942575872", ra=269.44850252543836, dec=4.739420051112412,
                    pmra=-801.5509783684709, pmdec=10362.394206546573, plx=546.975939730948, epoch=2016.0),
    "epsindB": dict(name="eps Indi Ba/Bb", gaia="Gaia DR3 6412596012146801152", ra=331.07645259656397, dec=-56.79381206688221,
                    pmra=3981.97666296105, pmdec=-2466.8318147663504, plx=270.6580324694526, epoch=2016.0),
    "epsindA": dict(name="eps Indi A", gaia="Gaia DR3 6412595290592307840", ra=330.8724078795965, dec=-56.79725466122902,
                    pmra=3966.6605387484133, pmdec=-2536.1919868044724, plx=274.8431415216296, epoch=2016.0),
}
MJD_REF = 61000.0  # 2025-11-21, used to define the FIXED cut-out centre (pure proper motion, no parallax)

FLAGBITS = {0: "TRANSIENT", 1: "OVERFLOW", 2: "SUR_ERROR", 6: "NONFUNC", 7: "DICHROIC", 9: "MISSING_DATA", 10: "HOT", 11: "COLD",
            12: "FULLSAMPLE", 14: "PHANMISS", 15: "NONLINEAR", 17: "PERSIST", 19: "OUTLIER", 20: "CROSSTALK", 21: "SOURCE",
            22: "GHOST", 23: "GHOST_FPA", 24: "GHOST_EXT", 25: "STREAK", 26: "BLOOM", 27: "SNOWBALL", 28: "HALO"}
# bits treated as "bad pixel" when stacking (SOURCE, FULLSAMPLE, HALO, GHOST* are informational -> kept)
BAD_BITS = [0, 1, 2, 6, 7, 9, 10, 11, 14, 15, 17, 19, 25, 26, 27]
BADMASK = int(sum(1 << b for b in BAD_BITS))
DET_RANGE = {1: (0.75, 1.11), 2: (1.10, 1.65), 3: (1.64, 2.44), 4: (2.40, 3.84), 5: (3.81, 4.42), 6: (4.40, 5.01)}


def pos_at(key, mjd, parallax=True):
    t = TARGETS[key]
    return spx.propagate(t["ra"], t["dec"], t["pmra"], t["pmdec"], t["epoch"], mjd, t["plx"] if parallax else 0.0)


def fixed_centre(key):
    ra, dec = pos_at(key, MJD_REF, parallax=False)
    return round(ra, 6), round(dec, 6)


def offset_arcsec(ra, dec, ra0, dec0):
    """(east, north) offset of (ra,dec) from (ra0,dec0) in arcsec (tangent-plane, small angle)."""
    de = (ra - ra0) * np.cos(np.radians(dec0)) * 3600.0
    dn = (dec - dec0) * 3600.0
    return de, dn


def flagnames(v):
    return [FLAGBITS.get(b, f"bit{b}") for b in range(32) if (int(v) >> b) & 1]


def mjd2iso(mjd):
    from astropy.time import Time
    return Time(mjd, format="mjd").isot[:10]


def mad_std(a):
    a = a[np.isfinite(a)]
    if a.size == 0:
        return np.nan
    return 1.4826 * np.median(np.abs(a - np.median(a)))
