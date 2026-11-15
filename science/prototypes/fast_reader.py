"""Request-minimal SPHEREx Level-2 window reader (tested snippet, research code).

Layout facts measured in q1_layout.py over 48 files (DR1 + QR3, 6 detectors, pipeline 7.0.5 / l2b-v27):
  PRIMARY hdr 2880 | IMAGE hdr 25920 (D1,D2) or 23040 (D3-D6) + 16,646,400 data | FLAGS hdr 17280 +
  RICE heap (8.4-14.7 MB, varies per file) | VARIANCE hdr 11520 + 16,646,400 | ZODI hdr 11520 + 16,646,400 |
  EPSF hdr 5760 + 3,862,080 (3,948,480 for D3) | WCS-WAVE hdr 2880 + 2880.
So: one request for bytes [0, 34560) yields the IMAGE header (WCS) AND the total size (Content-Range), and
VARIANCE / ZODI offsets follow from the END of the file.  FLAGS needs 2 requests (header + row descriptors,
then the heap bytes of the wanted rows).  WCS-WAVE and EPSF are byte-identical per detector -> cache once.

Requests per exposure: 6 cold (head, image, flags x2, variance, zodi); 2 for a movie frame (head, image);
with a per-file metadata cache: 4 / 1.
"""
import io
import os
import sys

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acc  # noqa: E402

HEAD_N = 34560            # 12 blocks: PRIMARY (1) + IMAGE header (8 or 9) + 2 spare
NX = NY = 2040
ROW = NX * 4              # 8160 bytes per image row
IMG = acc.IMG_BYTES
FLAGS_HDR, VAR_HDR, ZODI_HDR, EPSF_HDR, WAVE_HDR, WAVE_DATA = 17280, 11520, 11520, 5760, 2880, 2880
EPSF_DATA = {1: 3862080, 2: 3862080, 3: 3948480, 4: 3862080, 5: 3862080, 6: 3862080}
DESC = 8 * NY             # FLAGS row descriptors: 2040 x (int32 length, int32 offset)


def head(url):
    """1 request: IMAGE header + total size."""
    r = acc.get_range(url, 0, HEAD_N, "head")
    buf = r.content
    T = acc.total_size(r)
    e0 = acc.find_end(buf)
    e1 = acc.find_end(buf[e0:]) if e0 else None
    if e1 is None:  # header grew beyond the guess: fall back to a bigger read
        r = acc.get_range(url, 0, 4 * HEAD_N, "head-retry")
        buf = r.content
        e0 = acc.find_end(buf)
        e1 = acc.find_end(buf[e0:])
    hd = fits.Header.fromstring(buf[e0:e0 + e1].decode("ascii", "replace"))
    return {"T": T, "H0": e0, "H1": e1, "hdr": hd}


def offsets(meta, det):
    img = meta["H0"] + meta["H1"]
    F = img + IMG
    Z = meta["T"] - (WAVE_HDR + WAVE_DATA) - (EPSF_HDR + EPSF_DATA[det]) - (ZODI_HDR + IMG)
    V = Z - (VAR_HDR + IMG)
    return {"IMAGE": img, "FLAGS_HDU": F, "VAR_HDU": V, "VARIANCE": V + VAR_HDR, "ZODI": Z + ZODI_HDR,
            "EPSF_HDU": Z + ZODI_HDR + IMG, "WAVE_HDU": meta["T"] - WAVE_HDR - WAVE_DATA}


def plane_rows(url, data_off, y0, y1, tag):
    """1 request: full-width rows [y0, y1) of an uncompressed float32 plane."""
    buf = acc.get_range(url, data_off + y0 * ROW, data_off + y1 * ROW, tag).content
    return np.frombuffer(buf, dtype=">f4").reshape(y1 - y0, NX)


def flags_desc(url, F):
    """1 request: FLAGS header + the whole row-descriptor table (33.6 kB). Cacheable per file."""
    buf = acc.get_range(url, F, F + FLAGS_HDR + DESC, "flagsdesc").content
    e = acc.find_end(buf)
    h = fits.Header.fromstring(buf[:e].decode("ascii", "replace"))
    if e != FLAGS_HDR:
        buf = acc.get_range(url, F, F + e + DESC, "flagsdesc-retry").content
    desc = np.frombuffer(buf[e:e + DESC], dtype=">i4").reshape(-1, 2).astype(np.int64)
    return h, e, desc


def flags_heap(url, F, h, e, desc, y0, y1):
    """1 request: compressed bytes of rows [y0, y1). Returns raw pieces (decode separately to time it)."""
    lens, offs = desc[y0:y1, 0], desc[y0:y1, 1]
    theap = h.get("THEAP", h["NAXIS1"] * h["NAXIS2"])
    lo, hi = int(offs.min()), int((offs + lens).max())
    heap = acc.get_range(url, F + e + theap + lo, F + e + theap + hi, "flagsheap").content
    return lens, offs - lo, heap


def flags_decode(h, lens, offs, heap):
    """Wrap the row descriptors + heap as a tiny tile-compressed HDU and let astropy decode it."""
    n = len(lens)
    h2 = h.copy()
    h2["NAXIS2"] = n
    h2["ZNAXIS2"] = n
    h2["PCOUNT"] = len(heap)
    for k in ("THEAP", "CHECKSUM", "DATASUM", "ZHECKSUM", "ZDATASUM"):
        if k in h2:
            del h2[k]
    nd = np.empty((n, 2), dtype=">i4")
    nd[:, 0] = lens
    nd[:, 1] = offs
    body = nd.tobytes() + heap
    body += b"\0" * ((-len(body)) % acc.BLOCK)
    raw = fits.PrimaryHDU().header.tostring().encode("ascii") + h2.tostring().encode("ascii") + body
    with fits.open(io.BytesIO(raw)) as hl:
        return np.array(hl[1].data)


def window(row, ra, dec, half=24, planes=("IMAGE", "FLAGS", "VARIANCE", "ZODI"), meta=None, fdesc=None):
    """Cutout of (2*half+1)^2 pixels. Returns dict or None (off detector)."""
    url = row["s3_url"]
    det = row["det"]
    if meta is None:
        meta = head(url)
    hd = meta["hdr"]
    w = WCS(hd)
    x, y = [float(v) for v in w.all_world2pix(ra, dec, 0)]
    xi, yi = int(round(x)), int(round(y))
    if not (0 <= xi < NX and 0 <= yi < NY):
        return None
    x0, x1, y0, y1 = xi - half, xi + half + 1, yi - half, yi + half + 1
    cx0, cx1, cy0, cy1 = max(x0, 0), min(x1, NX), max(y0, 0), min(y1, NY)
    off = offsets(meta, det)
    out = {"x0": x0, "y0": y0, "xy": (x - x0, y - y0), "hdr": hd, "meta": meta, "det": det,
           "mjd": float(hd["MJD-AVG"]), "check_V": None}
    n = 2 * half + 1
    for name in planes:
        if name == "FLAGS":
            if fdesc is None:
                fdesc = flags_desc(url, off["FLAGS_HDU"])
            fh, fe, desc = fdesc
            out["check_V"] = (off["FLAGS_HDU"] + fe + acc.data_nbytes(fh) == off["VAR_HDU"])
            lens, offs, heap = flags_heap(url, off["FLAGS_HDU"], fh, fe, desc, cy0, cy1)
            a = flags_decode(fh, lens, offs, heap)[:, cx0:cx1]
            full = np.zeros((n, n), dtype="i4")
            out["fdesc"] = fdesc
        else:
            a = plane_rows(url, off[name], cy0, cy1, name.lower())[:, cx0:cx1]
            full = np.full((n, n), np.nan, dtype="f4")
        full[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0] = a
        out[name.lower()] = full
    return out
