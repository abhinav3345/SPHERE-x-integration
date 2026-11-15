"""Pydantic models of the wire format (Contract v1.0, sections 5 and 7).

These models are the source of truth for the JSON the API emits; ``docs/contract/manifest.schema.json`` is
exported from them with ``export_schema``. Field order follows the contract examples.

Two kinds of optional field exist and the difference is part of the contract:

* nullable fields are always present and serialise as ``null`` (for example ``Plane.band`` of a sci plane);
* fields named in a model's ``OMIT_IF_NONE`` are left out of the JSON when they are ``None`` (for example
  ``Plane.scaled``, ``Manifest.fixture_stars`` and a source's ``track``).

Units: degrees (ICRS), mas/yr and mas, MJD days, micron, MJy/sr for images and microjansky for flux densities.
NaN and infinity are rejected because JSON cannot carry them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from tombaugh.grid import PIXSCALE_ARCSEC, Grid
from tombaugh.types import Cutout, Exposure  # re-exported: Contract section 9 lists them with the models

CONTRACT_VERSION = "1.0"
Number = int | float  # a JSON number that keeps the way it was written (20 stays 20, 0.5 stays 0.5)

# fmt: off
__all__ = [
    "BinnedPoint", "BuildingResponse", "BuildsStatus", "CacheStatus", "CatwiseSource", "Centre",
    "ContractModel", "Cutout", "ErrorResponse", "Exposure", "ExposuresInfo", "FixtureStar", "FramesInfo",
    "GaiaSource", "GridModel", "Manifest", "Mover", "Neighbour", "NewestExposure", "OverlayUpstreams",
    "OverlaysResponse", "Plane", "Progress", "Provenance", "RequestInfo", "ResolveResponse", "SnappedTo",
    "SpectrumMethod", "SpectrumPoint", "SpectrumResponse", "SpectrumTarget", "StatusResponse", "TimeBin",
    "TimeBinning", "TimeSpan", "TrackPoint", "UpstreamHealth", "WaveBin", "export_schema", "manifest_schema",
]
# fmt: on


def _schema_required(schema: dict, model: type[ContractModel]) -> None:
    """JSON-schema hook: a field that may be absent from the emitted JSON is not listed as required."""
    required = [name for name in schema.get("required", []) if name not in model.may_be_absent()]
    if required:
        schema["required"] = required
    else:
        schema.pop("required", None)


class ContractModel(BaseModel):
    """Base of every wire model: unknown keys ignored, NaN refused, ``OMIT_IF_NONE`` fields left out."""

    model_config = ConfigDict(
        extra="ignore",
        allow_inf_nan=False,
        json_schema_serialization_defaults_required=True,
        json_schema_extra=_schema_required,
    )
    OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def may_be_absent(cls) -> frozenset[str]:
        """Names of the fields that can be missing from the emitted JSON."""
        return cls.OMIT_IF_NONE

    # No return annotation on purpose: with one, pydantic would describe the model as a free-form object.
    @model_serializer(mode="wrap")
    def _serialise(self, handler):
        data = handler(self)
        for name in self._omitted_when_none():
            if name in data and data[name] is None:
                del data[name]
        return data

    def _omitted_when_none(self) -> frozenset[str]:
        return self.OMIT_IF_NONE


# --------------------------------------------------------------------------------------- manifest (section 5)
class RequestInfo(ContractModel):
    """The request as received: position in degrees, field of view in arcmin."""

    ra: float
    dec: float
    fov_arcmin: int


class Centre(ContractModel):
    """Field centre in degrees: the requested position rounded to 4 decimals."""

    ra: float
    dec: float


class GridModel(ContractModel):
    """The sky grid of a field (Contract section 2); ``cx``, ``cy`` is the pixel on the field centre."""

    nx: int
    ny: int
    cx: int
    cy: int
    pixscale_arcsec: float = PIXSCALE_ARCSEC
    projection: Literal["TAN"] = "TAN"
    row0: Literal["north"] = "north"
    col0: Literal["east"] = "east"

    @classmethod
    def from_grid(cls, grid: Grid) -> GridModel:
        """The wire form of an in-process ``Grid``."""
        return cls(nx=grid.n, ny=grid.n, cx=grid.cx, cy=grid.cy, pixscale_arcsec=grid.pixscale)


class TimeBinning(ContractModel):
    """The three time-binning numbers, in days (Contract section 3)."""

    gap_days: Number = 20
    max_span_days: Number = 60
    sub_span_days: Number = 30


class TimeBin(ContractModel):
    """One frame of the blink: MJD limits in days, ISO dates, exposure count and contributing detectors."""

    id: int
    mjd_start: float
    mjd_end: float
    mjd_mid: float
    date_start: str
    date_end: str
    n_exposures: int
    detectors: list[int]


class WaveBin(ContractModel):
    """One of the 24 wavelength bins: ``id = (detector - 1) * 4 + sub``; limits in micron."""

    id: int
    detector: int
    lam_min: float
    lam_max: float


class Plane(ContractModel):
    """One image plane of frames.bin.

    ``kind`` "sci" is a SPHEREx stack of one (time bin, wave bin) and has ``band`` null. ``kind`` "legacy"
    is a Then & Now plane: ``mission`` AllWISE or 2MASS, a ``band``, ``time_bin`` and ``wave_bin`` null, and
    ``scaled`` "field_stars". Wavelengths in micron, ``sigma`` in MJy/sr, ``offset`` in bytes.
    """

    OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"scaled"})

    index: int
    kind: Literal["sci", "legacy"]
    mission: Literal["SPHEREx", "AllWISE", "2MASS"]
    time_bin: int | None
    wave_bin: int | None
    band: Literal["W1", "W2", "J", "H", "Ks"] | None = None
    lam_min: float
    lam_max: float
    lam_eff: float
    n_exposures: int
    sigma: float
    mjd_mid: float
    date_start: str
    date_end: str
    offset: int
    scaled: Literal["field_stars"] | None = None

    @model_validator(mode="after")
    def _check_kind(self) -> Plane:
        if self.kind == "sci":
            if self.mission != "SPHEREx" or self.time_bin is None or self.wave_bin is None:
                raise ValueError("a sci plane needs mission SPHEREx, a time_bin and a wave_bin")
            if self.band is not None or self.scaled is not None:
                raise ValueError("a sci plane has band null and no scaled field")
        else:
            if self.mission == "SPHEREx" or self.band is None:
                raise ValueError("a legacy plane needs mission AllWISE or 2MASS and a band")
            if self.time_bin is not None or self.wave_bin is not None:
                raise ValueError("a legacy plane has time_bin and wave_bin null")
        return self


class FramesInfo(ContractModel):
    """Where and what frames.bin is: ``nbytes`` and ``sha256`` are of the uncompressed bytes."""

    url: str
    dtype: Literal["float16"] = "float16"
    byteorder: Literal["little"] = "little"
    nbytes: int
    sha256: str


class ExposuresInfo(ContractModel):
    """How many exposures were found and used; ``newest_*`` are null when none exists."""

    found: int
    used: int
    sampled: bool
    collections: dict[str, int]
    newest_mjd: float | None
    newest_date: str | None


class Provenance(ContractModel):
    """Pipeline version, build time (ISO 8601 UTC, ``Z`` suffix), data DOIs and plain-language notes."""

    pipeline_version: str
    built_at: str
    data_dois: list[str]
    notes: list[str]


class FixtureStar(ContractModel):
    """A Gaia DR3 star of a fixture at its reference date: sky position in degrees and grid pixel (x, y)."""

    source_id: str
    ra: float
    dec: float
    x: float
    y: float


class Manifest(ContractModel):
    """The answer of ``GET /api/fields`` when a field is ready (HTTP 200).

    ``status`` "empty" means no public exposure covers the position: ``planes`` is empty and ``frames`` is
    null. ``fixture_stars`` exists only in fixture manifests.
    """

    OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"fixture_stars"})

    contract: str = CONTRACT_VERSION
    status: Literal["ready", "partial", "empty"]
    key: str
    request: RequestInfo
    centre: Centre
    epoch_ref: float = 2026.0
    grid: GridModel
    time_binning: TimeBinning = Field(default_factory=TimeBinning)
    time_bins: list[TimeBin]
    wave_bins: list[WaveBin]
    planes: list[Plane]
    frames: FramesInfo | None
    exposures: ExposuresInfo
    provenance: Provenance
    warnings: list[str] = Field(default_factory=list)
    fixture_stars: list[FixtureStar] | None = None

    @model_validator(mode="after")
    def _check_empty(self) -> Manifest:
        if self.status == "empty" and (self.planes or self.frames is not None):
            raise ValueError('an "empty" manifest has no planes and frames null')
        if self.status != "empty" and self.planes and self.frames is None:
            raise ValueError("a manifest with planes needs frames")
        return self


# --------------------------------------------------------------------------- building and errors (section 7)
class Progress(ContractModel):
    """Build progress: ``done`` of ``total`` units in the current stage."""

    stage: Literal["discover", "fetch", "stack"]
    done: int
    total: int


class BuildingResponse(ContractModel):
    """HTTP 202 while a field is being built; poll again after ``retry_after_s`` seconds."""

    contract: str = CONTRACT_VERSION
    status: Literal["building"] = "building"
    progress: Progress
    retry_after_s: Number = 1


class ErrorResponse(ContractModel):
    """Error body.

    HTTP status per code: bad_request 400, not_found 404, busy 429, upstream_unavailable 503, internal 500.
    """

    contract: str = CONTRACT_VERSION
    status: Literal["error"] = "error"
    code: Literal["bad_request", "not_found", "busy", "upstream_unavailable", "internal"]
    message: str


# ------------------------------------------------------------------------------------- spectrum (section 7.1)
class SnappedTo(ContractModel):
    """The catalogue source a clicked position was snapped to; separation in arcsec."""

    catalog: str
    id: str
    sep_arcsec: float


class SpectrumTarget(ContractModel):
    """Measured position in degrees; astrometry of the snapped source (mas/yr, mas, Julian year) or nulls."""

    ra: float
    dec: float
    snapped_to: SnappedTo | None = None
    pmra: float | None = None
    pmdec: float | None = None
    parallax: float | None = None
    epoch: float | None = None


class Neighbour(ContractModel):
    """A catalogued neighbour; ``fitted`` says whether it was fitted jointly. Separation in arcsec."""

    catalog: str
    id: str
    sep_arcsec: float
    fitted: bool


class SpectrumMethod(ContractModel):
    """How the fluxes were measured. Radii in native pixels; ``systematic_floor`` is a flux fraction."""

    kind: Literal["aperture", "joint_psf"]
    radius_px: Number
    encircled_energy: float
    annulus_px: tuple[Number, Number]
    systematic_floor: float


class TimeSpan(ContractModel):
    """First and last exposure used, MJD days."""

    mjd_min: float
    mjd_max: float


class SpectrumPoint(ContractModel):
    """One exposure's measurement: wavelength and bandwidth in micron, flux density and error in microjansky.

    ``err_ujy`` includes the systematic floor in quadrature; ``flags`` is the SPHEREx bit mask OR-ed over
    the aperture.
    """

    lam: float
    dlam: float
    mjd: float
    det: int
    time_bin: int
    flux_ujy: float
    err_ujy: float
    flags: int
    quality: Literal["good", "flagged", "saturated"]


class BinnedPoint(ContractModel):
    """Measurements combined per time bin and wavelength range (micron); flux density in microjansky."""

    time_bin: int
    lam: float
    lam_min: float
    lam_max: float
    flux_ujy: float
    err_ujy: float
    n: int


class SpectrumResponse(ContractModel):
    """Quick-look spectrophotometry at a position. ``time_span`` is null when no exposure was measured."""

    contract: str = CONTRACT_VERSION
    status: Literal["ok"] = "ok"
    state: Literal["ok", "indicative", "saturated", "contaminated", "no_data"]
    target: SpectrumTarget
    neighbours: list[Neighbour] = Field(default_factory=list)
    method: SpectrumMethod
    time_span: TimeSpan | None
    points: list[SpectrumPoint] = Field(default_factory=list)
    binned: list[BinnedPoint] = Field(default_factory=list)


# -------------------------------------------------------------------------------------- resolve (section 7.2)
class Mover(ContractModel):
    """A fast mover that passed the typed position: where it is at ``epoch_ref`` and how far it moved."""

    name: str
    ra_ref: float
    dec_ref: float
    moved_arcsec: float
    pm_arcsec_yr: float
    year_at_position: float


class ResolveResponse(ContractModel):
    """Name or coordinate string to position.

    ``ra``/``dec`` are the catalogue position at ``epoch``; ``ra_ref``/``dec_ref`` the position at
    ``epoch_ref``. With ``status`` "ok" every field of the contract example is present (null when unknown)
    and ``movers`` and ``message`` appear only when set. With "not_found" or "solar_system" only the fields
    that are set appear.
    """

    OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"movers", "message"})

    contract: str = CONTRACT_VERSION
    status: Literal["ok", "not_found", "solar_system"]
    query: str
    name: str | None = None
    ra: float | None = None
    dec: float | None = None
    epoch: float | None = None
    pmra: float | None = None
    pmdec: float | None = None
    parallax: float | None = None
    ra_ref: float | None = None
    dec_ref: float | None = None
    moved_arcsec: float | None = None
    otype: str | None = None
    source: str | None = None
    movers: list[Mover] | None = None
    message: str | None = None

    @classmethod
    def may_be_absent(cls) -> frozenset[str]:
        return frozenset(cls.model_fields) - {"contract", "status", "query"}

    def _omitted_when_none(self) -> frozenset[str]:
        if self.status == "ok":
            return self.OMIT_IF_NONE
        return frozenset(type(self).model_fields)

    @model_validator(mode="after")
    def _check_ok(self) -> ResolveResponse:
        if self.status == "ok" and None in (self.ra, self.dec, self.ra_ref, self.dec_ref):
            raise ValueError('an "ok" resolve answer needs ra, dec, ra_ref and dec_ref')
        return self


# ------------------------------------------------------------------------------------- overlays (section 7.3)
class TrackPoint(ContractModel):
    """Where a moving source is at the middle of one time bin, degrees."""

    time_bin: int
    ra: float
    dec: float


class GaiaSource(ContractModel):
    """A Gaia DR3 source at its catalogue ``epoch``. ``track`` exists only above 50 mas/yr."""

    OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"track"})

    source_id: str
    ra: float
    dec: float
    epoch: float
    pmra: float | None
    pmdec: float | None
    parallax: float | None
    g: float | None
    track: list[TrackPoint] | None = None


class CatwiseSource(ContractModel):
    """A CatWISE2020 source at its catalogue ``epoch``; W1, W2 in Vega magnitudes. ``track`` as for Gaia."""

    OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"track"})

    id: str
    ra: float
    dec: float
    epoch: float
    pmra: float | None
    pmdec: float | None
    w1: float | None
    w2: float | None
    track: list[TrackPoint] | None = None


UpstreamState = Literal["ok", "stale", "unavailable"]


class OverlayUpstreams(ContractModel):
    """Health of the two catalogue services: "stale" means a cached copy was served."""

    gaia: UpstreamState
    catwise: UpstreamState


class OverlaysResponse(ContractModel):
    """Gaia DR3 and CatWISE sources in the field."""

    contract: str = CONTRACT_VERSION
    status: Literal["ok"] = "ok"
    gaia: list[GaiaSource] = Field(default_factory=list)
    catwise: list[CatwiseSource] = Field(default_factory=list)
    upstreams: OverlayUpstreams


# --------------------------------------------------------------------------------------- status (section 7.4)
class NewestExposure(ContractModel):
    """The newest public exposure known to the service."""

    mjd: float
    date: str


class UpstreamHealth(ContractModel):
    """One upstream's last check; ``latency_ms`` and ``checked_at`` are null before the first check."""

    ok: bool
    latency_ms: Number | None
    checked_at: str | None


class CacheStatus(ContractModel):
    """Disk cache use in megabytes."""

    used_mb: Number
    free_mb: Number


class BuildsStatus(ContractModel):
    """Builds running and waiting."""

    active: int
    queued: int


class StatusResponse(ContractModel):
    """Pipeline version, newest public exposure, upstream health, cache and build state."""

    contract: str = CONTRACT_VERSION
    status: Literal["ok"] = "ok"
    pipeline_version: str
    newest_exposure: NewestExposure | None
    upstreams: dict[str, UpstreamHealth]
    cache: CacheStatus
    builds: BuildsStatus


# ------------------------------------------------------------------------------------------------ JSON schema
def manifest_schema() -> dict:
    """JSON schema of the manifest as emitted: every field required except those omitted when null."""
    schema = Manifest.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "Tombaugh manifest (Contract v1.0)"
    return schema


def export_schema(path: str | Path) -> None:
    """Write the manifest JSON schema to ``path`` (UTF-8, sorted keys, trailing newline)."""
    text = json.dumps(manifest_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    Path(path).write_text(text, encoding="utf-8")
