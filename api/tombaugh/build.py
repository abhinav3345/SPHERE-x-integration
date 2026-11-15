"""The build pipeline: a sky position in, a contract manifest and the bytes of frames.bin out.

discover -> sample -> read windows -> prepare -> register -> time bins -> stack -> encode -> manifest
(Contract v1.0, sections 2 to 6). Nothing here touches the disk; the cache and the HTTP service call it.

With `legacy_bands` (the service and make_fixture pass `tombaugh.legacy.LEGACY_BANDS`), the older-survey
planes of Then & Now (AllWISE W1/W2, 2MASS J/H/Ks; `tombaugh.legacy`) are made on a side thread while the
SPHEREx windows are read (IRSA serves them, the bucket serves SPHEREx), scaled on field stars to the paired
SPHEREx frame once the stacks exist, and appended after the SPHEREx planes (Contract sections 5 and 6). A plane
that could not be scaled on field stars is left out, because the contract says every legacy plane is
"scaled": "field_stars". Any failure there only costs those planes: the field is built without them and a
warning says so.

Units: positions in ICRS decimal degrees, fields of view in arcmin, times in MJD days (UTC), wavelengths in
micron, images in MJy/sr, durations in seconds.

What the counts in ``manifest.exposures`` mean:

* ``found``: detector images the archive lists for the field centre;
* ``sampled``: true when ``found`` exceeded the limit and a deterministic subset was read;
* ``used``: exposures that were read, registered and given to the stack with a known noise and at least one
  valid pixel on the grid. ``collections``, ``newest_mjd`` and ``newest_date`` describe these. Exposures
  left out for the foreground at 1.083 micron (see ``leave_out_helium``) are not among them.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import math
import re
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from tombaugh import CONTRACT_VERSION, __version__, http, legacy, prepare, presets, remote_fits
from tombaugh.discovery import discover
from tombaugh.frames import encode_planes, plane_offset, sha256_hex
from tombaugh.grid import ALLOWED_FOV, NATIVE_PIXSCALE_ARCSEC, PIXSCALE_ARCSEC, Grid, native_half_window
from tombaugh.models import (
    Centre,
    ExposuresInfo,
    FramesInfo,
    GridModel,
    Manifest,
    Plane,
    Provenance,
    RequestInfo,
    TimeBin,
    TimeBinning,
)
from tombaugh.register import register
from tombaugh.stack import Registered, stack_planes
from tombaugh.timebins import GAP_DAYS, MAX_SPAN_DAYS, SUB_SPAN_DAYS, assign_time_bins, mjd_to_date
from tombaugh.types import Cutout, Exposure, StackedPlane

PIPELINE_VERSION = __version__
EPOCH_REF = 2026.0  # Julian year; Contract section 1
MAX_EXPOSURES = 600  # Contract section 3
DEFAULT_DEADLINE_S = 120.0  # Contract section 7: a build that reaches 120 s returns what it has
READ_WORKERS = 16
KEY_LENGTH = 16  # hexadecimal characters of the content key
FRAMES_VERSION_LENGTH = 16  # hexadecimal characters of the frame file's SHA-256 written in its URL
HELIUM_LINE_UM = 1.0833  # He I line, micron: where a bright foreground was measured (see sees_helium_line)
STACK_RESERVE_S = 10.0  # time kept back from the deadline for preparing, registering and stacking
STACK_RESERVE_FRACTION = 0.15  # ... but never more than this share of the deadline
SPARSE_BIN_EXPOSURES = 15  # a time bin with fewer exposures gets a warning
SATURATION_RADIUS_ARCSEC = 15.0  # "saturated core within 15 arcsec of the centre"
CORE_BLANK = "blank"  # a saturated core with no value: nothing can be measured there
CORE_OVERFLOW = "overflow"  # OVERFLOW on the core, but every core pixel has a value: indicative only
STACK_PROGRESS_EVERY = 16  # exposures between two progress calls of the stack stage
LEGACY_DEADLINE_S = legacy.DEFAULT_DEADLINE_S  # the older-survey planes get at most this long ...
LEGACY_RESERVE_S = 5.0  # ... and are not waited for in the last seconds before the build's deadline
DATA_DOIS = ("10.26131/IRSA678", "10.26131/IRSA662")  # SPHEREx DR1 and QR3 spectral images
NOTE_RESAMPLED = (
    f'resampled to {PIXSCALE_ARCSEC}"/px; native pixel {NATIVE_PIXSCALE_ARCSEC}"; resolution about 10"'
)
NOTE_STACKS = (
    "each plane is the inverse-variance mean of the exposures of one time bin and wave bin after a local "
    "background was subtracted; outliers are rejected only within one time bin and detector; "
    "for display, not for photometry"
)
NOTE_REJECTION = (
    "the exposures of one detector see a source at different wavelengths, so a spectral feature that "
    "one in ten of them or fewer see can be rejected as an outlier and be missing from its plane"
)

ProgressFn = Callable[[str, int, int], None]
_PROCESSING_VERSION = re.compile(r"^(l\d[a-z]?-v\d+)")  # "l2b-v27" of "l2b-v27-2026-197"

log = logging.getLogger(__name__)


class AlreadyBuilt(Exception):
    """The caller already holds the field that this build would produce.

    Raised by `build_field` after discovery, before any pixel is read, when its `known` callback accepts
    the listing key. `key` is that listing key: `field_key` over the exposures about to be read. It is the
    key of the field itself only when every one of them ends up in the stack.
    """

    def __init__(self, key: str) -> None:
        super().__init__(f"field {key} is already built")
        self.key = key


@dataclass
class BuildStats:
    """What one build did, for logs and reports. Durations in seconds."""

    key: str = ""
    listing_key: str = ""  # `field_key` over the exposures selected for reading, used or not
    status: str = ""
    found: int = 0
    selected: int = 0
    read: int = 0
    used: int = 0
    off_detector: int = 0
    failed: int = 0
    timed_out: int = 0
    unusable: int = 0
    helium_left_out: int = 0  # exposures whose band covers 1.083 micron, left out of planes that have others
    helium_planes: int = 0  # planes made of such exposures alone
    planes: int = 0
    time_bins: int = 0
    frames_nbytes: int = 0
    newest_found_mjd: float | None = None
    legacy_planes: int = 0  # older-survey planes in the manifest
    legacy_left_out: int = 0  # older-survey planes made but left out (not scaled on field stars, or unusable)
    legacy_incomplete: bool = False  # an upstream of the older surveys failed: worth building again soon
    seconds: dict[str, float] = field(default_factory=dict)
    http: dict[str, int] = field(default_factory=dict)
    exposures: list[Exposure] = field(default_factory=list, repr=False)  # the selected exposures, read or not

    def as_log(self) -> dict:
        """The one-line JSON record of this build (the exposure list is left out)."""
        record = {"event": "build", **self.__dict__}
        record.pop("exposures", None)
        record["seconds"] = {name: round(value, 3) for name, value in self.seconds.items()}
        return record


# ------------------------------------------------------------------------------------------- sampling
def _fair_quotas(sizes: dict[tuple[int, int], int], limit: int) -> dict[tuple[int, int], int]:
    """How many members each group keeps when `limit` places are shared out as evenly as possible.

    Groups smaller than an even share keep everything and the places they leave go to the others. The sum
    of the quotas is `limit` whenever the groups hold more than `limit` members in all.
    """
    quotas: dict[tuple[int, int], int] = {}
    remaining = max(0, int(limit))
    still_open = sorted(sizes)
    while still_open:
        share = remaining // len(still_open)
        small = [key for key in still_open if sizes[key] <= share]
        if not small:
            extra = remaining - share * len(still_open)
            for position, key in enumerate(still_open):
                quotas[key] = share + (1 if position < extra else 0)
            break
        for key in small:
            quotas[key] = sizes[key]
            remaining -= sizes[key]
        still_open = [key for key in still_open if key not in small]
    return quotas


def _spread(count: int, wanted: int) -> list[int]:
    """`wanted` indices spread evenly over range(count): the centres of `wanted` equal strata."""
    if wanted >= count:
        return list(range(count))
    return [(2 * i + 1) * count // (2 * wanted) for i in range(wanted)]


def _canonical_order(exposure: Exposure) -> tuple[float, int, str]:
    return (exposure.mjd, exposure.det, exposure.obs_id)


def sample_exposures(exposures: Sequence[Exposure], limit: int = MAX_EXPOSURES) -> list[Exposure]:
    """At most `limit` exposures, chosen evenly per time bin and detector (Contract section 3).

    The exposures are grouped by (time bin, detector), the time bins coming from the listed mid-times. The
    `limit` places are shared out evenly between the groups, and inside a group the members are taken at
    even steps through the list ordered by `obs_id`. The choice depends only on the set of exposures, not on
    their order. The result is sorted by (mjd, detector, obs_id).
    """
    unique = sorted({exposure.uid: exposure for exposure in exposures}.values(), key=_canonical_order)
    if limit <= 0:
        return []
    if len(unique) <= limit:
        return unique
    bins = assign_time_bins([exposure.mjd for exposure in unique])
    groups: dict[tuple[int, int], list[Exposure]] = defaultdict(list)
    for exposure, time_bin in zip(unique, bins, strict=True):
        groups[(int(time_bin), exposure.det)].append(exposure)
    quotas = _fair_quotas({key: len(members) for key, members in groups.items()}, limit)
    chosen: list[Exposure] = []
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda exposure: (exposure.obs_id, exposure.det))
        chosen.extend(members[index] for index in _spread(len(members), quotas[key]))
    return sorted(chosen, key=_canonical_order)


# ------------------------------------------------------------------------------------------------ key
def field_key(ra0: float, dec0: float, fov_arcmin: int, uids: Sequence[str]) -> str:
    """Content key of a field: 16 hexadecimal characters.

    The first 16 characters of the SHA-256 of a canonical JSON (sorted keys, no spaces, ASCII) holding the
    contract version, the snapped centre written with 4 decimals, the field of view in arcmin, `epoch_ref`,
    the pipeline version and the sorted `uids` of the exposures used. The order of `uids` does not matter.
    """
    document = {
        "centre": [f"{float(ra0):.4f}", f"{float(dec0):.4f}"],
        "contract": CONTRACT_VERSION,
        "epoch_ref": EPOCH_REF,
        "exposures": sorted(set(uids)),
        "fov_arcmin": int(fov_arcmin),
        "pipeline_version": PIPELINE_VERSION,
    }
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()[:KEY_LENGTH]


def frames_version(sha256: str) -> str:
    """The part of a frame file's SHA-256 (hexadecimal) that its URL carries: the first 16 characters."""
    return sha256[:FRAMES_VERSION_LENGTH]


def frames_url(key: str, sha256: str) -> str:
    """Path of the frame file of a field, as written in its manifest.

    The query ``v`` names the bytes: `frames_version` of their SHA-256. The key alone does not (it is made
    of the centre, the field of view, the pipeline version and the exposure names), and the file is answered
    as immutable, so two files with different bytes must never share a URL.
    """
    return f"/api/fields/{key}/frames.bin?v={frames_version(sha256)}"


# ------------------------------------------------------------------------------------------- manifest
def _utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mjd(value: float) -> float:
    return round(float(value), 5)


def _time_bin_models(items: Sequence[Registered]) -> list[TimeBin]:
    """One `TimeBin` per time-bin id present among the stacked exposures, in id order."""
    members: dict[int, list[Registered]] = defaultdict(list)
    for item in items:
        members[int(item.time_bin)].append(item)
    bins: list[TimeBin] = []
    for time_bin in sorted(members):
        mjds = [float(item.mjd) for item in members[time_bin]]
        start, end = min(mjds), max(mjds)
        bins.append(
            TimeBin(
                id=time_bin,
                mjd_start=_mjd(start),
                mjd_end=_mjd(end),
                mjd_mid=_mjd(0.5 * (start + end)),
                date_start=mjd_to_date(start),
                date_end=mjd_to_date(end),
                n_exposures=len(mjds),
                detectors=sorted({int(item.exposure.det) for item in members[time_bin]}),
            )
        )
    return bins


def _plane_models(planes: Sequence[StackedPlane], grid: Grid) -> list[Plane]:
    """The manifest entries of the planes, in (time_bin, wave_bin) order with their byte offsets."""
    wave_bins = {wave_bin.id: wave_bin for wave_bin in presets.wave_bins()}
    ordered = sorted(planes, key=lambda plane: (plane.time_bin, plane.wave_bin))
    models: list[Plane] = []
    for index, plane in enumerate(ordered):
        wave_bin = wave_bins[int(plane.wave_bin)]
        models.append(
            Plane(
                index=index,
                kind="sci",
                mission="SPHEREx",
                time_bin=int(plane.time_bin),
                wave_bin=int(plane.wave_bin),
                band=None,
                lam_min=wave_bin.lam_min,
                lam_max=wave_bin.lam_max,
                lam_eff=round(float(plane.lam_eff), 5),
                n_exposures=int(plane.n_exposures),
                sigma=float(f"{float(plane.sigma):.6g}"),
                mjd_mid=_mjd(plane.mjd_mid),
                date_start=mjd_to_date(plane.mjd_min),
                date_end=mjd_to_date(plane.mjd_max),
                offset=plane_offset(index, grid.n, grid.n),
            )
        )
    return models


def _exposures_info(items: Sequence[Registered], found: int, sampled: bool) -> ExposuresInfo:
    counts = Counter(item.exposure.collection for item in items)
    newest = max((float(item.mjd) for item in items), default=None)
    return ExposuresInfo(
        found=int(found),
        used=len(items),
        sampled=bool(sampled),
        collections={name: counts[name] for name in sorted(counts)},
        newest_mjd=None if newest is None else _mjd(newest),
        newest_date=None if newest is None else mjd_to_date(newest),
    )


def assemble_manifest(
    request_ra: float,
    request_dec: float,
    fov_arcmin: int,
    grid: Grid,
    planes: Sequence[StackedPlane],
    items: Sequence[Registered],
    *,
    found: int,
    sampled: bool = False,
    partial: bool = False,
    warnings: Sequence[str] = (),
    notes: Sequence[str] = (),
    built_at: str | None = None,
    legacy_planes: Sequence[legacy.LegacyPlane] = (),
) -> tuple[Manifest, bytes]:
    """The manifest of Contract section 5 and the bytes of frames.bin for stacked planes.

    `planes` are the stacks of `items`, the registered exposures that were given to the stack; `found` is
    the number of exposures the archive lists. Without planes the manifest has status "empty", no planes
    and `frames` null, and the bytes are empty. The key is `field_key` over the uids of `items`. `built_at`
    (ISO 8601 UTC) defaults to now.

    `legacy_planes` (older-survey planes on the same grid, `tombaugh.legacy`) follow the SPHEREx planes in
    the order given, in the manifest and in frames.bin; they are dropped when there is no SPHEREx plane, and
    they never enter the key (it names the SPHEREx exposures; the version in it names the pipeline).
    """
    ordered = sorted(planes, key=lambda plane: (plane.time_bin, plane.wave_bin))
    stacked = list(items) if ordered else []
    extra = list(legacy_planes) if ordered else []
    key = field_key(grid.ra0, grid.dec0, fov_arcmin, [item.exposure.uid for item in stacked])
    plane_models = _plane_models(ordered, grid)
    plane_models += [plane.plane_model(len(ordered) + k, grid) for k, plane in enumerate(extra)]
    frames = (
        encode_planes([*(plane.data for plane in ordered), *(plane.data for plane in extra)])
        if ordered
        else b""
    )
    info = None
    if ordered:
        digest = sha256_hex(frames)
        info = FramesInfo(url=frames_url(key, digest), nbytes=len(frames), sha256=digest)
    manifest = Manifest(
        status="empty" if not ordered else ("partial" if partial else "ready"),
        key=key,
        request=RequestInfo(ra=float(request_ra), dec=float(request_dec), fov_arcmin=int(fov_arcmin)),
        centre=Centre(ra=grid.ra0, dec=grid.dec0),
        epoch_ref=EPOCH_REF,
        grid=GridModel.from_grid(grid),
        time_binning=TimeBinning(
            gap_days=int(GAP_DAYS), max_span_days=int(MAX_SPAN_DAYS), sub_span_days=int(SUB_SPAN_DAYS)
        ),
        time_bins=_time_bin_models(stacked),
        wave_bins=presets.wave_bins(),
        planes=plane_models,
        frames=info,
        exposures=_exposures_info(stacked, found, sampled),
        provenance=Provenance(
            pipeline_version=PIPELINE_VERSION,
            built_at=built_at or _utc_now(),
            data_dois=list(DATA_DOIS),
            notes=[NOTE_RESAMPLED, NOTE_STACKS, NOTE_REJECTION, *notes],
        ),
        warnings=list(warnings),
    )
    return manifest, frames


# ------------------------------------------------------------------------------- exposures to planes
def _core_near_centre(cut: Cutout) -> str | None:
    """What a bright core within 15 arcsec of the window centre does to the measurement there.

    * CORE_BLANK: a pixel of a saturated core has no value (`prepare.core_mask`, without a value): the core
      is blank, so no brightness can be read there ("saturated");
    * CORE_OVERFLOW: pixels there carry the OVERFLOW flag, but no core pixel is blank: the values exist and
      are indicative only;
    * None: neither.
    """
    if cut.flags is None:
        return None
    flags = np.asarray(cut.flags).astype(np.int64, copy=False)
    image = np.asarray(cut.image)
    blank = prepare.core_mask(image, flags) & ~np.isfinite(image)
    overflow = (flags & prepare.bit_mask(prepare.OVERFLOW)) != 0
    if not (blank.any() or overflow.any()):
        return None
    rows, cols = np.indices(image.shape, dtype=np.float64)
    centre_row, centre_col = (image.shape[0] - 1) / 2.0, (image.shape[1] - 1) / 2.0
    radius_px = SATURATION_RADIUS_ARCSEC / NATIVE_PIXSCALE_ARCSEC
    near = np.hypot(rows - centre_row, cols - centre_col) <= radius_px
    if (blank & near).any():
        return CORE_BLANK
    if (overflow & near).any():
        return CORE_OVERFLOW
    return None


def _register_one(cut: Cutout, grid: Grid, time_bin: int) -> Registered | None:
    """One cutout prepared and resampled onto the grid; None when it cannot contribute to a stack."""
    prepared = prepare.prepare(cut)
    if not (math.isfinite(prepared.weight) and prepared.weight > 0.0):
        return None
    data = register(cut, prepared.sci, grid)
    if not np.isfinite(data).any():
        return None
    return Registered(
        exposure=cut.exposure,
        data=data,
        weight=float(prepared.weight),
        lam=float(cut.lam),
        mjd=float(cut.mjd),
        time_bin=time_bin,
        wave_bin=presets.wave_bin_for(cut.exposure.det, cut.lam),
    )


def _renumber_time_bins(items: Sequence[Registered]) -> None:
    """Make the time-bin ids of `items` consecutive from 0, keeping their order in time."""
    present = sorted({item.time_bin for item in items})
    new_id = {old: new for new, old in enumerate(present)}
    for item in items:
        item.time_bin = new_id[item.time_bin]


def register_cutouts(
    cutouts: Sequence[Cutout],
    grid: Grid,
    progress: ProgressFn | None = None,
    *,
    cores: Counter[str] | None = None,
) -> tuple[list[Registered], int, int]:
    """Give every cutout its time bin, then prepare and register it.

    The time bins come from the mid-times of all the exposures that were read (Contract section 3), so an
    exposure that turns out to be unusable still holds its visit together. Bins left without a usable
    exposure are dropped and the ids renumbered from 0.

    Returns (items, unusable, saturated): the registered exposures, the number of cutouts that could not
    contribute (unknown noise, no valid pixel on the grid, or a header that could not be used), and the
    number whose saturated core within 15 arcsec of the centre is blank. `cores`, when given, counts the
    exposures per `_core_near_centre` outcome (CORE_BLANK, CORE_OVERFLOW).
    """
    bins = assign_time_bins([cut.mjd for cut in cutouts])
    items: list[Registered] = []
    unusable = saturated = 0
    for count, (cut, time_bin) in enumerate(zip(cutouts, bins, strict=True), start=1):
        try:
            core = _core_near_centre(cut)
            saturated += core == CORE_BLANK
            if cores is not None and core is not None:
                cores[core] += 1
            item = _register_one(cut, grid, int(time_bin))
        except (ValueError, ArithmeticError) as exc:
            log.warning("exposure %s could not be registered: %s", cut.exposure.uid, exc)
            item = None
        if item is None:
            unusable += 1
        else:
            items.append(item)
        if progress is not None and (count % STACK_PROGRESS_EVERY == 0 or count == len(cutouts)):
            progress("stack", count, len(cutouts))
    _renumber_time_bins(items)
    return items, unusable, saturated


def sees_helium_line(lam: float, dlam: float) -> bool:
    """True when 1.0833 micron lies within one bandwidth of an exposure's wavelength.

    `lam` and `dlam` are the central wavelength and the bandwidth at the field centre, micron.

    Measured on 14 Nov 2026 on real exposures. In the WISE 0855 field the five exposures this close to
    1.083 micron (1.064 to 1.101 micron) have a background that changes by 23 to 128 times the noise across
    the window, which no constant removes; the six others between 1.03 and 1.14 micron are flat to within 2
    times the noise. There and in the Barnard field the background of such exposures is up to 1.8 MJy/sr
    brighter than at neighbouring wavelengths, most at 1.082 to 1.092 micron. The wavelength is that of the
    He I line, which glows in the Earth's upper atmosphere; that this is the cause has not been checked
    against a primary source.
    """
    return abs(float(lam) - HELIUM_LINE_UM) < float(dlam)


def leave_out_helium(
    items: Sequence[Registered], cutouts: Sequence[Cutout]
) -> tuple[list[Registered], int, int]:
    """Leave the exposures whose band covers 1.083 micron out of every plane that has other exposures.

    See `sees_helium_line` for what is wrong with them. A plane, one (time bin, wave bin), keeps such
    exposures only when it has no other: a plane is never lost, so the set of wave bins of a time bin does
    not change. `cutouts` supplies the bandwidths.

    Returns (items kept in their order, exposures left out, planes that rest on such exposures alone).
    """
    affected = {cut.exposure.uid for cut in cutouts if sees_helium_line(cut.lam, cut.dlam)}
    clean_planes = {(item.time_bin, item.wave_bin) for item in items if item.exposure.uid not in affected}
    kept: list[Registered] = []
    alone: set[tuple[int, int]] = set()
    for item in items:
        plane = (item.time_bin, item.wave_bin)
        if item.exposure.uid not in affected:
            kept.append(item)
        elif plane not in clean_planes:
            kept.append(item)
            alone.add(plane)
    return kept, len(items) - len(kept), len(alone)


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _stack_reserve(deadline_s: float) -> float:
    return min(STACK_RESERVE_S, STACK_RESERVE_FRACTION * deadline_s)


def visit_label(time_bin: TimeBin) -> str:
    """How a warning names a visit: by its dates, never by its id ("the visit of 2025-09-30 to 2025-10-01")."""
    if time_bin.date_start == time_bin.date_end:
        return f"the visit of {time_bin.date_start}"
    return f"the visit of {time_bin.date_start} to {time_bin.date_end}"


def _warnings(
    stats: BuildStats, cores: Mapping[str, int], deadline_s: float, bins: Sequence[TimeBin]
) -> list[str]:
    """Plain-language warnings of a build, most important first.

    `cores` counts the exposures by what a bright core within 15 arcsec of the centre does there
    (`_core_near_centre`): CORE_BLANK (saturated: no value) and CORE_OVERFLOW (flagged, but measured).
    """
    out: list[str] = []
    if stats.timed_out:
        out.append(
            f"build stopped at the {deadline_s:g} s deadline: "
            f"{stats.read} of {_count(stats.selected, 'exposure')} were read"
        )
    if stats.failed:
        out.append(f"{_count(stats.failed, 'exposure')} failed to download")
    if stats.unusable:
        out.append(
            f"{_count(stats.unusable, 'exposure')} could not be used (no valid pixel or unknown noise)"
        )
    within = f"within {SATURATION_RADIUS_ARCSEC:g} arcsec of the centre"
    if cores.get(CORE_BLANK, 0):
        out.append(
            f"saturated core {within} in {cores[CORE_BLANK]} of {_count(stats.read, 'exposure')}: "
            "those pixels have no value, so no brightness can be read there"
        )
    if cores.get(CORE_OVERFLOW, 0):
        out.append(
            f"bright core {within} flagged as overflowing in {cores[CORE_OVERFLOW]} of "
            f"{_count(stats.read, 'exposure')}, but measured: brightness there is indicative only"
        )
    for time_bin in bins:
        if time_bin.n_exposures < SPARSE_BIN_EXPOSURES:
            out.append(f"{visit_label(time_bin)} has only {_count(time_bin.n_exposures, 'exposure')}")
    return out


def _processing_version(version: str) -> str:
    """The processing version without its run date: "l2b-v27" for "l2b-v27-2026-197"."""
    found = _PROCESSING_VERSION.match(version)
    return found.group(1) if found else version


def _notes(stats: BuildStats, cutouts: Sequence[Cutout]) -> list[str]:
    """Provenance notes that depend on the build."""
    out: list[str] = []
    versions = sorted({_processing_version(cut.version) for cut in cutouts if cut.version})
    if versions:
        out.append("SPHEREx Level-2 processing: " + ", ".join(versions))
    if stats.off_detector:
        out.append(
            f"{_count(stats.off_detector, 'listed exposure')} left out: the field centre is off the detector"
        )
    if stats.helium_left_out:
        out.append(
            f"{_count(stats.helium_left_out, 'exposure')} left out: the band covers 1.083 micron, "
            "where a bright foreground is not flat across the field"
        )
    if stats.helium_planes:
        out.append(
            f"{_count(stats.helium_planes, 'plane')} near 1.08 micron made only of exposures whose band "
            "covers the bright foreground at 1.083 micron: the background there is not flat"
        )
    return out


# ----------------------------------------------------------------------------------- older-survey planes
class _StoppableDeadline(http.Deadline):
    """A deadline that the build can also end early, so the side thread's requests stop at once."""

    def __init__(self, seconds: float, stop: threading.Event) -> None:
        super().__init__(seconds)
        self._stop = stop

    def remaining(self) -> float:
        return 0.0 if self._stop.is_set() else super().remaining()

    @property
    def expired(self) -> bool:
        return self._stop.is_set() or super().expired


# Words of tombaugh.legacy's warnings that name an upstream failure (a later build may do better), as opposed
# to the sky (no image covers the field, too few field stars): "<mission>: archive unavailable (...)" and
# "<mission> <band>: <n> image(s) not read (...)".
_LEGACY_UPSTREAM_FAILURE = (": archive unavailable (", " image(s) not read (")


@dataclass
class LegacyOutcome:
    """The older-survey planes a build keeps, with what the manifest says about them."""

    planes: list[legacy.LegacyPlane] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    left_out: int = 0
    incomplete: bool = False  # an upstream failed or the planes were not ready in time
    seconds: float = 0.0


def keep_legacy_planes(result: legacy.LegacyResult, grid: Grid) -> LegacyOutcome:
    """Which planes of a `legacy.LegacyResult` go into the manifest, and the words that go with them.

    A plane is kept only when it was scaled on field stars (Contract section 5: every legacy plane is
    "scaled": "field_stars") and its manifest entry is valid (finite numbers). A plane left out is replaced
    by a warning that says why; its own "not scaled ... values in DN" warning is dropped with it.
    """
    outcome = LegacyOutcome(seconds=float(result.seconds))
    dropped_words: set[str] = set()
    for plane in result.planes:
        label = f"{plane.mission} {plane.band}"
        reason = ""
        if plane.scaled != "field_stars":
            reason = "its brightness could not be matched to SPHEREx on field stars"
        else:
            try:
                plane.plane_model(0, grid)
            except ValueError as exc:  # pydantic refuses NaN and infinity
                reason = f"its description is not valid ({type(exc).__name__})"
        if reason:
            dropped_words.update(plane.warnings)
            outcome.left_out += 1
            outcome.warnings.append(f"{label}: plane left out: {reason}.")
            continue
        outcome.planes.append(plane)
        outcome.notes.extend(plane.notes)
    outcome.warnings = [w for w in result.warnings if w not in dropped_words] + outcome.warnings
    outcome.incomplete = any(part in w for w in result.warnings for part in _LEGACY_UPSTREAM_FAILURE)
    return outcome


class _LegacyJob:
    """`legacy.build_legacy_planes` on a side thread, started while the SPHEREx windows are read.

    The paired SPHEREx frames that scale the planes exist only after stacking, so the thread's `references`
    callback waits for `finish` to hand the stacked planes over. `deadline_s` bounds the older surveys'
    requests; the wait for the stacks is bounded by the build's own deadline (`stacks_by`), never by the
    requests' (regression: a field whose SPHEREx reads took 55 s lost every legacy plane, its references
    having timed out with the 60 s request deadline).
    """

    def __init__(self, grid: Grid, bands: Sequence[str], deadline_s: float, stacks_by: http.Deadline) -> None:
        self._grid = grid
        self._bands = tuple(bands)
        self._stop = threading.Event()
        self._deadline = _StoppableDeadline(deadline_s, self._stop)
        self._stacks_by = stacks_by
        self._stacked = threading.Event()
        self._planes: list[StackedPlane] = []
        self._result: legacy.LegacyResult | None = None
        self._error = ""
        self._thread = threading.Thread(target=self._run, name="tombaugh-legacy", daemon=True)
        self._thread.start()

    def _reference(self, band: str) -> np.ndarray | None:
        if not self._stacked.wait(self._stacks_by.remaining()) or self._stop.is_set() or not self._planes:
            return None
        return legacy.paired_reference(self._planes, band)

    def _run(self) -> None:
        try:
            self._result = legacy.build_legacy_planes(
                self._grid, self._bands, references=self._reference, deadline=self._deadline
            )
        except Exception as exc:  # the older surveys must never take the field down with them
            log.exception("older-survey planes failed")
            self._error = type(exc).__name__

    def cancel(self) -> None:
        """Stop the side thread's requests and let it end (idempotent)."""
        self._stop.set()
        self._stacked.set()

    def finish(self, planes: Sequence[StackedPlane], wait_s: float) -> LegacyOutcome:
        """Hand over the SPHEREx stacks, wait at most `wait_s` seconds, and say what is kept."""
        self._planes = list(planes)
        self._stacked.set()
        self._thread.join(timeout=max(0.0, wait_s))
        if self._thread.is_alive():
            self.cancel()
            return LegacyOutcome(
                warnings=["older-survey planes (AllWISE, 2MASS) were not ready before the build's deadline"],
                incomplete=True,
            )
        if self._result is None:
            return LegacyOutcome(
                warnings=[f"older-survey planes (AllWISE, 2MASS) could not be made ({self._error})"],
                incomplete=True,
            )
        return keep_legacy_planes(self._result, self._grid)


def _split_failures(failures: Sequence[tuple[Exposure, str]], stats: BuildStats) -> str:
    """Count the reader's failures by kind into `stats`; return the first download error, "" if none."""
    first_error = ""
    for _, reason in failures:
        if reason == remote_fits.OFF_DETECTOR:
            stats.off_detector += 1
        elif reason == remote_fits.DEADLINE:
            stats.timed_out += 1
        else:
            stats.failed += 1
            first_error = first_error or reason
    return first_error


def build_field_with_stats(
    ra: float,
    dec: float,
    fov_arcmin: int,
    *,
    progress: ProgressFn | None = None,
    deadline_s: float = DEFAULT_DEADLINE_S,
    max_exposures: int = MAX_EXPOSURES,
    known: Callable[[str], bool] | None = None,
    legacy_bands: Sequence[str] = (),
) -> tuple[Manifest, bytes, BuildStats]:
    """`build_field`, also returning what the build did (counts and seconds per stage)."""
    if fov_arcmin not in ALLOWED_FOV:
        raise ValueError(f"fov_arcmin must be one of {ALLOWED_FOV}, got {fov_arcmin!r}")
    for band in legacy_bands:
        legacy.mission_of(band)  # KeyError for a band presets.json does not pair, before anything is sent
    fov = int(fov_arcmin)
    grid = Grid.for_field(ra, dec, fov)
    stats = BuildStats()
    before = http.stats()
    clock = time.monotonic()
    started = clock
    build_deadline = http.Deadline(deadline_s)
    limit = http.Deadline(max(0.0, deadline_s - _stack_reserve(deadline_s)))

    def lap(stage: str) -> None:
        nonlocal clock
        now = time.monotonic()
        stats.seconds[stage] = now - clock
        clock = now

    def report(stage: str, done: int, total: int) -> None:
        if progress is not None:
            progress(stage, done, total)

    report("discover", 0, 1)
    found = discover(grid.ra0, grid.dec0, deadline=limit)
    report("discover", 1, 1)
    lap("discover")
    stats.found = len(found)
    stats.newest_found_mjd = max((exposure.mjd for exposure in found), default=None)

    selected = sample_exposures(found, max_exposures)
    stats.selected = len(selected)
    stats.exposures = list(selected)
    stats.listing_key = field_key(grid.ra0, grid.dec0, fov, [exposure.uid for exposure in selected])
    if known is not None and selected and known(stats.listing_key):
        raise AlreadyBuilt(stats.listing_key)  # the same exposures were listed before: nothing would change
    side = None
    if legacy_bands and selected:  # other hosts than the bucket: run alongside the SPHEREx reads
        side = _LegacyJob(grid, legacy_bands, min(LEGACY_DEADLINE_S, limit.remaining()), build_deadline)
    try:
        report("fetch", 0, len(selected))
        cutouts, failures = remote_fits.read_windows(
            selected,
            grid.ra0,
            grid.dec0,
            native_half_window(fov),
            workers=READ_WORKERS,
            deadline=limit,
            progress=lambda done, total: report("fetch", done, total),
        )
        lap("fetch")
        stats.read = len(cutouts)
        first_error = _split_failures(failures, stats)
        if selected and not cutouts and (stats.failed or stats.timed_out):
            raise http.UpstreamError(
                f"none of the {_count(len(selected), 'exposure')} could be read"
                + (f": {first_error}" if first_error else " before the deadline")
            )

        report("stack", 0, len(cutouts))
        cores: Counter[str] = Counter()
        items, stats.unusable, _ = register_cutouts(cutouts, grid, progress, cores=cores)
        items, stats.helium_left_out, stats.helium_planes = leave_out_helium(items, cutouts)
        planes, _events = stack_planes(items)
        older = LegacyOutcome()
        if side is not None and planes:
            older = side.finish(planes, build_deadline.remaining() - LEGACY_RESERVE_S)
            stats.seconds["legacy"] = older.seconds
    finally:
        if side is not None:
            side.cancel()
    stats.legacy_planes, stats.legacy_left_out = len(older.planes), older.left_out
    stats.legacy_incomplete = older.incomplete
    manifest, frames = assemble_manifest(
        ra,
        dec,
        fov,
        grid,
        planes,
        items,
        found=len(found),
        sampled=len(selected) < len(found),
        partial=stats.timed_out > 0,
        legacy_planes=older.planes,
    )
    manifest.warnings = _warnings(stats, cores, deadline_s, manifest.time_bins)
    manifest.provenance.notes.extend(_notes(stats, cutouts))
    if manifest.planes:
        manifest.warnings.extend(older.warnings)
        manifest.provenance.notes.extend(older.notes)
    report("stack", len(cutouts), len(cutouts))
    lap("stack")

    stats.seconds["total"] = time.monotonic() - started
    stats.key, stats.status = manifest.key, manifest.status
    stats.used, stats.planes, stats.time_bins = manifest.exposures.used, len(planes), len(manifest.time_bins)
    stats.frames_nbytes = len(frames)
    after = http.stats()
    stats.http = {name: after[name] - before.get(name, 0) for name in after}
    log.info(json.dumps(stats.as_log(), sort_keys=True))
    return manifest, frames, stats


def build_field(
    ra: float,
    dec: float,
    fov_arcmin: int,
    *,
    progress: ProgressFn | None = None,
    deadline_s: float = DEFAULT_DEADLINE_S,
    max_exposures: int = MAX_EXPOSURES,
    known: Callable[[str], bool] | None = None,
    legacy_bands: Sequence[str] = (),
) -> tuple[Manifest, bytes]:
    """Build the field around a sky position: (manifest, bytes of frames.bin).

    `ra` and `dec` are ICRS degrees and are snapped to 4 decimals; `fov_arcmin` is one of 3, 4, 5, 6, 8, 10.
    At most `max_exposures` exposures are read, sampled evenly per time bin and detector beyond that.

    * No exposure covers the position: status "empty", no planes, `frames` null, empty bytes.
    * `deadline_s` seconds after the start nothing more is read; what was read is stacked and the status is
      "partial", with a warning that says how many exposures were read.
    * `progress(stage, done, total)` is called from this thread with stage "discover", "fetch" or "stack".
      An exception raised by it stops the build and propagates: that is how a caller cancels.
    * `known(listing_key)` is asked once, after discovery, whether the caller already holds the field that
      a complete build of exactly the exposures about to be read gave. The listing key is `field_key` over
      those exposures; it differs from the field's own key as soon as one of them is not used (off the
      detector, unusable). If the answer is yes, `AlreadyBuilt` is raised and nothing is read.
    * `legacy_bands` (contract bands, `legacy.LEGACY_BANDS` for all five) adds the older-survey planes after
      the SPHEREx planes: made while the SPHEREx windows are read, scaled on field stars, left out with a
      warning when that fails. The default adds none.

    Raises ValueError for a position or field of view out of range, KeyError for an unknown legacy band, and
    `http.UpstreamError` when the archive cannot be searched or none of the exposures can be read.
    """
    manifest, frames, _ = build_field_with_stats(
        ra,
        dec,
        fov_arcmin,
        progress=progress,
        deadline_s=deadline_s,
        max_exposures=max_exposures,
        known=known,
        legacy_bands=legacy_bands,
    )
    return manifest, frames


def build_field_for_service(
    ra: float, dec: float, fov_arcmin: int, **kwargs
) -> tuple[Manifest, bytes, BuildStats]:
    """What the HTTP service builds: `build_field_with_stats` with every older-survey band."""
    kwargs.setdefault("legacy_bands", legacy.LEGACY_BANDS)
    return build_field_with_stats(ra, dec, fov_arcmin, **kwargs)
