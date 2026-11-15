/**
 * Tombaugh Contract v1.0 as TypeScript shapes (docs/CONTRACT_FIELDS.md, sections 5 and 7).
 *
 * These mirror the wire format: keys are snake_case and units follow section 1 of the contract
 * (ICRS decimal degrees, MJD UTC, MJy/sr for images, µJy for fluxes, µm for wavelengths, mas/yr
 * for proper motions, mas for parallax). Unknown keys must be ignored.
 * The contract is the source of truth: change it first (with its owner), then this file.
 */

export const CONTRACT_VERSION = "1.0";

/** Section 2: allowed field-of-view values, arcmin. */
export const FOV_CHOICES_ARCMIN = [3, 4, 5, 6, 8, 10] as const;
export const DEFAULT_FOV_ARCMIN = 6;

/** Section 2: native SPHEREx pixel, arcsec. Frames are resampled to half of it, not sharper. */
export const NATIVE_PIXEL_ARCSEC = 6.15;

/** Section 4: a frame built from fewer exposures than this is "thin". */
export const THIN_EXPOSURES = 8;

/** Section 8: recorded real fields that exist at v1.0. */
export const FIXTURE_NAMES = ["wise0855", "barnard"] as const;

// ---------------------------------------------------------------------------------------------
// Section 5: manifest
// ---------------------------------------------------------------------------------------------

export type FieldStatus = "ready" | "partial" | "empty";

/** The `grid` object of a manifest. The field centre (`ra0`, `dec0`) is `Manifest.centre`. */
export interface Grid {
  nx: number;
  ny: number;
  /** Column of the pixel whose centre is exactly the field centre: (nx - 1) / 2. */
  cx: number;
  /** Row of that pixel: (ny - 1) / 2. */
  cy: number;
  /** Arcsec per pixel: 3.075. */
  pixscale_arcsec: number;
  projection: "TAN";
  /** Row 0 is the northern edge. */
  row0: "north";
  /** Column 0 is the eastern edge. */
  col0: "east";
}

/** One frame of the blink: a group of exposures close in time (section 3). */
export interface TimeBin {
  id: number;
  mjd_start: number;
  mjd_end: number;
  mjd_mid: number;
  /** ISO 8601 date, YYYY-MM-DD. */
  date_start: string;
  date_end: string;
  n_exposures: number;
  /** Detectors (1..6) that observed the field during this bin. */
  detectors: number[];
}

/** One of the 24 wavelength bins: id = (detector - 1) * 4 + sub (section 4). */
export interface WaveBin {
  id: number;
  detector: number;
  /** µm. */
  lam_min: number;
  /** µm. */
  lam_max: number;
}

export type PlaneKind = "sci" | "legacy";

/** One image in frames.bin: a (time bin, wave bin) stack, or a legacy survey image. */
export interface Plane {
  index: number;
  kind: PlaneKind;
  /** "SPHEREx" for science planes; "AllWISE" or "2MASS" for legacy planes. */
  mission: string;
  /** Null for legacy planes. */
  time_bin: number | null;
  /** Null for legacy planes. */
  wave_bin: number | null;
  /** "W1", "W2", "J", "H" or "Ks" for legacy planes, else null. */
  band: string | null;
  /** µm. */
  lam_min: number;
  /** µm. */
  lam_max: number;
  /** µm. */
  lam_eff: number;
  n_exposures: number;
  /** Robust noise of the plane, MJy/sr. */
  sigma: number;
  mjd_mid: number;
  date_start: string;
  date_end: string;
  /** Byte offset in frames.bin: index * ny * nx * 2. */
  offset: number;
  /** Legacy planes only: brightness is matched to field stars and is not comparable. */
  scaled?: "field_stars";
}

/** Where and how to read the frame file (section 6). */
export interface FramesInfo {
  url: string;
  dtype: "float16";
  byteorder: "little";
  /** Length of the uncompressed file in bytes. */
  nbytes: number;
  /** Hex SHA-256 of the uncompressed bytes. */
  sha256: string;
}

export interface TimeBinning {
  gap_days: number;
  max_span_days: number;
  sub_span_days: number;
}

export interface ExposureSummary {
  found: number;
  used: number;
  sampled: boolean;
  /** Exposure count per IRSA collection, e.g. { "spherex_dr1": 258 }. */
  collections: Record<string, number>;
  newest_mjd: number;
  newest_date: string;
}

export interface Provenance {
  pipeline_version: string;
  /** ISO 8601 UTC timestamp. */
  built_at: string;
  data_dois: string[];
  notes: string[];
}

/** A Gaia DR3 star recorded in a fixture manifest for decoder and grid tests. */
export interface FixtureStar {
  source_id: string;
  ra: number;
  dec: number;
  /** Plane pixel coordinates at the fixture's reference date. */
  x: number;
  y: number;
}

/** `GET /api/fields` once a field is ready (HTTP 200). */
export interface Manifest {
  contract: string;
  status: FieldStatus;
  /** Content key: centre, field of view, epoch_ref, pipeline version and exposure set. */
  key: string;
  request: { ra: number; dec: number; fov_arcmin: number };
  /** Field centre: the requested position rounded to 4 decimals. This is the grid's ra0, dec0. */
  centre: { ra: number; dec: number };
  /** Julian year that "where the object is now" refers to: 2026.0. */
  epoch_ref: number;
  grid: Grid;
  time_binning: TimeBinning;
  time_bins: TimeBin[];
  wave_bins: WaveBin[];
  /** Empty when status is "empty". */
  planes: Plane[];
  /** Null when status is "empty". */
  frames: FramesInfo | null;
  exposures: ExposureSummary;
  provenance: Provenance;
  warnings: string[];
  /** Fixture manifests only. */
  fixture_stars?: FixtureStar[];
}

// ---------------------------------------------------------------------------------------------
// Section 7: HTTP API
// ---------------------------------------------------------------------------------------------

export type BuildStage = "discover" | "fetch" | "stack";

/** HTTP 202 while a field is being built. Repeat the same GET to poll. */
export interface BuildingResponse {
  contract: string;
  status: "building";
  progress: { stage: BuildStage; done: number; total: number };
  /** Seconds to wait before the next poll. */
  retry_after_s: number;
}

export type ErrorCode = "bad_request" | "not_found" | "busy" | "upstream_unavailable" | "internal";

/** Body of every 4xx and 5xx answer. */
export interface ErrorResponse {
  contract: string;
  status: "error";
  code: ErrorCode;
  message: string;
}

// 7.1 Spectrum --------------------------------------------------------------------------------

export type SpectrumState = "ok" | "indicative" | "saturated" | "contaminated" | "no_data";
export type PointQuality = "good" | "flagged" | "saturated";

export interface CatalogueMatch {
  catalog: string;
  id: string;
  sep_arcsec: number;
}

/**
 * The contract shows `snapped_to` and the astrometry filled in; it does not say what they are
 * when no catalogued source is near, so they are typed as possibly null or absent here.
 */
export interface SpectrumTarget {
  ra: number;
  dec: number;
  snapped_to?: CatalogueMatch | null;
  /** mas/yr, includes cos(dec). */
  pmra?: number | null;
  /** mas/yr. */
  pmdec?: number | null;
  /** mas. */
  parallax?: number | null;
  /** Julian year of the catalogue position. */
  epoch?: number | null;
}

export interface SpectrumNeighbour extends CatalogueMatch {
  /** True when the neighbour was fitted jointly with the target. */
  fitted: boolean;
}

export interface SpectrumMethod {
  kind: "aperture" | "joint_psf";
  radius_px: number;
  encircled_energy: number;
  annulus_px: [number, number];
  /** Fractional systematic floor already folded into err_ujy. */
  systematic_floor: number;
}

/** One exposure's measurement. */
export interface SpectrumPoint {
  /** µm. */
  lam: number;
  /** µm. */
  dlam: number;
  mjd: number;
  det: number;
  time_bin: number;
  flux_ujy: number;
  /** Includes the systematic floor in quadrature. */
  err_ujy: number;
  /** SPHEREx bit mask OR-ed over the aperture. */
  flags: number;
  quality: PointQuality;
}

/** Measurements combined per time bin and wavelength range. */
export interface SpectrumBinnedPoint {
  time_bin: number;
  lam: number;
  lam_min: number;
  lam_max: number;
  flux_ujy: number;
  err_ujy: number;
  n: number;
}

/** `GET /api/fields/{key}/spectrum?ra=&dec=`. */
export interface SpectrumResponse {
  contract: string;
  status: "ok";
  state: SpectrumState;
  target: SpectrumTarget;
  neighbours: SpectrumNeighbour[];
  method: SpectrumMethod;
  time_span: { mjd_min: number; mjd_max: number };
  /** Empty when state is "saturated". */
  points: SpectrumPoint[];
  binned: SpectrumBinnedPoint[];
}

// 7.2 Resolve ---------------------------------------------------------------------------------

/** A fast mover whose track passed near a typed coordinate. */
export interface ResolveMover {
  name: string;
  ra_ref: number;
  dec_ref: number;
  moved_arcsec: number;
  pm_arcsec_yr: number;
  year_at_position: number;
}

/**
 * A resolved name or coordinate string. `ra`/`dec` are the catalogue position at `epoch`;
 * `ra_ref`/`dec_ref` are the position at `epoch_ref`, which is where clients centre.
 * A plain coordinate string resolves to itself, so its catalogue fields may be null.
 */
export interface ResolveOk {
  contract: string;
  status: "ok";
  query: string;
  name: string | null;
  ra: number;
  dec: number;
  epoch: number | null;
  /** mas/yr, includes cos(dec). */
  pmra: number | null;
  /** mas/yr. */
  pmdec: number | null;
  /** mas. */
  parallax: number | null;
  ra_ref: number;
  dec_ref: number;
  moved_arcsec: number;
  otype: string | null;
  source: string;
  /** Present for coordinate queries. */
  movers?: ResolveMover[];
}

export interface ResolveNotFound {
  contract: string;
  status: "not_found";
  query?: string;
  message?: string;
}

/** Planets, asteroids and comets are not resolved; `message` says why. */
export interface ResolveSolarSystem {
  contract: string;
  status: "solar_system";
  query?: string;
  message: string;
}

/** `GET /api/resolve?q=`. */
export type ResolveResponse = ResolveOk | ResolveNotFound | ResolveSolarSystem;

// 7.3 Overlays --------------------------------------------------------------------------------

export type UpstreamState = "ok" | "stale" | "unavailable";

/** Position of a moving source at the middle of one time bin, parallax included. */
export interface TrackPoint {
  time_bin: number;
  ra: number;
  dec: number;
}

/** Astrometry is null for Gaia sources without a five-parameter solution. */
export interface GaiaSource {
  source_id: string;
  ra: number;
  dec: number;
  epoch: number;
  pmra: number | null;
  pmdec: number | null;
  parallax: number | null;
  /** G magnitude. */
  g: number | null;
  /** Only for sources moving faster than 50 mas/yr. */
  track?: TrackPoint[];
}

export interface CatwiseSource {
  id: string;
  ra: number;
  dec: number;
  epoch: number;
  pmra: number | null;
  pmdec: number | null;
  /** W1 magnitude. */
  w1: number | null;
  /** W2 magnitude. */
  w2: number | null;
  /**
   * Section 7.3: "track is present only for sources moving faster than 50 mas/yr". The example
   * shows it on a Gaia source; the engine also sends it for CatWISE sources whose motion it trusts.
   */
  track?: TrackPoint[];
}

/** `GET /api/fields/{key}/overlays`. */
export interface OverlaysResponse {
  contract: string;
  status: "ok";
  gaia: GaiaSource[];
  catwise: CatwiseSource[];
  upstreams: { gaia: UpstreamState; catwise: UpstreamState };
}

// 7.4 Status ----------------------------------------------------------------------------------

export interface UpstreamHealth {
  ok: boolean;
  latency_ms: number;
  /** ISO 8601 UTC timestamp. */
  checked_at: string;
}

/** `GET /api/status`. */
export interface StatusResponse {
  contract: string;
  status: "ok";
  pipeline_version: string;
  newest_exposure: { mjd: number; date: string };
  /** Keyed by upstream name: "irsa_sia", "s3". */
  upstreams: Record<string, UpstreamHealth>;
  cache: { used_mb: number; free_mb: number };
  builds: { active: number; queued: number };
}
