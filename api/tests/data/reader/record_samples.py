"""Record the real samples that the offline reader tests replay, and bundle the wavelength tables.

Needs the network (IRSA and the public SPHEREx bucket). Run once by hand from the `api` folder:

    uv run python tests/data/reader/record_samples.py

It writes, next to this script:
    sia_excerpt.csv   the header line and 8 rows of a real SIA answer, byte for byte
    exposure.json     the one exposure the reader samples come from, and the request that was made
    ranges.npz        every byte range the reader asked for, keyed "<start>_<end>"
    expected.npz      the same window obtained by an independent route (see `independent_window`)
and into tombaugh/data: wcs_wave_D1.fits ... wcs_wave_D6.fits, the per-detector WCS-WAVE lookup tables.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from scipy.optimize import fsolve

from tombaugh import discovery, http
from tombaugh import remote_fits as rf
from tombaugh.types import Exposure

HERE = Path(__file__).resolve().parent
BUNDLE = Path(rf.__file__).resolve().parent / "data"
RA, DEC = 133.7599, -7.2418  # the contract's example field
HALF_PX = 8
COLLECTION = "spherex_dr1"
EXCERPT_ROWS = 8
CHUNK = 8 * 1024 * 1024


def sia_text() -> str:
    """The raw CSV answer of IRSA SIA for the example field."""
    params = {"COLLECTION": COLLECTION, "POS": f"circle {RA:.6f} {DEC:.6f} 0.010000", "RESPONSEFORMAT": "csv"}
    return http.get(discovery.SIA_URL, params=params).content.decode("utf-8")


def excerpt(text: str) -> str:
    """The header line and EXCERPT_ROWS rows spread evenly through the answer, unchanged."""
    lines = text.splitlines()
    rows = lines[1:]
    picked = [rows[i * len(rows) // EXCERPT_ROWS] for i in range(EXCERPT_ROWS)]
    return "\n".join([lines[0], *picked]) + "\n"


def wave_hdu(exp: Exposure) -> bytes:
    """The WCS-WAVE HDU of one file: its last 5760 bytes."""
    total = http.get_range(exp.url, 0, rf.BLOCK).total
    assert total is not None
    return bytes(http.get_range(exp.url, total - rf.WAVE_HDU_BYTES, total))


def bundle_wave_tables(exps: list[Exposure]) -> None:
    """Write tombaugh/data/wcs_wave_D<det>.fits from one real file per detector, checked against a second."""
    BUNDLE.mkdir(exist_ok=True)
    for det in range(1, 7):
        mine = [e for e in exps if e.det == det]
        first, last = wave_hdu(mine[0]), wave_hdu(mine[-1])
        same_table = first[rf.BLOCK :] == last[rf.BLOCK :]
        assert same_table, f"D{det}: the lookup table differs between two files"
        raw = rf._EMPTY_PRIMARY + first
        with fits.open(io.BytesIO(raw)) as hdus:
            header = hdus[1].header
            assert header["EXTNAME"] == "WCS-WAVE" and int(header["DETECTOR"]) == det
        (BUNDLE / f"wcs_wave_D{det}.fits").write_bytes(raw)
        digest = hashlib.sha1(first[rf.BLOCK :]).hexdigest()[:16]
        print(
            f"D{det}: table sha1 {digest}, headers identical: {first[: rf.BLOCK] == last[: rf.BLOCK]}",
            f"({mine[0].obs_id} vs {mine[-1].obs_id})",
        )


def record_ranges(exp: Exposure) -> tuple[dict[str, np.ndarray], int]:
    """Every range `read_window` asks for: first with the object size known, then without it."""
    real = http.get_range
    ranges: dict[str, np.ndarray] = {}
    totals: set[int] = set()

    def recording(url: str, start: int, end: int, **kwargs: object) -> http.RangeBytes:
        buf = real(url, start, end, **kwargs)
        ranges[f"{start}_{end}"] = np.frombuffer(bytes(buf), dtype=np.uint8)
        totals.add(buf.total)
        return buf

    def recording_without_size(url: str, start: int, end: int, **kwargs: object) -> bytes:
        return bytes(recording(url, start, end, **kwargs))

    try:
        for fake in (recording, recording_without_size):
            http.get_range = fake
            rf.clear_cache()
            before = len(ranges)
            assert rf.read_window(exp, RA, DEC, HALF_PX) is not None
            print(f"{fake.__name__}: {len(ranges) - before} new ranges, {len(ranges)} in all")
    finally:
        http.get_range = real
        rf.clear_cache()
    (total,) = totals
    return ranges, total


def whole_file(exp: Exposure, total: int) -> bytes:
    """The complete object, fetched in CHUNK-sized ranges."""
    parts = [
        bytes(http.get_range(exp.url, start, min(start + CHUNK, total))) for start in range(0, total, CHUNK)
    ]
    return b"".join(parts)


def tab_lookup(table: fits.BinTableHDU, x: float, y: float) -> tuple[float, float]:
    """(wavelength, bandwidth) in micron at 0-based pixel (x, y): the -TAB bilinear lookup written by hand.

    The spectral WCS has CRPIX = CRVAL = CDELT = 1, so the lookup coordinate is the 1-based pixel coordinate.
    """
    row = table.data[0]
    values = row["VALUES"].astype(float)  # [y index, x index, (wavelength, bandwidth)]

    def cell(index: np.ndarray, coordinate: float) -> tuple[int, float]:
        k = int(np.clip(np.searchsorted(index, coordinate, side="right") - 1, 0, len(index) - 2))
        return k, (coordinate - index[k]) / (index[k + 1] - index[k])

    kx, fx = cell(row["X"].astype(float), x + 1.0)
    ky, fy = cell(row["Y"].astype(float), y + 1.0)
    value = (
        values[ky, kx] * (1 - fx) * (1 - fy)
        + values[ky, kx + 1] * fx * (1 - fy)
        + values[ky + 1, kx] * (1 - fx) * fy
        + values[ky + 1, kx + 1] * fx * fy
    )
    return float(value[0]), float(value[1])


def independent_window(blob: bytes) -> dict[str, np.ndarray]:
    """The window and its scalars from the complete file, by routes the reader does not use.

    astropy opens the whole file; FLAGS is decompressed in full as a CompImageHDU; the pixel position
    comes from solving the forward WCS (with SIP) numerically; the wavelength from a hand-written table
    lookup on the file's own WCS-WAVE HDU, cross-checked against wcslib.
    """
    with fits.open(io.BytesIO(blob)) as hdus:
        header = hdus["IMAGE"].header
        wcs = WCS(header)

        def miss(pixel: np.ndarray) -> list[float]:
            ra, dec = wcs.all_pix2world(pixel[0], pixel[1], 0)
            return [(float(ra) - RA) * math.cos(math.radians(DEC)), float(dec) - DEC]

        x, y = (float(v) for v in fsolve(miss, [rf.NX / 2, rf.NY / 2], xtol=1e-13))
        xc, yc = round(x), round(y)
        x0, y0, side = xc - HALF_PX, yc - HALF_PX, 2 * HALF_PX + 1
        assert x0 >= 0 and y0 >= 0 and x0 + side <= rf.NX and y0 + side <= rf.NY, (
            "pick a window fully on the detector"
        )
        assert isinstance(hdus["FLAGS"], fits.CompImageHDU)
        lam, dlam = tab_lookup(hdus["WCS-WAVE"], x, y)
        spectral = WCS(header, fobj=hdus, key="W")
        spectral.sip = None
        lam_wcslib, dlam_wcslib = (float(v) for v in spectral.wcs_pix2world(x, y, 0))
        assert abs(lam - lam_wcslib) < 1e-9 and abs(dlam - dlam_wcslib) < 1e-9, (
            lam,
            lam_wcslib,
            dlam,
            dlam_wcslib,
        )
        rows = slice(yc - rf.LEVEL_ROWS // 2, yc - rf.LEVEL_ROWS // 2 + rf.LEVEL_ROWS)
        cols = slice(x0, x0 + side)
        return {
            "image": np.array(hdus["IMAGE"].data[y0 : y0 + side, cols], dtype=np.float32),
            "flags": np.array(hdus["FLAGS"].data[y0 : y0 + side, cols], dtype=np.int32),
            "x": np.float64(x),
            "y": np.float64(y),
            "x0": np.int64(x0),
            "y0": np.int64(y0),
            "lam": np.float64(lam),
            "dlam": np.float64(dlam),
            "mjd": np.float64(header["MJD-AVG"]),
            "psf_fwhm": np.float64(header["PSF_FWHM"]),
            "zodi_level": np.float64(np.median(hdus["ZODI"].data[rows, cols])),
            "sky_var": np.float64(np.median(hdus["VARIANCE"].data[rows, cols])),
        }


def main() -> None:
    text = sia_text()
    (HERE / "sia_excerpt.csv").write_text(excerpt(text), encoding="utf-8")
    exps = discovery.parse_sia_csv(text, COLLECTION)
    print(f"{len(exps)} exposures listed")
    bundle_wave_tables(exps)
    exp = exps[0]
    ranges, total = record_ranges(exp)
    np.savez_compressed(HERE / "ranges.npz", **ranges)
    expected = independent_window(whole_file(exp, total))
    np.savez_compressed(HERE / "expected.npz", **expected)
    request = {"ra": RA, "dec": DEC, "half_px": HALF_PX, "total_bytes": total}
    (HERE / "exposure.json").write_text(
        json.dumps({"exposure": asdict(exp), "request": request}, indent=2) + "\n"
    )
    print(exp.uid, {k: (v.shape if v.ndim else v.item()) for k, v in expected.items()})


if __name__ == "__main__":
    main()
