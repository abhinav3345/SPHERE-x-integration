"""Discovery: which public SPHEREx detector images cover a sky position (IRSA Simple Image Access).

One SIA request per collection, at most two at a time. Every row is validated before it becomes an
`Exposure`: the pixels are only ever read from the public bucket `nasa-irsa-spherex` in `us-east-1`, under
a key of the known Level-2 shape. Rows that fail are dropped and counted, never repaired.

Angles are ICRS decimal degrees; times are MJD (UTC).
"""

from __future__ import annotations

import csv
import json
import logging
import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor

from tombaugh import http
from tombaugh.types import Exposure

COLLECTIONS = ("spherex_dr1", "spherex_dr1_deep", "spherex_qr3", "spherex_qr3_deep")
SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
BUCKET = "nasa-irsa-spherex"
REGION = "us-east-1"
KEY_PATTERN = re.compile(
    r"^(dr1|qr3)/level2/[A-Za-z0-9_]+/[A-Za-z0-9_.-]+/[1-6]/level2_[A-Za-z0-9_]+D[1-6]_spx_[A-Za-z0-9_.-]+\.fits$"
)
MAX_CONCURRENT = 2  # SIA requests in flight per discover() call
MAX_RADIUS_DEG = 2.0
DEFAULT_DEADLINE_S = 90.0  # used when the caller passes no deadline
SIA_TRIES = 8  # attempts per collection before discover() gives up

_REQUIRED = (
    "obs_id",
    "energy_bandpassname",
    "t_min",
    "t_max",
    "cloud_access",
    "dataproduct_type",
    "dataproduct_subtype",
    "access_format",
)
_UNQUOTED_JSON = re.compile(r"(?:(?<=,)|^)\{.*\}(?=,|$)")
_PLACEHOLDER = "@cloud_access@"
_OBS_ID = re.compile(r"[A-Za-z0-9_.-]+")
_BAND = re.compile(r"SPHEREx-D([1-6])")
_KEY_DETECTORS = re.compile(r"/([1-6])/level2_[A-Za-z0-9_]+D([1-6])_spx_")
_COLLECTION = re.compile(r"[a-z0-9_]+")
_FILTERED = "not_science_fits"  # rows of another product type: expected, not a fault

log = logging.getLogger(__name__)


def _split_row(line: str) -> list[str]:
    """Cells of one CSV line.

    IRSA does not quote the JSON object in the `cloud_access` column, so a plain CSV parser cuts that
    cell at the commas inside it. The object is lifted out before parsing and put back afterwards.
    """
    found = _UNQUOTED_JSON.search(line)
    if found is None:
        return next(csv.reader([line]), [])
    cells = next(csv.reader([line[: found.start()] + _PLACEHOLDER + line[found.end() :]]), [])
    return [found.group(0) if cell == _PLACEHOLDER else cell for cell in cells]


def _cloud_location(cell: str) -> tuple[object, object, object] | None:
    """(bucket, region, key) from a `cloud_access` cell, or None when it is not the expected JSON."""
    try:
        aws = json.loads(cell)["aws"]
        return aws["bucket_name"], aws["region"], aws["key"]
    except (ValueError, KeyError, TypeError):
        return None


def _exposure(row: dict[str, str], collection: str) -> Exposure | str:
    """The validated `Exposure` of one SIA row, or the reason the row is dropped."""
    kind = (row["dataproduct_type"], row["dataproduct_subtype"], row["access_format"])
    if tuple(value.strip().lower() for value in kind) != ("image", "science", "image/fits"):
        return _FILTERED
    obs_id = row["obs_id"].strip()
    if _OBS_ID.fullmatch(obs_id) is None:
        return "bad_obs_id"
    band = _BAND.fullmatch(row["energy_bandpassname"].strip())
    if band is None:
        return "bad_detector"
    det = int(band.group(1))
    try:
        t_min, t_max = float(row["t_min"]), float(row["t_max"])
    except ValueError:
        return "bad_time"
    if not (math.isfinite(t_min) and math.isfinite(t_max)):
        return "bad_time"
    location = _cloud_location(row["cloud_access"])
    if location is None:
        return "bad_cloud_access"
    bucket, region, key = location
    if bucket != BUCKET:
        return "wrong_bucket"
    if region != REGION:
        return "wrong_region"
    if not isinstance(key, str) or ".." in key or KEY_PATTERN.fullmatch(key) is None:
        return "bad_key"
    in_key = _KEY_DETECTORS.search(key)
    if in_key is None or {int(in_key.group(1)), int(in_key.group(2))} != {det}:
        return "detector_mismatch"
    exposure = Exposure(
        obs_id=obs_id,
        det=det,
        mjd=0.5 * (t_min + t_max),
        collection=collection,
        bucket=BUCKET,
        region=REGION,
        key=key,
        s_region=(row.get("s_region") or "").strip(),
    )
    try:
        http.check_url(exposure.url)
    except ValueError:
        return "foreign_host"
    return exposure


def _order(exposure: Exposure) -> tuple[float, int, str]:
    return (exposure.mjd, exposure.det, exposure.obs_id)


def parse_sia_csv_counted(text: str, collection: str) -> tuple[list[Exposure], dict[str, int]]:
    """Parse an SIA CSV answer; also return how many rows were dropped, by reason.

    Reasons: `not_science_fits` (another product type, expected), `malformed_row`, `bad_obs_id`,
    `bad_detector`, `bad_time`, `bad_cloud_access`, `wrong_bucket`, `wrong_region`, `bad_key`,
    `detector_mismatch`, `foreign_host`. Raises ValueError when `text` is not an SIA CSV table at all.
    A table with only its header line is a normal empty answer.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("empty SIA answer")
    header = [name.strip() for name in next(csv.reader([lines[0].lstrip("﻿")]), [])]
    missing = [name for name in _REQUIRED if name not in header]
    if missing:
        raise ValueError(f"not an SIA CSV table: no column {', '.join(missing)}")
    exposures: list[Exposure] = []
    dropped: Counter[str] = Counter()
    for line in lines[1:]:
        cells = _split_row(line)
        if len(cells) != len(header):
            dropped["malformed_row"] += 1
            continue
        outcome = _exposure(dict(zip(header, cells, strict=True)), collection)
        if isinstance(outcome, Exposure):
            exposures.append(outcome)
        else:
            dropped[outcome] += 1
    exposures.sort(key=_order)
    return exposures, dict(dropped)


def parse_sia_csv(text: str, collection: str) -> list[Exposure]:
    """Science FITS images listed in an SIA CSV answer, as validated `Exposure`s sorted by (mjd, det).

    `collection` is recorded on each exposure. `det` comes from `energy_bandpassname` ("SPHEREx-D3"
    gives 3) and `mjd` is the mean of `t_min` and `t_max`. Rows that fail validation are dropped; the
    number dropped is logged, and `parse_sia_csv_counted` returns it.
    """
    exposures, dropped = parse_sia_csv_counted(text, collection)
    faults = {reason: count for reason, count in dropped.items() if reason != _FILTERED}
    if faults:
        log.warning(
            "SIA %s: dropped %d row(s) that failed validation: %s", collection, sum(faults.values()), faults
        )
    return exposures


def merge_exposures(
    exposures: Iterable[Exposure], collections: Sequence[str] = COLLECTIONS
) -> list[Exposure]:
    """One exposure per (obs_id, det), preferring the dr1 collections, sorted by (mjd, det)."""

    def rank(exposure: Exposure) -> tuple[int, int]:
        listed = (
            collections.index(exposure.collection) if exposure.collection in collections else len(collections)
        )
        return (0 if exposure.collection.startswith("spherex_dr1") else 1, listed)

    best: dict[tuple[str, int], Exposure] = {}
    for exposure in exposures:
        held = best.get((exposure.obs_id, exposure.det))
        if held is None or rank(exposure) < rank(held):
            best[(exposure.obs_id, exposure.det)] = exposure
    return sorted(best.values(), key=_order)


def _check_request(ra: float, dec: float, radius_deg: float, collections: Sequence[str]) -> None:
    """Raise ValueError for a position, radius or collection name that must not be sent upstream."""
    if not (math.isfinite(ra) and math.isfinite(dec) and 0.0 <= ra <= 360.0 and -90.0 <= dec <= 90.0):
        raise ValueError(f"position out of range: ra={ra!r}, dec={dec!r}")
    if not (math.isfinite(radius_deg) and 0.0 < radius_deg <= MAX_RADIUS_DEG):
        raise ValueError(f"radius_deg must be within (0, {MAX_RADIUS_DEG}], got {radius_deg!r}")
    for name in collections:
        if _COLLECTION.fullmatch(name) is None:
            raise ValueError(f"not a collection name: {name!r}")


def _query(collection: str, pos: str, deadline: http.Deadline) -> list[Exposure]:
    """All exposures of one collection whose footprint meets the circle `pos`."""
    params = {"COLLECTION": collection, "POS": pos, "RESPONSEFORMAT": "csv"}
    response = http.get(SIA_URL, params=params, tries=SIA_TRIES, deadline=deadline)
    try:
        return parse_sia_csv(response.content.decode("utf-8", "replace"), collection)
    except ValueError as exc:
        message = f"unreadable SIA answer for {collection}: {exc}"
        raise http.UpstreamError(message, url=SIA_URL, status=response.status_code, attempts=1) from exc


def discover(
    ra: float,
    dec: float,
    *,
    radius_deg: float = 0.01,
    collections: Sequence[str] = COLLECTIONS,
    deadline: http.Deadline | None = None,
) -> list[Exposure]:
    """Every public SPHEREx detector image whose footprint meets a circle on the sky.

    `ra`, `dec` and `radius_deg` are ICRS degrees. One SIA request goes out per collection, at most two
    at a time. The result holds one exposure per (obs_id, det), preferring the dr1 collections, sorted
    by (mjd, det). An empty list is a normal answer. Raises UpstreamError (DeadlineExceeded when the
    deadline ran out) if IRSA still fails for any collection after the retries, and ValueError for an
    out-of-range request. Without a `deadline` the whole call is limited to DEFAULT_DEADLINE_S seconds.
    """
    _check_request(ra, dec, radius_deg, collections)
    limit = deadline if deadline is not None else http.Deadline(DEFAULT_DEADLINE_S)
    pos = f"circle {ra:.6f} {dec:.6f} {radius_deg:.6f}"
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT, thread_name_prefix="tombaugh-sia") as pool:
        found = list(pool.map(lambda name: _query(name, pos, limit), collections))
    return merge_exposures((exposure for part in found for exposure in part), collections)
