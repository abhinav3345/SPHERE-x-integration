"""Scratch helper for SPHEREx feasibility probes (research only, NOT product code).

Reads small pixel windows of SPHEREx Level-2 spectral images straight from the public
AWS bucket (nasa-irsa-spherex, us-east-1) with HTTP range requests, so a cutout costs
~0.1-2 MB instead of the 4 MB that the IRSA cutout service returns (its EPSF table dominates).

Usage (run with the shared venv):
    import sys; sys.path.insert(0, "<scratchpad>/tools"); import spx
    rows = spx.sia(133.795, -7.245)                    # all DR1 exposures covering the point
    cuts = spx.fetch_many(rows, 133.795, -7.245, half=24, workers=8)
    c = cuts[0]; c["image"], c["flags"], c["variance"], c["zodi"], c["wcs"], c["lam"], c["mjd"]

Every network call retries (this network resets ~50% of new TLS connections) and results
are cached on disk under <scratchpad>/cache so repeated calls are free.
"""
import csv
import hashlib
import io
import json
import os
import random
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import requests
from requests.adapters import HTTPAdapter
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning

warnings.simplefilter("ignore", FITSFixedWarning)
warnings.filterwarnings("ignore", message=".*SIP.*")

S = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(S, "cache")
os.makedirs(CACHE, exist_ok=True)
BLOCK = 2880
PIX_ARCSEC = 6.15
SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
S3_HTTP = "https://{bucket}.s3.{region}.amazonaws.com/{key}"
_tls = threading.local()


def session():
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        s.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=4, max_retries=0))
        s.headers["User-Agent"] = "spherex-feasibility-probe/0.1 (python-requests)"
        _tls.s = s
    return s


def http_get(url, headers=None, params=None, timeout=90, tries=14, ok=(200, 206)):
    """GET with retries on connection resets / 5xx. Raises on 4xx."""
    err = None
    for i in range(tries):
        try:
            r = session().get(url, headers=headers, params=params, timeout=timeout)
            if r.status_code in ok:
                return r
            err = RuntimeError(f"HTTP {r.status_code} for {url}")
            if r.status_code in (400, 403, 404, 416):
                raise err
        except requests.RequestException as e:
            err = e
        time.sleep(min(4.0, 0.12 * (1.6 ** i)) + random.random() * 0.15)
    raise err


def get_range(url, start, end):
    """Bytes [start, end) of a remote object."""
    r = http_get(url, headers={"Range": f"bytes={start}-{end - 1}"})
    return r.content


# --------------------------------------------------------------------------- discovery
def _parse_sia_csv(text):
    rd = csv.reader(io.StringIO(text))
    hdr = next(rd)
    ic = hdr.index("cloud_access")
    out = []
    for r in rd:
        if not r:
            continue
        extra = len(r) - len(hdr)
        if extra > 0:  # IRSA's CSV does not quote the JSON in cloud_access
            r = r[:ic] + [",".join(r[ic:ic + extra + 1])] + r[ic + extra + 1:]
        d = dict(zip(hdr, r))
        d["mjd"] = 0.5 * (float(d["t_min"]) + float(d["t_max"]))
        d["det"] = int(d["energy_bandpassname"][-1])
        try:
            ca = json.loads(d["cloud_access"])["aws"]
            d["s3_url"] = S3_HTTP.format(bucket=ca["bucket_name"], region=ca["region"], key=ca["key"])
        except Exception:
            d["s3_url"] = None
        out.append(d)
    out.sort(key=lambda d: (d["mjd"], d["det"]))
    return out


def sia(ra, dec, radius_deg=0.0005, collection="spherex_dr1", refresh=False):
    """All exposures in `collection` whose footprint covers (ra, dec) [deg, ICRS]."""
    path = os.path.join(CACHE, f"sia_{collection}_{ra:.5f}_{dec:+.5f}_{radius_deg}.csv")
    if refresh or not os.path.exists(path):
        r = http_get(SIA_URL, params={"COLLECTION": collection, "POS": f"circle {ra} {dec} {radius_deg}",
                                      "RESPONSEFORMAT": "csv"}, timeout=240)
        with open(path, "w") as f:
            f.write(r.text)
    with open(path) as f:
        return _parse_sia_csv(f.read())


def epochs(rows, gap_days=20.0):
    """Cluster exposures into visits separated by more than gap_days. Adds row['epoch'] (0-based)."""
    rows = sorted(rows, key=lambda d: d["mjd"])
    e = 0
    for i, d in enumerate(rows):
        if i and d["mjd"] - rows[i - 1]["mjd"] > gap_days:
            e += 1
        d["epoch"] = e
    return rows


# --------------------------------------------------------------------------- remote FITS
def _find_end(buf):
    for pos in range(0, len(buf) - 79, 80):
        if buf[pos:pos + 80].rstrip() == b"END":
            return ((pos + 80 + BLOCK - 1) // BLOCK) * BLOCK
    return None


def _read_header(url, off, guess=11520):
    """Parse the FITS header that starts at byte `off`. Returns (Header, header_nbytes)."""
    n = guess
    while True:
        buf = get_range(url, off, off + n)
        end = _find_end(buf)
        if end is not None:
            return fits.Header.fromstring(buf[:end].decode("ascii", "replace")), end
        if len(buf) < n:
            raise RuntimeError("header END not found before EOF")
        n *= 2


def _data_nbytes(h):
    if h.get("NAXIS", 0) == 0:
        return 0
    n = abs(h["BITPIX"]) // 8
    for i in range(1, h["NAXIS"] + 1):
        n *= h[f"NAXIS{i}"]
    n = (n + h.get("PCOUNT", 0)) * h.get("GCOUNT", 1)
    return ((n + BLOCK - 1) // BLOCK) * BLOCK


def hdu_index(url):
    """Offsets + headers of every HDU in a remote Level-2 file (cached on disk)."""
    key = hashlib.sha1(url.encode()).hexdigest()[:20]
    path = os.path.join(CACHE, f"idx_{key}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    idx, off = [], 0
    guesses = [34560, 20160, 14400, 14400, 8640, 5760]
    for i in range(8):
        try:
            h, hn = _read_header(url, off, guesses[i] if i < len(guesses) else 5760)
        except Exception:
            break
        dn = _data_nbytes(h)
        idx.append({"name": h.get("EXTNAME", "PRIMARY"), "hdr_off": off, "hdr_len": hn, "data_off": off + hn,
                    "data_len": dn, "header": h.tostring(sep="\n", endcard=False, padding=False)})
        off += hn + dn
        if h.get("EXTNAME") == "WCS-WAVE":
            break
    tmp = path + f".{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w") as f:
        json.dump(idx, f)
    os.replace(tmp, path)
    return idx


def _hdr(entry):
    return fits.Header.fromstring(entry["header"], sep="\n")


def _wave_table_hdu(url, idx):
    e = next(x for x in idx if x["name"] == "WCS-WAVE")
    buf = get_range(url, e["hdr_off"], e["data_off"] + e["data_len"])
    return fits.BinTableHDU.fromstring(buf)


def read_rows(url, e, h, y0, y1, nx):
    """Image rows [y0, y1) of one HDU as a 2-D array.

    Plain IMAGE HDUs: one byte-range. Tile-compressed HDUs (FLAGS is RICE_1 with one tile per image row):
    fetch the row descriptors, then the matching heap bytes, wrap them as a tiny self-contained
    compressed-image HDU and let astropy decode it.
    """
    if h.get("ZIMAGE", False):
        if not (h["ZTILE1"] == h["ZNAXIS1"] and h.get("ZTILE2", 1) == 1):
            raise RuntimeError("unsupported tiling")
        rl = h["NAXIS1"]
        tb = get_range(url, e["data_off"] + y0 * rl, e["data_off"] + y1 * rl)
        is_q = "Q" in h["TFORM1"].split("(")[0]
        dt = ">i8" if is_q else ">i4"
        desc = np.frombuffer(tb, dtype=dt).reshape(-1, 2).astype(np.int64)
        lens, offs = desc[:, 0], desc[:, 1]
        theap = h.get("THEAP", h["NAXIS1"] * h["NAXIS2"])
        lo, hi = int(offs.min()), int((offs + lens).max())
        heap = get_range(url, e["data_off"] + theap + lo, e["data_off"] + theap + hi)
        n = y1 - y0
        h2 = h.copy()
        h2["NAXIS2"] = n
        h2["ZNAXIS2"] = n
        h2["PCOUNT"] = hi - lo
        for k in ("THEAP", "CHECKSUM", "DATASUM", "ZHECKSUM", "ZDATASUM"):
            if k in h2:
                del h2[k]
        nd = np.empty((n, 2), dtype=dt)
        nd[:, 0] = lens
        nd[:, 1] = offs - lo
        body = nd.tobytes() + heap
        body += b"\0" * ((-len(body)) % BLOCK)
        raw = fits.PrimaryHDU().header.tostring().encode("ascii") + h2.tostring().encode("ascii") + body
        with fits.open(io.BytesIO(raw)) as hl:
            return np.array(hl[1].data)
    bpp = abs(h["BITPIX"]) // 8
    dt = {-32: ">f4", 32: ">i4", 16: ">i2", -64: ">f8", 64: ">i8"}[h["BITPIX"]]
    buf = get_range(url, e["data_off"] + y0 * nx * bpp, e["data_off"] + y1 * nx * bpp)
    return np.frombuffer(buf, dtype=dt).reshape(y1 - y0, nx)


def cutout(row, ra, dec, half=24, hdus=("IMAGE", "FLAGS", "VARIANCE", "ZODI")):
    """Pixel window of (2*half+1)^2 around (ra, dec) from one exposure.

    Returns dict: image/flags/variance/zodi arrays (NaN / 0 padded off-detector), wcs (celestial, SIP,
    valid for the window), xy (float pixel position of the target inside the window), lam / dlam
    (central wavelength and bandwidth in micron AT THE TARGET PIXEL), lam_map (wavelength per window
    pixel), mjd, det, obs_id, header (IMAGE header), on_detector (bool).
    Cached as .npz. Returns None if the target is off the detector.
    """
    url = row["s3_url"] or row["access_url"]
    tag = hashlib.sha1(f"{url}|{ra:.6f}|{dec:.6f}|{half}|{','.join(hdus)}".encode()).hexdigest()[:20]
    path = os.path.join(CACHE, f"cut_{tag}.npz")
    if os.path.exists(path):
        z = np.load(path, allow_pickle=False)
        d = {k: z[k] for k in z.files}
        meta = json.loads(str(d.pop("meta")))
        if meta.get("off"):
            return None
        hd = fits.Header.fromstring(meta.pop("header"), sep="\n")
        d.update(meta)
        d["header"] = hd
        d["wcs"] = _window_wcs(hd, meta["x0"], meta["y0"])
        return d
    idx = hdu_index(url)
    ent = {e["name"]: e for e in idx}
    hd = _hdr(ent["IMAGE"])
    nx, ny = hd["NAXIS1"], hd["NAXIS2"]
    wfull = WCS(hd)
    x, y = [float(v) for v in wfull.all_world2pix(ra, dec, 0)]
    xi, yi = int(round(x)), int(round(y))
    if not (0 <= xi < nx and 0 <= yi < ny):
        np.savez(path, meta=json.dumps({"off": True}))
        return None
    x0, x1, y0, y1 = xi - half, xi + half + 1, yi - half, yi + half + 1
    cx0, cx1, cy0, cy1 = max(x0, 0), min(x1, nx), max(y0, 0), min(y1, ny)
    out = {}
    for name in hdus:
        e = ent[name]
        h = _hdr(e)
        a = read_rows(url, e, h, cy0, cy1, nx)[:, cx0:cx1]
        if a.dtype.kind == "f":
            full = np.full((2 * half + 1, 2 * half + 1), np.nan, dtype="f4")
        else:
            full = np.zeros((2 * half + 1, 2 * half + 1), dtype="i4")
        full[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0] = a
        out[name.lower()] = full
    # wavelength via the tabular spectral WCS (alternate WCS key "W")
    wt = _wave_table_hdu(url, idx)
    hl = fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(header=hd), wt])
    ws = WCS(hd, fobj=hl, key="W")
    ws.sip = None
    lam, dlam = [float(v) for v in ws.wcs_pix2world(x, y, 0)]
    yy, xx = np.mgrid[y0:y1, x0:x1]
    lam_map, _ = ws.wcs_pix2world(np.clip(xx, 0, nx - 1), np.clip(yy, 0, ny - 1), 0)
    out["lam_map"] = np.asarray(lam_map, dtype="f4")
    meta = {"x0": x0, "y0": y0, "xy": [x - x0, y - y0], "xy_full": [x, y], "lam": lam, "dlam": dlam,
            "mjd": float(hd.get("MJD-AVG", row["mjd"])), "det": int(hd.get("DETECTOR", row["det"])),
            "obs_id": row["obs_id"], "url": url, "psf_fwhm": float(hd.get("PSF_FWHM", "nan")),
            "header": hd.tostring(sep="\n", endcard=False, padding=False)}
    tmp = path + f".{os.getpid()}.{threading.get_ident()}.tmp.npz"
    np.savez(tmp, meta=json.dumps(meta), **out)
    os.replace(tmp, path)
    hdr_txt = meta.pop("header")
    out.update(meta)
    out["header"] = hd
    out["wcs"] = _window_wcs(hd, x0, y0)
    return out


def _window_wcs(hd, x0, y0):
    w = WCS(hd)
    return w[y0:y0 + 10 ** 6, x0:x0 + 10 ** 6] if (x0 >= 0 and y0 >= 0) else _shift_wcs(w, x0, y0)


def _shift_wcs(w, x0, y0):
    w2 = w.deepcopy()
    w2.wcs.crpix = [w.wcs.crpix[0] - x0, w.wcs.crpix[1] - y0]
    if w2.sip is not None:
        from astropy.wcs import Sip
        s = w2.sip
        w2.sip = Sip(s.a, s.b, s.ap, s.bp, [s.crpix[0] - x0, s.crpix[1] - y0])
    return w2


def fetch_many(rows, ra, dec, half=24, workers=8, hdus=("IMAGE", "FLAGS", "VARIANCE", "ZODI"), verbose=True):
    """cutout() for many exposures in parallel (S3 tolerates 8-16 workers). Skips off-detector / failed."""
    t0 = time.time()
    res, fail = [], 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(cutout, r, ra, dec, half, hdus): r for r in rows}
        for i, f in enumerate(as_completed(futs)):
            try:
                c = f.result()
                if c is not None:
                    c["epoch"] = futs[f].get("epoch")
                    res.append(c)
            except Exception as e:  # noqa
                fail += 1
                if verbose:
                    print("  cutout failed:", futs[f]["obs_id"], repr(e)[:120])
    res.sort(key=lambda c: (c["mjd"], c["det"]))
    if verbose:
        print(f"fetched {len(res)} cutouts ({fail} failed, {len(rows) - len(res) - fail} off-detector) in {time.time() - t0:.1f}s")
    return res


# --------------------------------------------------------------------------- small science utils
def sr_per_pixel(wcs=None):
    """Pixel solid angle [sr]. Nominal 6.15 arcsec pixels unless a WCS is given."""
    if wcs is not None:
        from astropy.wcs.utils import proj_plane_pixel_area
        return float(proj_plane_pixel_area(wcs)) * (np.pi / 180.0) ** 2
    return (PIX_ARCSEC / 206264.806) ** 2


def mjysr_to_ujy_per_pix(img, wcs=None):
    return img * 1e12 * sr_per_pixel(wcs)  # MJy/sr * sr = MJy -> 1e12 uJy


def target_grid_wcs(ra, dec, npix=49, pixscale_arcsec=6.15):
    """North-up TAN grid centred on (ra, dec)."""
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(npix + 1) / 2.0, (npix + 1) / 2.0]
    w.wcs.cdelt = [-pixscale_arcsec / 3600.0, pixscale_arcsec / 3600.0]
    return w


def reproject_cut(c, grid_wcs, npix, key="image", order="bilinear"):
    """Reproject one cutout plane onto grid_wcs (surface-brightness units are preserved)."""
    from reproject import reproject_interp
    arr, fp = reproject_interp((c[key].astype("f8"), c["wcs"]), grid_wcs, shape_out=(npix, npix), order=order)
    return arr, fp


def propagate(ra, dec, pmra_masyr, pmdec_masyr, epoch_from_yr, mjd_to, parallax_mas=0.0):
    """Apply proper motion (and optionally parallax, geocentric) from a catalog epoch to an MJD. Degrees in/out."""
    from astropy.coordinates import SkyCoord, Distance, get_body_barycentric
    from astropy.time import Time
    import astropy.units as u
    t1 = Time(mjd_to, format="mjd")
    kw = {}
    if parallax_mas and parallax_mas > 0:
        kw["distance"] = Distance(parallax=parallax_mas * u.mas)
    c = SkyCoord(ra * u.deg, dec * u.deg, pm_ra_cosdec=pmra_masyr * u.mas / u.yr, pm_dec=pmdec_masyr * u.mas / u.yr,
                 obstime=Time(epoch_from_yr, format="jyear"), frame="icrs", **kw)
    c2 = c.apply_space_motion(new_obstime=t1)
    ra2, dec2 = c2.ra.deg, c2.dec.deg
    if parallax_mas and parallax_mas > 0:
        e = get_body_barycentric("earth", t1).xyz.to_value(u.au)
        a, d = np.radians(ra2), np.radians(dec2)
        p = parallax_mas / 3.6e6
        ra2 += p * (e[0] * np.sin(a) - e[1] * np.cos(a)) / np.cos(d)
        dec2 += p * (e[0] * np.cos(a) * np.sin(d) + e[1] * np.sin(a) * np.sin(d) - e[2] * np.cos(d))
    return float(ra2), float(dec2)
