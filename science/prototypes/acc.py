"""Instrumented HTTP + FITS-layout helpers for the 'access' agent (research only).

Counts requests / bytes / failures and records per-request latency so that request economy and
throughput can be measured. Does not touch the shared spx cache (own cache dir).
"""
import hashlib
import io
import json
import os
import random
import re
import sys
import threading
import time
import warnings

S = "<scratch>"
sys.path.insert(0, S + "/tools")

import numpy as np  # noqa: E402
import requests  # noqa: E402
from requests.adapters import HTTPAdapter  # noqa: E402
from astropy.io import fits  # noqa: E402
from astropy.wcs import WCS, FITSFixedWarning  # noqa: E402

warnings.simplefilter("ignore", FITSFixedWarning)
warnings.filterwarnings("ignore", message=".*SIP.*")

HERE = os.path.dirname(os.path.abspath(__file__))
MYCACHE = os.path.join(HERE, "cache")
os.makedirs(MYCACHE, exist_ok=True)
BLOCK = 2880
IMG_BYTES = 2040 * 2040 * 4  # 16,646,400 = exactly 5780 FITS blocks


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.req = 0
            self.bytes = 0
            self.errors = []  # (wallclock, what, tag, seconds)
            self.lat = []     # (ttfb_s, total_s, nbytes, fresh_connection, tag, attempt)

    def snapshot(self):
        with self.lock:
            return {"req": self.req, "bytes": self.bytes, "errors": list(self.errors), "lat": list(self.lat)}


STATS = Stats()
_tls = threading.local()
UA = "spherex-access-probe/0.1 (python-requests)"


def session():
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        s.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=4, max_retries=0))
        s.headers["User-Agent"] = UA
        _tls.s = s
        _tls.fresh = True
    return s


def http_get(url, headers=None, params=None, timeout=(10, 60), tries=14, ok=(200, 206), tag="", expect=None):
    """GET with retries. Records ttfb (requests' r.elapsed: send -> headers parsed, includes TCP+TLS setup when
    the connection is new) and total time. `expect` = expected body length (truncation check)."""
    err = None
    for i in range(tries):
        s = session()
        fresh = getattr(_tls, "fresh", True)
        t0 = time.perf_counter()
        try:
            r = s.get(url, headers=headers, params=params, timeout=timeout)
            t1 = time.perf_counter()
            _tls.fresh = False
            if r.status_code in ok:
                n = len(r.content)
                if expect is not None and n != expect and r.status_code == 206:
                    cr = r.headers.get("Content-Range", "")
                    with STATS.lock:
                        STATS.errors.append((time.time(), f"SHORT {n}/{expect} {cr}", tag, t1 - t0))
                    # a short answer at EOF is legitimate; only retry when the server promised more
                    if cr and int(cr.split("/")[0].split("-")[1]) - int(cr.split("/")[0].split()[-1].split("-")[0]) + 1 != n:
                        continue
                with STATS.lock:
                    STATS.req += 1
                    STATS.bytes += n
                    STATS.lat.append((r.elapsed.total_seconds(), t1 - t0, n, fresh, tag, i))
                return r
            err = RuntimeError(f"HTTP {r.status_code} for {url}")
            with STATS.lock:
                STATS.errors.append((time.time(), f"HTTP {r.status_code}", tag, t1 - t0))
            if r.status_code in (400, 403, 404, 416):
                raise err
        except requests.RequestException as e:
            err = e
            _tls.fresh = True
            with STATS.lock:
                STATS.errors.append((time.time(), type(e).__name__ + ": " + repr(e)[:160], tag, time.perf_counter() - t0))
        time.sleep(min(4.0, 0.12 * (1.6 ** i)) + random.random() * 0.15)
    raise err


def get_range(url, start, end, tag=""):
    """Response for bytes [start, end)."""
    return http_get(url, headers={"Range": f"bytes={start}-{end - 1}"}, tag=tag, expect=end - start)


def find_end(buf):
    for pos in range(0, len(buf) - 79, 80):
        if buf[pos:pos + 80].rstrip() == b"END":
            return ((pos + 80 + BLOCK - 1) // BLOCK) * BLOCK
    return None


def total_size(r):
    return int(r.headers["Content-Range"].split("/")[1])


def read_header_at(url, off, guess, tag):
    n = guess
    while True:
        r = get_range(url, off, off + n, tag)
        buf = r.content
        end = find_end(buf)
        if end is not None:
            return fits.Header.fromstring(buf[:end].decode("ascii", "replace")), end, buf, total_size(r)
        if len(buf) < n:
            raise RuntimeError("header END not found before EOF")
        n *= 2


def data_nbytes(h):
    if h.get("NAXIS", 0) == 0:
        return 0
    n = abs(h["BITPIX"]) // 8
    for i in range(1, h["NAXIS"] + 1):
        n *= h[f"NAXIS{i}"]
    n = (n + h.get("PCOUNT", 0)) * h.get("GCOUNT", 1)
    return ((n + BLOCK - 1) // BLOCK) * BLOCK


def key_version(url):
    m = re.search(r"(l\d[a-z]?-v\d+-\d{4}-\d{3})", url)
    return m.group(1) if m else None


def probe_layout(url, want_epsf=False):
    """Walk every HDU of a remote file. Cached as JSON in my own cache dir."""
    key = hashlib.sha1(url.encode()).hexdigest()[:20]
    path = os.path.join(MYCACHE, f"layout_{key}{'_e' if want_epsf else ''}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    out = {"url": url, "keyver": key_version(url), "hdus": []}
    off, i, total = 0, 0, None
    guesses = [34560, 20160, 14400, 14400, 8640, 5760, 5760]
    while True:
        h, hn, buf, total = read_header_at(url, off, guesses[i] if i < len(guesses) else 5760, f"hdr{i}")
        dn = data_nbytes(h)
        name = h.get("EXTNAME", "PRIMARY")
        txt = h.tostring(sep="\n", endcard=False, padding=False)
        e = {"name": name, "hdr_off": off, "hdr_len": hn, "data_off": off + hn, "data_len": dn,
             "ncards": len(h), "hdr_sha1": hashlib.sha1(txt.encode()).hexdigest()[:12], "header": txt}
        if name == "WCS-WAVE" or (name == "EPSF" and want_epsf):
            d = get_range(url, off + hn, off + hn + dn, f"data-{name}").content
            e["data_sha1"] = hashlib.sha1(d).hexdigest()[:16]
            if name == "EPSF":
                # hash only the PSF cube column separately is costly; keep raw bytes hash + save one copy per hash
                p = os.path.join(MYCACHE, f"epsf_{e['data_sha1']}.bin")
                if not os.path.exists(p):
                    with open(p, "wb") as f:
                        f.write(d)
            else:
                p = os.path.join(MYCACHE, f"wave_{e['data_sha1']}.bin")
                if not os.path.exists(p):
                    with open(p, "wb") as f:
                        f.write(buf[:hn] + d)
        out["hdus"].append(e)
        off += hn + dn
        i += 1
        if off >= total or i > 12:
            break
    out["total"] = total
    out["end_off"] = off
    tmp = path + f".{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w") as f:
        json.dump(out, f)
    os.replace(tmp, path)
    return out
