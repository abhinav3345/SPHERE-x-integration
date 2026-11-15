/**
 * Loads a field: its manifest from `GET /api/fields`, then its frame file (Contract v1.0,
 * sections 5 to 7).
 *
 * - While the API answers 202 the same URL is polled and progress is reported.
 * - `status: "empty"` is a normal answer (no public exposure covers the position), not an error.
 * - Error answers become a `FieldError` carrying the contract's `code`.
 * - A fixture falls back to the copy bundled with the site when the API cannot be reached, so
 *   the recorded fields work with no back end at all.
 * - A recorded field may also carry recorded answers of the overlays and spectrum routes, in the
 *   same folder: loadRecordedOverlays and loadRecordedSpectrum read them, null when there is none.
 * - The engine answers at /api on the page's own origin, or at VITE_ENGINE_URL when that is set
 *   (an origin such as https://engine.example; .env.example). Paths stay "/api/...".
 */
import {
  type BuildingResponse,
  type BuildStage,
  type ErrorCode,
  FOV_CHOICES_ARCMIN,
  type Manifest,
  type OverlaysResponse,
  type SpectrumResponse,
  type StatusResponse,
} from "./contract";

const FIELDS_URL = "/api/fields";
const STATUS_URL = "/api/status";

/** The engine's origin, without a trailing slash; "" when the page and the engine share one. */
export const ENGINE_URL = String(import.meta.env.VITE_ENGINE_URL ?? "").replace(/\/+$/, "");

/**
 * An engine path ("/api/...") at the engine's address. A full URL, or a path that does not start
 * with "/", is returned as it is: `frames.url` is opaque and is only resolved against the engine.
 */
export function engineUrl(path: string, base: string = ENGINE_URL): string {
  const origin = base.replace(/\/+$/, "");
  if (!origin || !path.startsWith("/") || path.startsWith("//")) return path;
  return `${origin}${path}`;
}

/** The origin of a URL, resolved against `base`; null when it cannot be read. */
function originOf(url: string, base: string): string | null {
  try {
    return new URL(url, base).origin;
  } catch {
    return null;
  }
}

/** Stands in for the page where there is none (tests, tools), so that a path stays "on the page". */
const NO_PAGE = "http://page.invalid/";

/**
 * True when a URL the engine handed over (`frames.url`, opaque) points at the page's own origin or
 * at the configured engine: the page makes no request to any other origin (CLAUDE.md, front end).
 *
 * The URL is always resolved the way `fetch` will resolve it, against the page, and only the
 * resulting origin is compared. There is no shortcut for text that "looks like a path": the URL
 * parser reads "/\host", " //host" and "ht\ntp://host" as other sites, so only its answer counts.
 */
export function isEngineOrigin(
  url: string,
  base: string = ENGINE_URL,
  page: string | null = globalThis.location?.href ?? null,
): boolean {
  const pageUrl = page ?? NO_PAGE;
  const allowed = new Set<string>();
  const own = originOf(pageUrl, pageUrl);
  if (own) allowed.add(own);
  const engine = base.replace(/\/+$/, "");
  if (engine) {
    const origin = originOf(engine, pageUrl);
    if (origin) allowed.add(origin);
  }
  const target = originOf(url, pageUrl);
  return target !== null && target !== "null" && allowed.has(target);
}

/** Poll interval when the API does not say, s. */
const POLL_DEFAULT_S = 1;
/** The API cancels a build nobody has polled for 20 s, so never wait long. */
const POLL_MIN_S = 0.2;
const POLL_MAX_S = 5;
/** Give up polling after this long, ms. The API itself answers "partial" at 120 s. */
const BUILD_DEADLINE_MS = 180_000;
/** Pauses before the second and third attempt of a request that failed to connect, ms. */
const RETRY_DELAYS_MS = [300, 900];

/** A position (degrees, field of view in arcmin) or the name of a recorded field. */
export type FieldRequest = { ra: number; dec: number; fov: number } | { fixture: string };

export type FieldSource = "api" | "bundled";

export interface LoadedField {
  manifest: Manifest;
  /** The uncompressed frame file; null when the field is empty. */
  frames: ArrayBuffer | null;
  /** "bundled" when the copy shipped with the site was used because the API was unreachable. */
  source: FieldSource;
}

export interface LoadProgress {
  /** A build stage reported by the API, or "frames" while the frame file downloads. */
  stage: BuildStage | "frames";
  /** Units done so far (exposures for build stages); null when unknown. */
  done: number | null;
  /** Units in total (exposures for build stages, bytes for "frames"); null when unknown. */
  total: number | null;
}

export type FieldErrorCode =
  | ErrorCode
  /** The API did not answer at all. */
  | "unreachable"
  /** A recorded field is not bundled with this build and the API did not answer. */
  | "fixture_missing"
  /** The answer does not follow the contract. */
  | "bad_response"
  /** The frame file does not match its manifest. */
  | "bad_frames"
  /** The build did not finish in time. */
  | "timeout";

export class FieldError extends Error {
  override readonly name = "FieldError";

  constructor(
    readonly code: FieldErrorCode,
    message: string,
    /** Seconds to wait before trying again, when the API said so (429). */
    readonly retryAfterS?: number,
  ) {
    super(message);
  }
}

export interface LoadOptions {
  signal?: AbortSignal;
  onProgress?: (progress: LoadProgress) => void;
  /** Replaceable for tests. */
  fetchImpl?: typeof fetch;
  /** Replaceable for tests: resolves after `ms`, rejects if the signal aborts first. */
  sleep?: (ms: number, signal?: AbortSignal) => Promise<void>;
  /** Replaceable for tests: clock in ms. */
  now?: () => number;
  /** Replaceable for tests: the engine's origin (default ENGINE_URL). */
  engine?: string;
}

type Context = Required<Pick<LoadOptions, "fetchImpl" | "sleep" | "now" | "engine">> &
  Pick<LoadOptions, "signal" | "onProgress">;

/** Raised internally when nothing that speaks the contract answered. */
class ApiUnreachable extends Error {}

function defaultSleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(signal.reason);
      },
      { once: true },
    );
  });
}

function isAbort(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

/** Checks a request before any network call; throws `FieldError("bad_request")`. */
export function checkRequest(request: FieldRequest): void {
  if ("fixture" in request) {
    if (!/^[a-z0-9][a-z0-9_-]*$/.test(request.fixture)) {
      throw new FieldError("bad_request", "That is not the name of a recorded field.");
    }
    return;
  }
  const { ra, dec, fov } = request;
  if (!Number.isFinite(ra) || ra < 0 || ra > 360) {
    throw new FieldError("bad_request", "Right ascension must be between 0 and 360 degrees.");
  }
  if (!Number.isFinite(dec) || dec < -90 || dec > 90) {
    throw new FieldError("bad_request", "Declination must be between -90 and 90 degrees.");
  }
  if (!(FOV_CHOICES_ARCMIN as readonly number[]).includes(fov)) {
    const choices = FOV_CHOICES_ARCMIN.join(", ");
    throw new FieldError("bad_request", `Field of view must be one of ${choices} arcmin.`);
  }
}

/** The `GET /api/fields` URL of a request. Repeating it polls the same build. */
export function fieldUrl(request: FieldRequest): string {
  const query =
    "fixture" in request
      ? new URLSearchParams({ fixture: request.fixture })
      : new URLSearchParams({
          ra: String(request.ra),
          dec: String(request.dec),
          fov: String(request.fov),
        });
  return `${FIELDS_URL}?${query}`;
}

/** Checks a downloaded frame file against its manifest; throws `FieldError("bad_frames")`. */
export function checkFrames(manifest: Manifest, buffer: ArrayBuffer): void {
  const { frames, grid, planes } = manifest;
  if (!frames) throw new FieldError("bad_frames", "The manifest has no frame file.");
  if (buffer.byteLength !== frames.nbytes) {
    throw new FieldError(
      "bad_frames",
      `The frame file is ${buffer.byteLength} bytes long; its manifest says ${frames.nbytes}. The download is incomplete or out of date.`,
    );
  }
  const expected = planes.length * grid.nx * grid.ny * 2;
  if (frames.nbytes !== expected) {
    throw new FieldError(
      "bad_frames",
      `The manifest lists ${planes.length} planes of ${grid.nx} x ${grid.ny} pixels (${expected} bytes), but its frame file is ${frames.nbytes} bytes.`,
    );
  }
}

/** One GET with two more attempts when the connection itself fails. */
async function fetchWithRetry(url: string, accept: string, context: Context): Promise<Response> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await context.fetchImpl(url, {
        headers: { Accept: accept },
        signal: context.signal,
      });
    } catch (error) {
      if (isAbort(error) || context.signal?.aborted) throw error;
      if (attempt >= RETRY_DELAYS_MS.length) throw new ApiUnreachable();
      await context.sleep(RETRY_DELAYS_MS[attempt], context.signal);
    }
  }
}

/**
 * The JSON body when it carries the contract's `contract` key, else null. A dev proxy with no
 * back end and a static host both answer `/api/...` with something else (an error page).
 */
async function contractBody(response: Response): Promise<Record<string, unknown> | null> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "contract" in body) {
      const record = body as Record<string, unknown>;
      if (typeof record.contract === "string") return record;
    }
  } catch {
    // Not JSON: not our API.
  }
  return null;
}

/**
 * Set by the site's own proxy (web/functions/api) on the 503 it writes when the API address is
 * not configured or the API does not answer. The body then has the contract's error shape, but
 * it does not come from the API.
 */
const PROXY_ERROR_HEADER = "x-tombaugh-proxy-error";

/** The contract JSON of an answer that really comes from the API; throws `ApiUnreachable` else. */
async function apiBody(response: Response): Promise<Record<string, unknown>> {
  const body = response.headers.has(PROXY_ERROR_HEADER) ? null : await contractBody(response);
  if (body === null) throw new ApiUnreachable();
  return body;
}

const ERROR_CODES: readonly ErrorCode[] = [
  "bad_request",
  "not_found",
  "busy",
  "upstream_unavailable",
  "internal",
];

const CODE_BY_HTTP_STATUS: Record<number, ErrorCode> = {
  400: "bad_request",
  404: "not_found",
  429: "busy",
  503: "upstream_unavailable",
};

const DEFAULT_MESSAGES: Record<ErrorCode, string> = {
  bad_request: "The API rejected the position or field of view.",
  not_found: "The API does not know this field.",
  busy: "The build queue is full. Try again shortly.",
  upstream_unavailable: "The SPHEREx archive cannot be reached and this field is not cached.",
  internal: "The API failed while building this field.",
};

function errorFrom(body: Record<string, unknown>, response: Response): FieldError {
  const stated = ERROR_CODES.find((code) => code === body.code);
  const code = stated ?? CODE_BY_HTTP_STATUS[response.status] ?? "internal";
  const message =
    typeof body.message === "string" && body.message ? body.message : DEFAULT_MESSAGES[code];
  const retryAfter = Number(response.headers.get("Retry-After"));
  return new FieldError(code, message, retryAfter > 0 ? retryAfter : undefined);
}

/** Checks that a 200 answer is a manifest this code can draw. */
function checkManifest(body: Record<string, unknown>): Manifest {
  const manifest = body as unknown as Manifest;
  const bad = (what: string) => new FieldError("bad_response", `Unusable manifest: ${what}.`);
  if (!manifest.contract.startsWith("1.")) {
    throw bad(`it uses contract ${manifest.contract}, this page understands 1.x`);
  }
  if (manifest.status === "empty") return manifest;
  if (manifest.status !== "ready" && manifest.status !== "partial") {
    throw bad(`unknown status "${String(manifest.status)}"`);
  }
  const { grid, frames, planes, time_bins: timeBins, centre } = manifest;
  if (!grid || !frames || !centre || !Array.isArray(planes) || !Array.isArray(timeBins)) {
    throw bad("the grid, centre, planes, time bins or frame file are missing");
  }
  const { wave_bins: waveBins, warnings, exposures, provenance } = manifest;
  if (!Array.isArray(waveBins) || !Array.isArray(warnings) || !exposures || !provenance) {
    throw bad("the wave bins, warnings, exposure summary or provenance are missing");
  }
  if (grid.projection !== "TAN" || grid.row0 !== "north" || grid.col0 !== "east") {
    throw bad("its grid is not the north-up, east-left TAN grid of the contract");
  }
  if (frames.dtype !== "float16" || frames.byteorder !== "little") {
    throw bad("its frame file is not little-endian float16");
  }
  return manifest;
}

function pollDelayMs(building: Partial<BuildingResponse>): number {
  const stated = Number(building.retry_after_s);
  const seconds = Number.isFinite(stated) && stated > 0 ? stated : POLL_DEFAULT_S;
  return 1000 * Math.min(POLL_MAX_S, Math.max(POLL_MIN_S, seconds));
}

/** GETs the manifest, polling the same URL for as long as the API answers 202. */
async function requestManifest(url: string, context: Context): Promise<Manifest> {
  const startedAt = context.now();
  for (;;) {
    const response = await fetchWithRetry(url, "application/json", context);
    const body = await apiBody(response);
    if (response.status === 202 || body.status === "building") {
      const building = body as Partial<BuildingResponse>;
      context.onProgress?.({
        stage: building.progress?.stage ?? "discover",
        done: building.progress?.done ?? null,
        total: building.progress?.total ?? null,
      });
      if (context.now() - startedAt > BUILD_DEADLINE_MS) {
        throw new FieldError("timeout", "The build did not finish in time. Try again.");
      }
      await context.sleep(pollDelayMs(building), context.signal);
      continue;
    }
    if (!response.ok || body.status === "error") throw errorFrom(body, response);
    return checkManifest(body);
  }
}

/** Downloads the frame file and checks its length against the manifest. */
async function fetchFrames(
  url: string,
  manifest: Manifest,
  context: Context,
): Promise<ArrayBuffer> {
  context.onProgress?.({ stage: "frames", done: null, total: manifest.frames?.nbytes ?? null });
  const response = await fetchWithRetry(url, "application/octet-stream", context);
  if (!response.ok) throw errorFrom(await apiBody(response), response);
  const buffer = await response.arrayBuffer();
  checkFrames(manifest, buffer);
  return buffer;
}

async function loadFromApi(request: FieldRequest, context: Context): Promise<LoadedField> {
  const manifest = await requestManifest(engineUrl(fieldUrl(request), context.engine), context);
  if (manifest.status === "empty" || !manifest.frames) {
    return { manifest, frames: null, source: "api" };
  }
  const framesUrl = engineUrl(manifest.frames.url, context.engine);
  if (!isEngineOrigin(framesUrl, context.engine)) {
    throw new FieldError(
      "bad_response",
      "The manifest points its frame file at another site, so it is not loaded.",
    );
  }
  const frames = await fetchFrames(framesUrl, manifest, context);
  return { manifest, frames, source: "api" };
}

/** The copy of a recorded field shipped with the site under fixtures/<name>/. */
async function loadBundled(name: string, context: Context): Promise<LoadedField> {
  const folder = `${import.meta.env.BASE_URL}fixtures/${name}`;
  const missing = new FieldError(
    "fixture_missing",
    `The recorded field "${name}" is not bundled with this build, and the API cannot be reached.`,
  );
  try {
    const response = await fetchWithRetry(`${folder}/manifest.json`, "application/json", context);
    const body = response.ok ? await contractBody(response) : null;
    if (body === null) throw missing;
    const manifest = checkManifest(body);
    if (manifest.status === "empty" || !manifest.frames) {
      return { manifest, frames: null, source: "bundled" };
    }
    const frames = await fetchFrames(`${folder}/frames.bin`, manifest, context);
    return { manifest, frames, source: "bundled" };
  } catch (error) {
    if (error instanceof ApiUnreachable) throw missing;
    throw error;
  }
}

function contextOf(options: LoadOptions): Context {
  return {
    signal: options.signal,
    onProgress: options.onProgress,
    fetchImpl: options.fetchImpl ?? ((input, init) => fetch(input, init)),
    sleep: options.sleep ?? defaultSleep,
    now: options.now ?? (() => Date.now()),
    engine: options.engine ?? ENGINE_URL,
  };
}

/**
 * The copy of a recorded field bundled with the site, without asking the engine first: for when
 * a load has just shown that no engine answers. Rejects with a `FieldError` ("fixture_missing"
 * when it is not bundled), or with the abort reason.
 */
export async function loadBundledField(
  name: string,
  options: LoadOptions = {},
): Promise<LoadedField> {
  checkRequest({ fixture: name });
  return loadBundled(name, contextOf(options));
}

/**
 * Loads a field by position or by fixture name.
 * Rejects with a `FieldError`, or with the abort reason when `options.signal` aborts.
 */
export async function loadField(
  request: FieldRequest,
  options: LoadOptions = {},
): Promise<LoadedField> {
  checkRequest(request);
  const context = contextOf(options);
  try {
    return await loadFromApi(request, context);
  } catch (error) {
    if (!(error instanceof ApiUnreachable)) throw error;
    if ("fixture" in request) return loadBundled(request.fixture, context);
    throw new FieldError(
      "unreachable",
      "The Tombaugh API cannot be reached, so a new field cannot be built right now.",
    );
  }
}

// ---------------------------------------------------------------------------------------------
// Sections 7.1 and 7.3: the spectrum and the catalogue overlays of a field on screen
// ---------------------------------------------------------------------------------------------

/** Give up waiting for overlays after this long, ms. */
const OVERLAYS_DEADLINE_MS = 60_000;
/** Give up waiting for a spectrum after this long, ms (it reads every exposure again). */
const SPECTRUM_DEADLINE_MS = 180_000;

const SPECTRUM_STATES = ["ok", "indicative", "saturated", "contaminated", "no_data"];

/** Progress of a spectrum the engine is still measuring (an HTTP 202, as for a build). */
export interface MeasureProgress {
  done: number | null;
  total: number | null;
}

export interface ExtraOptions
  extends Pick<LoadOptions, "signal" | "fetchImpl" | "sleep" | "now" | "engine"> {
  onProgress?: (progress: MeasureProgress) => void;
}

/** A field key as the manifest gives it; anything else is refused before a request. */
function checkKey(key: string): void {
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(key)) {
    throw new FieldError("bad_request", "That is not the key of a field.");
  }
}

/**
 * Contract 7.1: a spectrum missing some exposures comes with this header, "<n> of <m> exposures
 * not measured; not cached".
 */
const INCOMPLETE_HEADER = "x-tombaugh-incomplete";

/** A spectrum as the engine answered it, with its X-Tombaugh-Incomplete header when it sent one. */
export type SpectrumAnswer = SpectrumResponse & { incomplete?: string };

/** GETs a JSON answer of the engine, polling the same URL while it answers 202. */
async function pollJson(
  url: string,
  context: Context,
  deadlineMs: number,
  onProgress?: (progress: MeasureProgress) => void,
  onAnswer?: (response: Response) => void,
): Promise<Record<string, unknown>> {
  const startedAt = context.now();
  for (;;) {
    let response: Response;
    let body: Record<string, unknown>;
    try {
      response = await fetchWithRetry(url, "application/json", context);
      body = await apiBody(response);
    } catch (error) {
      if (error instanceof ApiUnreachable) {
        throw new FieldError("unreachable", "The Tombaugh API cannot be reached right now.");
      }
      throw error;
    }
    if (response.status === 202 || body.status === "building") {
      const building = body as Partial<BuildingResponse>;
      onProgress?.({
        done: building.progress?.done ?? null,
        total: building.progress?.total ?? null,
      });
      if (context.now() - startedAt > deadlineMs) {
        throw new FieldError("timeout", "The engine did not answer in time. Try again.");
      }
      await context.sleep(pollDelayMs(building), context.signal);
      continue;
    }
    if (!response.ok || body.status === "error") throw errorFrom(body, response);
    onAnswer?.(response);
    return body;
  }
}

function extraContext(options: ExtraOptions): Context {
  return contextOf({ ...options, onProgress: undefined });
}

// The shapes of sections 7.1 and 7.3 as the engine's models write them (api/tombaugh/models.py,
// which refuse NaN): every field the contract names, with its type. An answer of another shape
// is refused whole, live or recorded, so that nothing on the page reads a field that is missing.

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** Each of `names` is a finite number in `item`. */
const numbers = (item: Record<string, unknown>, ...names: string[]) =>
  names.every((name) => typeof item[name] === "number" && Number.isFinite(item[name]));

/** Each of `names` is a finite number or null in `item` (present either way). */
const numbersOrNull = (item: Record<string, unknown>, ...names: string[]) =>
  names.every((name) => item[name] === null || numbers(item, name));

/** An array of objects that each pass `check`. */
const listOf = (value: unknown, check: (item: Record<string, unknown>) => boolean) =>
  Array.isArray(value) && value.every((item) => isObject(item) && check(item));

const oneOf = (value: unknown, names: readonly string[]) =>
  typeof value === "string" && names.includes(value);

const UPSTREAM_STATES = ["ok", "stale", "unavailable"];

/** A track of 7.3: absent, or one position per time bin. */
const isTrack = (track: unknown) =>
  track === undefined ||
  track === null ||
  listOf(track, (p) => numbers(p, "time_bin", "ra", "dec"));

const isGaiaSource = (s: Record<string, unknown>) =>
  typeof s.source_id === "string" &&
  numbers(s, "ra", "dec", "epoch") &&
  numbersOrNull(s, "pmra", "pmdec", "parallax", "g") &&
  isTrack(s.track);

const isCatwiseSource = (s: Record<string, unknown>) =>
  typeof s.id === "string" &&
  numbers(s, "ra", "dec", "epoch") &&
  numbersOrNull(s, "pmra", "pmdec", "w1", "w2") &&
  isTrack(s.track);

/** A 200 answer of the overlays route as the contract shapes it; throws `FieldError` else. */
function checkOverlays(body: Record<string, unknown>): OverlaysResponse {
  const { upstreams } = body;
  if (
    body.status !== "ok" ||
    !listOf(body.gaia, isGaiaSource) ||
    !listOf(body.catwise, isCatwiseSource) ||
    !isObject(upstreams) ||
    !oneOf(upstreams.gaia, UPSTREAM_STATES) ||
    !oneOf(upstreams.catwise, UPSTREAM_STATES)
  ) {
    throw new FieldError("bad_response", "The catalogue answer does not follow the contract.");
  }
  return body as unknown as OverlaysResponse;
}

/** `GET /api/fields/{key}/overlays`: Gaia DR3 and CatWISE sources of a field (section 7.3). */
export async function loadOverlays(
  key: string,
  options: ExtraOptions = {},
): Promise<OverlaysResponse> {
  checkKey(key);
  const context = extraContext(options);
  const url = engineUrl(`${FIELDS_URL}/${key}/overlays`, context.engine);
  return checkOverlays(await pollJson(url, context, OVERLAYS_DEADLINE_MS));
}

/** The `spectrum` URL of a position: decimal degrees, as many digits as given. */
export function spectrumUrl(key: string, ra: number, dec: number): string {
  const query = new URLSearchParams({ ra: String(ra), dec: String(dec) });
  return `${FIELDS_URL}/${key}/spectrum?${query}`;
}

/** True for a position on the sky: RA in [0, 360), Dec in [-90, 90], degrees. */
const onTheSky = (ra: number, dec: number) =>
  Number.isFinite(ra) && ra >= 0 && ra < 360 && Number.isFinite(dec) && Math.abs(dec) <= 90;

const POINT_QUALITIES = ["good", "flagged", "saturated"];
const METHOD_KINDS = ["aperture", "joint_psf"];

/** The method of 7.1: its kind and its radii, energy and floor. */
const isMethod = (method: unknown) =>
  isObject(method) &&
  oneOf(method.kind, METHOD_KINDS) &&
  numbers(method, "radius_px", "encircled_energy", "systematic_floor") &&
  Array.isArray(method.annulus_px) &&
  method.annulus_px.length === 2 &&
  method.annulus_px.every((r) => typeof r === "number" && Number.isFinite(r));

/** `time_span` of 7.1: null when no exposure was measured (a saturated answer has none). */
const isTimeSpan = (span: unknown) =>
  span === null || (isObject(span) && numbers(span, "mjd_min", "mjd_max"));

const isNeighbour = (n: Record<string, unknown>) =>
  typeof n.catalog === "string" &&
  typeof n.id === "string" &&
  numbers(n, "sep_arcsec") &&
  typeof n.fitted === "boolean";

const isPoint = (p: Record<string, unknown>) =>
  numbers(p, "lam", "dlam", "mjd", "det", "time_bin", "flux_ujy", "err_ujy", "flags") &&
  oneOf(p.quality, POINT_QUALITIES);

const isBinned = (p: Record<string, unknown>) =>
  numbers(p, "time_bin", "lam", "lam_min", "lam_max", "flux_ujy", "err_ujy", "n");

/** A 200 answer of the spectrum route as the contract shapes it; throws `FieldError` else. */
function checkSpectrum(body: Record<string, unknown>): SpectrumResponse {
  const { target } = body;
  if (
    body.status !== "ok" ||
    !oneOf(body.state, SPECTRUM_STATES) ||
    !isObject(target) ||
    !numbers(target, "ra", "dec") ||
    !listOf(body.neighbours, isNeighbour) ||
    !isMethod(body.method) ||
    !isTimeSpan(body.time_span) ||
    !listOf(body.points, isPoint) ||
    !listOf(body.binned, isBinned)
  ) {
    throw new FieldError("bad_response", "The spectrum answer does not follow the contract.");
  }
  return body as unknown as SpectrumResponse;
}

/** `GET /api/fields/{key}/spectrum?ra=&dec=`: quick-look spectrophotometry (section 7.1). */
export async function loadSpectrum(
  key: string,
  ra: number,
  dec: number,
  options: ExtraOptions = {},
): Promise<SpectrumAnswer> {
  checkKey(key);
  if (!onTheSky(ra, dec)) {
    throw new FieldError("bad_request", "That position is outside the sky.");
  }
  const context = extraContext(options);
  const url = engineUrl(spectrumUrl(key, ra, dec), context.engine);
  const said: { incomplete: string | null } = { incomplete: null };
  const body = await pollJson(url, context, SPECTRUM_DEADLINE_MS, options.onProgress, (answer) => {
    said.incomplete = answer.headers.get(INCOMPLETE_HEADER);
  });
  const spectrum = checkSpectrum(body);
  return said.incomplete ? { ...spectrum, incomplete: said.incomplete } : spectrum;
}

// ---------------------------------------------------------------------------------------------
// Recorded answers: what the engine answered for a recorded field, shipped beside it
// ---------------------------------------------------------------------------------------------

/** The routes a recorded field may carry a recorded answer of: what each was asked and answered. */
export interface RecordedRoutes {
  overlays: { request: Record<string, never>; response: OverlaysResponse };
  spectrum: { request: { ra: number; dec: number }; response: SpectrumResponse };
}

export type RecordedRoute = keyof RecordedRoutes;

/**
 * A real answer of the engine, recorded beside a recorded field as
 * `cache/fixtures/<name>/overlays.json` or `spectrum.json` (docs/CONTRACT_FIELDS.md section 8,
 * "Recorded answers"). Both files are optional. The web app's own type, kept out of contract.ts
 * until the contract's owner takes the envelope into it.
 */
export interface RecordedAnswer<Route extends RecordedRoute = RecordedRoute> {
  contract: string;
  kind: "recorded_answer";
  route: Route;
  /** The recorded field's name, e.g. "wise0855". */
  field: string;
  /** The field's key: equal to its manifest's `key`. */
  key: string;
  /** The manifest's `provenance.pipeline_version`. */
  pipeline_version: string;
  /** When the answer was recorded: UTC, "YYYY-MM-DDTHH:MM:SSZ". */
  recorded_at: string;
  /** {} for overlays; for the spectrum, the manifest's request position. */
  request: RecordedRoutes[Route]["request"];
  /** The exact JSON body the route answered. */
  response: RecordedRoutes[Route]["response"];
}

/** `recorded_at` is a real UTC time in one form: "2026-11-14T23:47:33Z". */
function isRecordedAt(text: unknown): text is string {
  if (typeof text !== "string") return false;
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(text)) return false;
  // Only a time that reads back as written is real (not 31 February, not 24:00:00).
  const time = new Date(text);
  return !Number.isNaN(time.getTime()) && time.toISOString() === text.replace("Z", ".000Z");
}

/** True when a recorded response passes the checks the live loader applies to the route's answer. */
function isRouteAnswer(route: RecordedRoute, response: unknown): boolean {
  // The live loaders take only bodies that carry the contract's key (contractBody).
  if (!isObject(response) || typeof response.contract !== "string") return false;
  try {
    if (route === "overlays") checkOverlays(response);
    else checkSpectrum(response);
    return true;
  } catch {
    return false;
  }
}

/**
 * The envelope when it is the recorded answer of `route` for the field `name` whose manifest key is
 * `key` (rule R1), else null.
 */
function recordedEnvelope<R extends RecordedRoute>(
  body: Record<string, unknown>,
  route: R,
  name: string,
  key: string,
): RecordedAnswer<R> | null {
  const { contract, kind, request } = body;
  if (typeof contract !== "string" || !contract.startsWith("1.")) return null;
  if (kind !== "recorded_answer" || body.route !== route) return null;
  if (body.field !== name || body.key !== key) return null;
  if (typeof body.pipeline_version !== "string" || !isRecordedAt(body.recorded_at)) return null;
  if (!isObject(request)) return null;
  if (route === "spectrum") {
    // A recorded spectrum was measured at one position, and applies only there (rule R3).
    const { ra, dec } = request;
    if (typeof ra !== "number" || typeof dec !== "number" || !onTheSky(ra, dec)) return null;
  }
  if (!isRouteAnswer(route, body.response)) return null;
  return body as unknown as RecordedAnswer<R>;
}

/**
 * The recorded answer of `route` shipped with the recorded field `name`, a same-origin static file
 * (BASE_URL + "fixtures/<name>/<route>.json", copied there by scripts/sync-contract.mjs), when it
 * belongs to the field whose manifest key is `key`: contract 1.x, kind "recorded_answer", this
 * route, field and key, a real `recorded_at`, and a response that passes the live loader's checks.
 *
 * Null when there is none: a missing file (404 or another 4xx), a page that is not JSON, any
 * envelope that fails these checks (the page then behaves as it would without the file).
 *
 * It rejects with a `FieldError("unreachable")` when the file could not be read this time: the
 * site did not answer (three attempts) or answered 429 or 5xx. That is not an answer about the
 * file, so the caller may ask again later. It rejects with the abort reason when aborted.
 */
async function loadRecorded<R extends RecordedRoute>(
  route: R,
  name: string,
  key: string,
  options: Pick<LoadOptions, "signal" | "fetchImpl" | "sleep"> = {},
): Promise<RecordedAnswer<R> | null> {
  if (!/^[a-z0-9][a-z0-9_-]*$/.test(name) || !/^[A-Za-z0-9_-]{1,64}$/.test(key)) return null;
  const context = contextOf(options);
  const url = `${import.meta.env.BASE_URL}fixtures/${name}/${route}.json`;
  const unread = () => new FieldError("unreachable", "The recorded answer could not be read now.");
  let response: Response;
  try {
    response = await fetchWithRetry(url, "application/json", context);
  } catch (error) {
    if (isAbort(error) || context.signal?.aborted) throw error;
    throw unread();
  }
  if (response.status === 429 || response.status >= 500) throw unread();
  if (!response.ok) return null;
  const body = await contractBody(response);
  return body === null ? null : recordedEnvelope(body, route, name, key);
}

/** The recorded overlays answer of a recorded field (contract 7.3), or null; see loadRecorded. */
export function loadRecordedOverlays(
  name: string,
  key: string,
  options: Pick<LoadOptions, "signal" | "fetchImpl" | "sleep"> = {},
): Promise<RecordedAnswer<"overlays"> | null> {
  return loadRecorded("overlays", name, key, options);
}

/** The recorded spectrum answer of a recorded field (contract 7.1), or null; see loadRecorded. */
export function loadRecordedSpectrum(
  name: string,
  key: string,
  options: Pick<LoadOptions, "signal" | "fetchImpl" | "sleep"> = {},
): Promise<RecordedAnswer<"spectrum"> | null> {
  return loadRecorded("spectrum", name, key, options);
}

/**
 * `GET /api/status` (contract section 7.4): one attempt, no retries. Resolves to null when no
 * engine answers or the answer is not the contract's, so callers can say what is unavailable.
 * Rejects only with the abort reason.
 */
export async function loadStatus(
  options: Pick<LoadOptions, "signal" | "fetchImpl" | "engine"> = {},
): Promise<StatusResponse | null> {
  const fetchImpl = options.fetchImpl ?? ((input, init) => fetch(input, init));
  try {
    const response = await fetchImpl(engineUrl(STATUS_URL, options.engine ?? ENGINE_URL), {
      headers: { Accept: "application/json" },
      signal: options.signal,
    });
    if (!response.ok || response.headers.has(PROXY_ERROR_HEADER)) return null;
    const body = await contractBody(response);
    if (body === null || body.status !== "ok") return null;
    return body as unknown as StatusResponse;
  } catch (error) {
    if (isAbort(error) || options.signal?.aborted) throw error;
    return null;
  }
}
