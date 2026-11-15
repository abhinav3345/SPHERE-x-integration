"""Request-minimal reader for SPHEREx Level-2 spectral images in the public S3 bucket.

Layout measured on 48 files (DR1 and QR3, six detectors, pipeline 7.0.5 / l2b-v27), sizes in bytes:

    PRIMARY   header 2880
    IMAGE     header 25920 (D1, D2) or 23040 (D3-D6) + 16,646,400 data (2040 x 2040 float32, big-endian)
    FLAGS     header 17280 + 16,320 row descriptors + Rice heap of 8.4 to 14.7 MB (differs per file)
    VARIANCE  header 11520 + 16,646,400
    ZODI      header 11520 + 16,646,400
    EPSF      header 5760 + 3,862,080 (3,948,480 for D3)
    WCS-WAVE  header 2880 + 2880 (byte-identical for every file of a detector: bundled in tombaugh/data)

So one request for bytes [0, 34560) gives the IMAGE header (the WCS) and, through Content-Range, the object
size; VARIANCE and ZODI are then located from the END of the object. FLAGS takes two requests: its header
with the row descriptors, then the heap bytes of the wanted rows.

A window costs 6 requests cold (head, image rows, FLAGS descriptors, FLAGS heap, ZODI block, VARIANCE
block) and 4 once the per-file metadata is cached; 2 and 1 when only the image is wanted.

No offset is trusted blindly. Every header that is fetched is parsed and checked, and the two offsets
counted from the end are used only when the FLAGS header plus its heap lands exactly on the VARIANCE HDU.
Otherwise, or when the object size is unknown, the reader walks the headers after FLAGS one by one.

Pixel coordinates are 0-based detector pixels (x is the column, y the row); wavelengths are micron.
"""

from __future__ import annotations

import io
import logging
import re
import threading
import time
import warnings
import zlib
from collections import OrderedDict
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning, NoConvergence

from tombaugh import http
from tombaugh.types import Cutout, Exposure

BLOCK = 2880  # FITS block
NX = NY = 2040  # detector pixels
ROW_BYTES = NX * 4  # 8160: one image row of float32
IMAGE_BYTES = NX * NY * 4  # 16,646,400: exactly 5780 blocks
HEAD_BYTES = 34560  # 12 blocks: PRIMARY (1) + IMAGE header (8 or 9) + spare
FLAGS_HEADER_BYTES = 17280
FLAGS_DESC_BYTES = 8 * NY  # 2040 x (int32 length, int32 heap offset)
VARIANCE_HEADER_BYTES = 11520
ZODI_HEADER_BYTES = 11520
EPSF_HEADER_BYTES = 5760
EPSF_DATA_BYTES = {1: 3862080, 2: 3862080, 3: 3948480, 4: 3862080, 5: 3862080, 6: 3862080}
WAVE_HDU_BYTES = 5760  # header 2880 + table 2880: the last bytes of every file

LEVEL_ROWS = 4  # rows of ZODI and of VARIANCE read through the window centre
MAX_HALF_PX = 512
META_CACHE_FILES = 2000
FAR_OFF_PX = 300.0  # further than this outside the detector before distortion: not worth inverting
MAX_WALK_HDUS = 6
MAX_WORKERS = 64
DEADLINE_GRACE_S = 2.0  # how long read_windows waits for requests in flight once the deadline passed
NO_LIMIT_S = 86400.0  # "remaining" time reported to workers when the caller set no deadline

OFF_DETECTOR = "off_detector"  # reasons reported by read_windows
DEADLINE = "deadline"

_DATA_DIR = Path(__file__).resolve().parent / "data"
_EMPTY_PRIMARY = fits.PrimaryHDU().header.tostring().encode("ascii")
_VERSION = re.compile(r"/(l2b-v\d+[A-Za-z0-9_.-]*)/")

# SPHEREx headers make astropy report harmless repairs (date formats, units). Thread-safe to set once here.
warnings.filterwarnings("ignore", category=FITSFixedWarning)


class _DropSipNote(logging.Filter):
    """Drops one astropy INFO line per exposure: SIP terms next to the spectral WCS, which never uses them."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "Inconsistent SIP distortion information" not in record.getMessage()


logging.getLogger("astropy").addFilter(_DropSipNote())


class ReadError(RuntimeError):
    """A file does not have the layout this reader was measured on, so nothing can be read safely."""


# --------------------------------------------------------------------------- FITS helpers
def _require(condition: bool, what: str) -> None:
    if not condition:
        raise ReadError(what)


def _header_end(buf: bytes) -> int | None:
    """Bytes taken by the FITS header at the start of `buf` (whole blocks), or None if END is not in `buf`."""
    for pos in range(0, len(buf) - 79, 80):
        if buf[pos : pos + 3] == b"END" and buf[pos : pos + 80].rstrip() == b"END":
            return (pos // BLOCK + 1) * BLOCK
    return None


def _parse_header(raw: bytes) -> fits.Header:
    """Header from raw FITS header bytes."""
    _require(raw[:9] in (b"SIMPLE  =", b"XTENSION="), "expected a FITS header, found something else")
    return fits.Header.fromstring(raw.decode("ascii", "replace"))


def _data_nbytes(header: fits.Header) -> int:
    """Bytes of the data unit that `header` describes, padded to whole blocks."""
    if header.get("NAXIS", 0) == 0:
        return 0
    size = abs(header["BITPIX"]) // 8
    for axis in range(1, header["NAXIS"] + 1):
        size *= header[f"NAXIS{axis}"]
    size = (size + header.get("PCOUNT", 0)) * header.get("GCOUNT", 1)
    return -(-size // BLOCK) * BLOCK


def _name(header: fits.Header) -> str:
    return str(header.get("EXTNAME", "")).strip()


def _check_plane(header: fits.Header, name: str) -> None:
    """Raise ReadError unless `header` describes an uncompressed 2040 x 2040 float32 image called `name`."""
    shape = (header.get("BITPIX"), header.get("NAXIS"), header.get("NAXIS1"), header.get("NAXIS2"))
    _require(
        str(header.get("XTENSION", "")).strip() == "IMAGE" and _name(header) == name, f"no {name} image HDU"
    )
    _require(shape == (-32, 2, NX, NY), f"{name} is not a {NX} x {NY} float32 image")
    _require(header.get("BSCALE", 1) == 1 and header.get("BZERO", 0) == 0, f"{name} holds scaled values")


def _desc_dtype(header: fits.Header) -> str:
    """numpy dtype of the (length, heap offset) pairs in a compressed-image table: 32 or 64 bit."""
    return ">i8" if str(header.get("TFORM1", "")).lstrip("1").startswith("Q") else ">i4"


def _check_flags(header: fits.Header) -> None:
    """Raise ReadError unless `header` is the FLAGS image, tile-compressed with one tile per image row."""
    _require(
        str(header.get("XTENSION", "")).strip() == "BINTABLE" and _name(header) == "FLAGS", "no FLAGS HDU"
    )
    _require(
        header.get("ZIMAGE", False) is True and header.get("TFIELDS") == 1, "FLAGS is not a compressed image"
    )
    shape = (header.get("ZNAXIS"), header.get("ZNAXIS1"), header.get("ZNAXIS2"), header.get("NAXIS2"))
    _require(shape == (2, NX, NY, NY), f"FLAGS is not a {NX} x {NY} image")
    _require(header.get("ZTILE1", NX) == NX and header.get("ZTILE2", 1) == 1, "FLAGS is not tiled row by row")
    width = 2 * np.dtype(_desc_dtype(header)).itemsize
    _require(header.get("NAXIS1") == width, "FLAGS row descriptors have an unexpected width")


def _fetch(url: str, start: int, end: int, deadline: http.Deadline | None) -> bytes:
    """Exactly the bytes [start, end) of the object; ReadError if the object ends before `end`."""
    buf = http.get_range(url, start, end, deadline=deadline)
    _require(len(buf) == end - start, f"the file ends before byte {end}")
    return buf


def _read_header_at(
    url: str, off: int, guess: int, deadline: http.Deadline | None
) -> tuple[fits.Header, int]:
    """Header that starts at byte `off` and its length in bytes; `guess` is the first read size."""
    size = guess
    for _ in range(4):
        try:
            buf = http.get_range(url, off, off + size, deadline=deadline)
        except http.UpstreamError as exc:
            if exc.status == 416:
                raise ReadError(f"the file ends before byte {off}") from exc
            raise
        length = _header_end(buf)
        if length is not None:
            return _parse_header(buf[:length]), length
        if len(buf) < size:
            break
        size *= 2
    raise ReadError(f"no FITS header found at byte {off}")


# --------------------------------------------------------------------------- per-file metadata
@dataclass(frozen=True)
class _Flags:
    """Where the FLAGS HDU of one file is and how its rows are stored."""

    packed: bytes  # zlib-compressed header bytes followed by the row-descriptor table
    header_len: int  # bytes
    heap_off: int  # byte offset of the heap in the object
    end: int  # byte offset of the first byte after the FLAGS HDU

    def unpack(self) -> tuple[fits.Header, np.ndarray]:
        """The FLAGS header and its (NY, 2) table of (tile length, heap offset), in bytes."""
        raw = zlib.decompress(self.packed)
        header = _parse_header(raw[: self.header_len])
        table = np.frombuffer(raw, dtype=_desc_dtype(header), offset=self.header_len).reshape(-1, 2)
        return header, table.astype(np.int64)


@dataclass(frozen=True)
class _FileMeta:
    """What has been learned about one remote file. Immutable: updates replace the cache entry."""

    total: int | None  # object size in bytes, None when the server did not state it
    packed_header: bytes  # zlib-compressed IMAGE header bytes
    image_off: int  # byte offset of the IMAGE data
    flags: _Flags | None = None
    levels: tuple[int, int] | None = None  # verified byte offsets of the (ZODI, VARIANCE) data

    def header(self) -> fits.Header:
        """A fresh copy of the IMAGE header."""
        return _parse_header(zlib.decompress(self.packed_header))


class _MetaCache:
    """Thread-safe least-recently-used map from object URL to `_FileMeta`."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._lock = threading.Lock()
        self._items: OrderedDict[str, _FileMeta] = OrderedDict()

    def get(self, url: str) -> _FileMeta | None:
        with self._lock:
            meta = self._items.get(url)
            if meta is not None:
                self._items.move_to_end(url)
            return meta

    def put(self, url: str, meta: _FileMeta) -> None:
        with self._lock:
            self._items[url] = meta
            self._items.move_to_end(url)
            while len(self._items) > self._size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


_cache = _MetaCache(META_CACHE_FILES)


def clear_cache() -> None:
    """Forget all per-file metadata (the next window on any file is read cold)."""
    _cache.clear()


def _split_head(buf: bytes) -> tuple[int, int] | None:
    """(length of the PRIMARY header, length of the IMAGE header) if both are complete in `buf`."""
    first = _header_end(buf)
    second = _header_end(buf[first:]) if first is not None else None
    return None if first is None or second is None else (first, second)


def _load_head(exp: Exposure, deadline: http.Deadline | None) -> _FileMeta:
    """Request 1: the first bytes of the object, giving the IMAGE header and the object size."""
    buf = _fetch(exp.url, 0, HEAD_BYTES, deadline)
    lengths = _split_head(buf)
    if lengths is None:  # the headers have grown beyond the measured sizes: read more, once
        buf = _fetch(exp.url, 0, 4 * HEAD_BYTES, deadline)
        lengths = _split_head(buf)
        _require(lengths is not None, "IMAGE header not found at the start of the file")
    primary_len, image_len = lengths
    _require(_data_nbytes(_parse_header(buf[:primary_len])) == 0, "the primary HDU holds data")
    raw = bytes(buf[primary_len : primary_len + image_len])
    header = _parse_header(raw)
    _check_plane(header, "IMAGE")
    detector = str(header.get("DETECTOR", exp.det)).strip()
    _require(detector == str(exp.det), f"the file is from detector {detector}, the listing says {exp.det}")
    return _FileMeta(getattr(buf, "total", None), zlib.compress(raw, 1), primary_len + image_len)


def _file_meta(exp: Exposure, deadline: http.Deadline | None) -> _FileMeta:
    meta = _cache.get(exp.url)
    if meta is None:
        meta = _load_head(exp, deadline)
        _cache.put(exp.url, meta)
    return meta


def _load_flags(url: str, off: int, deadline: http.Deadline | None) -> _Flags:
    """Request 3: the FLAGS header and its row descriptors, from the HDU that starts at byte `off`."""
    buf = _fetch(url, off, off + FLAGS_HEADER_BYTES + FLAGS_DESC_BYTES, deadline)
    header_len = _header_end(buf)
    if header_len is None:  # a longer header than measured: read more, once
        buf = _fetch(url, off, off + 4 * len(buf), deadline)
        header_len = _header_end(buf)
        _require(header_len is not None, "FLAGS header not found after the IMAGE data")
    header = _parse_header(buf[:header_len])
    _check_flags(header)
    desc_len = header["NAXIS1"] * header["NAXIS2"]
    if header_len + desc_len > len(buf):
        buf = _fetch(url, off, off + header_len + desc_len, deadline)
    packed = zlib.compress(bytes(buf[: header_len + desc_len]), 1)
    heap_off = off + header_len + header.get("THEAP", desc_len)
    return _Flags(packed, header_len, heap_off, off + header_len + _data_nbytes(header))


def _with_flags(url: str, meta: _FileMeta, deadline: http.Deadline | None) -> _FileMeta:
    if meta.flags is not None:
        return meta
    meta = replace(meta, flags=_load_flags(url, meta.image_off + IMAGE_BYTES, deadline))
    _cache.put(url, meta)
    return meta


def _levels_from_end(total: int, det: int) -> tuple[int, int]:
    """Byte offsets of the (ZODI, VARIANCE) HDUs counted back from the object size, by the measured layout."""
    zodi_hdu = (
        total - WAVE_HDU_BYTES - EPSF_HEADER_BYTES - EPSF_DATA_BYTES[det] - ZODI_HEADER_BYTES - IMAGE_BYTES
    )
    return zodi_hdu, zodi_hdu - VARIANCE_HEADER_BYTES - IMAGE_BYTES


def _walk_levels(url: str, off: int, total: int | None, deadline: http.Deadline | None) -> tuple[int, int]:
    """Byte offsets of the (ZODI, VARIANCE) data, found by parsing each header from byte `off` on."""
    found: dict[str, int] = {}
    for _ in range(MAX_WALK_HDUS):
        if total is not None and off >= total:
            break
        header, header_len = _read_header_at(url, off, VARIANCE_HEADER_BYTES, deadline)
        if _name(header) in ("ZODI", "VARIANCE"):
            _check_plane(header, _name(header))
            found[_name(header)] = off + header_len
            if len(found) == 2:
                return found["ZODI"], found["VARIANCE"]
        off += header_len + _data_nbytes(header)
    raise ReadError("ZODI and VARIANCE not found after FLAGS")


def _with_levels(exp: Exposure, meta: _FileMeta, deadline: http.Deadline | None) -> _FileMeta:
    """Locate ZODI and VARIANCE: from the end when that agrees with the FLAGS header, else by walking."""
    if meta.levels is not None:
        return meta
    assert meta.flags is not None
    after_flags = meta.flags.end  # exact: it follows from headers that were parsed
    levels = None
    if meta.total is not None and exp.det in EPSF_DATA_BYTES:
        zodi_hdu, variance_hdu = _levels_from_end(meta.total, exp.det)
        if variance_hdu == after_flags:
            levels = (zodi_hdu + ZODI_HEADER_BYTES, variance_hdu + VARIANCE_HEADER_BYTES)
    if levels is None:
        levels = _walk_levels(exp.url, after_flags, meta.total, deadline)
    meta = replace(meta, levels=levels)
    _cache.put(exp.url, meta)
    return meta


# --------------------------------------------------------------------------- window geometry
@dataclass(frozen=True)
class _Window:
    """A square window of 2 * half + 1 pixels centred on detector pixel (xc, yc), which is on the detector."""

    xc: int
    yc: int
    half: int

    @property
    def x0(self) -> int:
        """Detector column of the window's first column (negative when it hangs off the edge)."""
        return self.xc - self.half

    @property
    def y0(self) -> int:
        """Detector row of the window's first row."""
        return self.yc - self.half

    @property
    def side(self) -> int:
        return 2 * self.half + 1

    @property
    def cols(self) -> tuple[int, int]:
        """Half-open range of detector columns the window covers on the detector."""
        return max(self.x0, 0), min(self.x0 + self.side, NX)

    @property
    def rows(self) -> tuple[int, int]:
        """Half-open range of detector rows the window covers on the detector."""
        return max(self.y0, 0), min(self.y0 + self.side, NY)

    def paste(self, detector_rows: np.ndarray, fill: float, dtype: type) -> np.ndarray:
        """Window-shaped array: `detector_rows` (full-width, rows `self.rows`) inside, `fill` elsewhere."""
        (c0, c1), (r0, r1) = self.cols, self.rows
        out = np.full((self.side, self.side), fill, dtype=dtype)
        out[r0 - self.y0 : r1 - self.y0, c0 - self.x0 : c1 - self.x0] = detector_rows[:, c0:c1]
        return out


def _detector_pixel(header: fits.Header, ra: float, dec: float) -> tuple[float, float] | None:
    """0-based detector pixel (x, y) of a sky position through the full WCS with SIP; None if far off."""
    wcs = WCS(header)
    x_lin, y_lin = (float(v) for v in wcs.wcs_world2pix(ra, dec, 0))  # no distortion: a cheap first look
    if not (-FAR_OFF_PX <= x_lin <= NX + FAR_OFF_PX and -FAR_OFF_PX <= y_lin <= NY + FAR_OFF_PX):
        return None  # also taken when either value is NaN (the position is not on this projection)
    try:
        x, y = (float(v) for v in wcs.all_world2pix(ra, dec, 0))
    except NoConvergence as exc:
        raise ReadError("the WCS could not be inverted at this position") from exc
    return (x, y) if np.isfinite(x) and np.isfinite(y) else None


# --------------------------------------------------------------------------- wavelength
_wave_lock = threading.Lock()
_wave_tables: dict[int, fits.BinTableHDU] = {}


def _wave_table(det: int) -> fits.BinTableHDU:
    """The bundled WCS-WAVE lookup table of detector `det`, loaded once per process (call under the lock)."""
    table = _wave_tables.get(det)
    if table is None:
        if det not in EPSF_DATA_BYTES:
            raise ValueError(f"detector must be 1 to 6, got {det!r}")
        table = fits.HDUList.fromstring((_DATA_DIR / f"wcs_wave_D{det}.fits").read_bytes())[1]
        _require(_name(table.header) == "WCS-WAVE", "the bundled wavelength table is damaged")
        _wave_tables[det] = table
    return table


def wavelength_at(det: int, header: fits.Header | str, x: float, y: float) -> tuple[float, float]:
    """Central wavelength and bandwidth, both in micron, at 0-based detector pixel (x, y).

    `header` is the IMAGE header of an exposure of detector `det` (1 to 6), as a Header or as the text in
    `Cutout.wcs_header`. Its tabular spectral WCS (alternate key "W") is evaluated against the lookup
    table bundled for the detector, which is byte-identical in every file of that detector.
    """
    if isinstance(header, str):
        header = fits.Header.fromstring(header, sep="\n")
    with _wave_lock:
        hdus = fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(header=header), _wave_table(det)])
        spectral = WCS(header, fobj=hdus, key="W")
        spectral.sip = None
        lam, dlam = spectral.wcs_pix2world(x, y, 0)
    return float(lam), float(dlam)


# --------------------------------------------------------------------------- planes
def _read_image(url: str, meta: _FileMeta, win: _Window, deadline: http.Deadline | None) -> np.ndarray:
    """Request 2: the window's rows of the IMAGE plane, float32 MJy/sr, NaN off the detector."""
    r0, r1 = win.rows
    buf = _fetch(url, meta.image_off + r0 * ROW_BYTES, meta.image_off + r1 * ROW_BYTES, deadline)
    return win.paste(np.frombuffer(buf, dtype=">f4").reshape(r1 - r0, NX), np.nan, np.float32)


def _decode_tiles(header: fits.Header, lengths: np.ndarray, offsets: np.ndarray, heap: bytes) -> np.ndarray:
    """Image rows from their compressed tiles (one tile per row).

    `lengths` and `offsets` are bytes, the offsets counted from the start of `heap`. The tiles are wrapped
    as a small self-contained compressed-image HDU, which astropy then decodes.
    """
    count = len(lengths)
    small = header.copy()
    small["NAXIS2"] = count
    small["ZNAXIS2"] = count
    small["PCOUNT"] = len(heap)
    for key in ("THEAP", "CHECKSUM", "DATASUM", "ZHECKSUM", "ZDATASUM"):
        small.remove(key, ignore_missing=True)
    table = np.empty((count, 2), dtype=_desc_dtype(header))
    table[:, 0] = lengths
    table[:, 1] = offsets
    body = table.tobytes() + heap
    body += b"\0" * (-len(body) % BLOCK)
    with fits.open(io.BytesIO(_EMPTY_PRIMARY + small.tostring().encode("ascii") + body)) as hdus:
        return np.array(hdus[1].data)


def _read_flags(url: str, flags: _Flags, win: _Window, deadline: http.Deadline | None) -> np.ndarray:
    """Request 4: the window's rows of the FLAGS plane, int32 bit mask, 0 off the detector."""
    header, table = flags.unpack()
    r0, r1 = win.rows
    lengths, offsets = table[r0:r1, 0], table[r0:r1, 1]
    low, high = int(offsets.min()), int((offsets + lengths).max())
    _require(lengths.min() > 0 and low >= 0, "FLAGS row descriptors are not valid")
    _require(high - low <= 2 * (r1 - r0) * ROW_BYTES, "FLAGS rows are not stored together")
    heap = _fetch(url, flags.heap_off + low, flags.heap_off + high, deadline)
    rows = _decode_tiles(header, lengths, offsets - low, heap)
    _require(rows.shape == (r1 - r0, NX), "FLAGS rows decoded to an unexpected shape")
    return win.paste(rows, 0, np.int32)


def _level(url: str, data_off: int, win: _Window, deadline: http.Deadline | None) -> float | None:
    """Requests 5 and 6: median of a plane over the window columns of LEVEL_ROWS rows through the centre."""
    r0 = min(max(win.yc - LEVEL_ROWS // 2, 0), NY - LEVEL_ROWS)
    buf = _fetch(url, data_off + r0 * ROW_BYTES, data_off + (r0 + LEVEL_ROWS) * ROW_BYTES, deadline)
    c0, c1 = win.cols
    block = np.frombuffer(buf, dtype=">f4").reshape(LEVEL_ROWS, NX)[:, c0:c1]
    finite = block[np.isfinite(block)]
    return float(np.median(finite)) if finite.size else None


def _header_float(header: fits.Header, key: str) -> float:
    try:
        return float(header[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReadError(f"the IMAGE header has no usable {key}") from exc


def key_version(key: str) -> str:
    """The processing-version element of an object key, for example "l2b-v27-2026-197"; "" if absent."""
    found = _VERSION.search(key)
    return found.group(1) if found else ""


# --------------------------------------------------------------------------- public readers
def read_window(
    exp: Exposure,
    ra: float,
    dec: float,
    half_px: int,
    *,
    want_flags: bool = True,
    want_levels: bool = True,
    deadline: http.Deadline | None = None,
) -> Cutout | None:
    """A (2 * half_px + 1) squared window of native pixels around a sky position, read from the bucket.

    `ra` and `dec` are ICRS degrees. The window is centred on the detector pixel nearest the position,
    found with the full WCS including SIP. Returns None when that pixel is off the detector. Parts of the
    window beyond the detector edge are NaN in `image` and 0 in `flags`.

    `image` is MJy/sr with the zodiacal light still in it. `lam` and `dlam` (micron) are evaluated at the
    position itself. With `want_levels`, `zodi_level` (MJy/sr) and `sky_var` ((MJy/sr)^2) are medians
    over the window columns of four rows through the window centre. Raises ReadError when the file does
    not have the measured layout and UpstreamError (or DeadlineExceeded) when the bucket cannot be read.
    """
    if not 0 <= half_px <= MAX_HALF_PX:
        raise ValueError(f"half_px must be within 0 to {MAX_HALF_PX}, got {half_px!r}")
    meta = _file_meta(exp, deadline)
    header = meta.header()
    pixel = _detector_pixel(header, ra, dec)
    if pixel is None:
        return None
    x, y = pixel
    xc, yc = round(x), round(y)
    if not (0 <= xc < NX and 0 <= yc < NY):
        return None
    win = _Window(xc, yc, half_px)
    lam, dlam = wavelength_at(exp.det, header, x, y)
    mjd, psf_fwhm = _header_float(header, "MJD-AVG"), _header_float(header, "PSF_FWHM")
    image = _read_image(exp.url, meta, win, deadline)
    flags = zodi = variance = None
    if want_flags or want_levels:  # the FLAGS header also proves where VARIANCE and ZODI are
        meta = _with_flags(exp.url, meta, deadline)
    if want_flags:
        flags = _read_flags(exp.url, meta.flags, win, deadline)
    if want_levels:
        meta = _with_levels(exp, meta, deadline)
        zodi = _level(exp.url, meta.levels[0], win, deadline)
        variance = _level(exp.url, meta.levels[1], win, deadline)
    return Cutout(
        exposure=exp,
        image=image,
        flags=flags,
        x0=win.x0,
        y0=win.y0,
        wcs_header=header.tostring(sep="\n"),
        lam=lam,
        dlam=dlam,
        mjd=mjd,
        psf_fwhm=psf_fwhm,
        zodi_level=zodi,
        sky_var=variance,
        version=key_version(exp.key),
    )


class _Budget(http.Deadline):
    """The caller's deadline, if any, which `read_windows` can also end early to stop its workers."""

    def __init__(self, limit: http.Deadline | None) -> None:
        self._limit = limit
        self._stopped = threading.Event()

    def stop(self) -> None:
        """Expire now: requests in flight finish, no worker starts another."""
        self._stopped.set()

    def remaining(self) -> float:
        if self._stopped.is_set():
            return 0.0
        return NO_LIMIT_S if self._limit is None else self._limit.remaining()

    @property
    def expired(self) -> bool:
        return self._stopped.is_set() or (self._limit is not None and self._limit.expired)


_pools: dict[int, ThreadPoolExecutor] = {}
_pools_lock = threading.Lock()


def _pool(workers: int) -> ThreadPoolExecutor:
    """The long-lived pool of `workers` threads. Its threads keep their HTTP sessions between calls."""
    with _pools_lock:
        pool = _pools.get(workers)
        if pool is None:
            pool = _pools[workers] = ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="tombaugh-read"
            )
        return pool


def _read_one(
    exp: Exposure,
    ra: float,
    dec: float,
    half_px: int,
    want_flags: bool,
    want_levels: bool,
    budget: _Budget,
) -> Cutout | str:
    """`read_window` for a worker thread: the cutout, or the reason there is none."""
    if budget.expired:
        return DEADLINE
    try:
        cutout = read_window(
            exp, ra, dec, half_px, want_flags=want_flags, want_levels=want_levels, deadline=budget
        )
    except http.DeadlineExceeded:
        return DEADLINE
    except http.UpstreamError as exc:
        return f"upstream: {exc}"
    except ReadError as exc:
        return f"unreadable: {exc}"
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the others
        return f"error: {type(exc).__name__}: {exc}"
    return cutout if cutout is not None else OFF_DETECTOR


def read_windows(
    exps: Iterable[Exposure],
    ra: float,
    dec: float,
    half_px: int,
    *,
    workers: int = 16,
    want_flags: bool = True,
    want_levels: bool = True,
    deadline: http.Deadline | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[Cutout], list[tuple[Exposure, str]]]:
    """`read_window` for many exposures on a thread pool, at most `workers` at a time.

    Returns (cutouts, failures), both in the order of `exps`. A failure is (exposure, reason) with reason
    "off_detector", "deadline", or text starting "upstream:", "unreadable:" or "error:". Nothing is raised
    for a single exposure. Once the deadline has expired nothing new is submitted, and what is still in
    flight gets DEADLINE_GRACE_S more before it is reported as "deadline".

    `progress(done, total)` is called in the calling thread after each exposure finishes. An exception
    raised by `progress` stops the read and propagates, which is how a caller cancels. However the call
    ends, no worker starts another request afterwards.

    The threads are kept between calls, so their connections to the bucket stay warm.
    """
    todo = list(exps)
    workers = max(1, min(workers, MAX_WORKERS))
    cutouts: dict[int, Cutout] = {}
    failures: dict[int, str] = {}
    pending: dict[Future[Cutout | str], int] = {}
    submitted = 0
    grace_end: float | None = None
    budget = _Budget(deadline)
    pool = _pool(workers)
    try:
        while True:
            if grace_end is None and budget.expired:
                grace_end = time.monotonic() + DEADLINE_GRACE_S
            while grace_end is None and submitted < len(todo) and len(pending) < workers:
                job = pool.submit(
                    _read_one, todo[submitted], ra, dec, half_px, want_flags, want_levels, budget
                )
                pending[job] = submitted
                submitted += 1
            if not pending:
                break
            if grace_end is not None:
                patience: float | None = max(0.0, grace_end - time.monotonic())
            else:
                patience = None if deadline is None else deadline.remaining()
            finished, _ = wait(pending, timeout=patience, return_when=FIRST_COMPLETED)
            for job in finished:
                index = pending.pop(job)
                outcome = job.result()
                if isinstance(outcome, Cutout):
                    cutouts[index] = outcome
                else:
                    failures[index] = outcome
                if progress is not None:
                    progress(len(cutouts) + len(failures), len(todo))
            if not finished and grace_end is not None and time.monotonic() >= grace_end:
                break
    finally:
        budget.stop()
        for job in pending:
            job.cancel()
    for index in range(len(todo)):
        if index not in cutouts and index not in failures:
            failures[index] = DEADLINE
    return [cutouts[i] for i in sorted(cutouts)], [(todo[i], failures[i]) for i in sorted(failures)]
