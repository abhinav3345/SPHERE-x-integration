/**
 * The four parts behind vm.extras (types.ts): three-colour, catalogue markers, Then and now and
 * the spectrum, derived from the state, the field on screen and what the engine answered. Pure
 * functions; useComparator does the loading and adds the handlers.
 *
 * A recorded field may carry recorded answers of the overlays and spectrum routes (api.ts
 * loadRecorded*). They stand in for a live answer only where none can be had, and are labelled as
 * recorded wherever they are shown: the rules R1 to R5 are in the section "Recorded answers".
 *
 * Positions go through player/grid.ts, the one projection of the browser. Brightness scales are
 * pooled with player/render.ts. A value the data does not give is left out, never invented.
 */
import type {
  FieldErrorCode,
  MeasureProgress,
  RecordedAnswer,
  RecordedRoute,
  SpectrumAnswer,
} from "../../api";
import type {
  CatwiseSource,
  GaiaSource,
  Manifest,
  OverlaysResponse,
  SpectrumResponse,
  TrackPoint,
  UpstreamState,
} from "../../contract";
import { pixelToSky, type SkyGrid, skyToPixel } from "../../player/grid";
import { legacyPair } from "../../player/presets";
import { type Limits, pooledLimits } from "../../player/render";
import type { FieldSynth, LegacyPlane } from "../../player/synth";
import type { Features } from "../features";
import { ARCSEC, countFixed, EN_DASH, rangeFixed, shortDate } from "../format";
import {
  BANDS,
  type BandId,
  type Offset,
  type RecordedId,
  rgbChannelsOf,
  type SeqFrame,
  separationArcsec,
  type ViewState,
} from "../model";
import { EMPTY_EXTRAS } from "./empty";
import { measuringSentence, spectrumModel, spectrumVM } from "./spectrum";
import type {
  ExtrasVM,
  MarkersVM,
  MarkerVM,
  SpectrumVM,
  ThenAndNowVM,
  ThreeColourVM,
} from "./types";

// ---------------------------------------------------------------------------------------------
// What the hook has loaded (passed in Env)
// ---------------------------------------------------------------------------------------------

/** The catalogue overlays of the field on screen, as far as they have loaded. */
export type OverlaysLoad =
  | { phase: "idle" }
  | { phase: "loading"; key: string }
  | { phase: "ready"; key: string; data: OverlaysResponse }
  | { phase: "failed"; key: string; code: FieldErrorCode | "unexpected" };

/** Where a spectrum is measured: the field and the ring's sky position. */
export interface SpectrumAt {
  key: string;
  ra: number;
  dec: number;
}

/** The spectrum at the ring, as far as it has loaded. */
export type SpectrumLoad =
  | { phase: "idle" }
  | { phase: "loading"; at: SpectrumAt; progress: MeasureProgress | null }
  | { phase: "ready"; at: SpectrumAt; data: SpectrumAnswer }
  | { phase: "failed"; at: SpectrumAt; code: FieldErrorCode | "unexpected" };

/** Decimals of a spectrum position: 1e-6 degree is 0.0036″, far below a pixel. */
const SPECTRUM_DIGITS = 6;
const roundTo = (value: number, digits: number) => Number(value.toFixed(digits));

/** The sky position of the ring on a field: where its spectrum is measured. */
export function spectrumAt(manifest: Manifest, grid: SkyGrid, ring: Offset): SpectrumAt {
  const sky = pixelToSky(grid, manifest.grid.cx + ring.dx, manifest.grid.cy + ring.dy);
  return {
    key: manifest.key,
    ra: roundTo(sky.ra, SPECTRUM_DIGITS),
    dec: roundTo(sky.dec, SPECTRUM_DIGITS),
  };
}

export const sameAt = (a: SpectrumAt, b: SpectrumAt) =>
  a.key === b.key && a.ra === b.ra && a.dec === b.dec;

// ---------------------------------------------------------------------------------------------
// Recorded answers (cache/fixtures/<name>/overlays.json and spectrum.json)
//
// R1  A recorded answer belongs to one recorded field: it is used only for the field of that
//     name whose manifest key is the answer's key (api.ts checks the rest of the envelope, and
//     the response as it checks a live one). A recorded spectrum is used only when its request
//     is the manifest's request position, as the format says it is.
// R2  Live answers win. A recorded answer is used only when no live one can be had: the field is
//     the bundled copy (no engine answered), the engine's request failed (network error, timeout,
//     404, 429, 5xx), or, for the overlays only, the live answer marks a catalogue unavailable.
//     And only for a recorded field opened for itself (answersField): one shown INSTEAD of the
//     place asked for uses none, so its answers are never read as the answers of that place.
// R3  The recorded spectrum is used only while the ring is on the pixel of the position it was
//     recorded for (a recorded field's default ring). Anywhere else the panel says what it says
//     when no spectrum can be measured.
// R4  Whatever is shown from a recorded answer is labelled as recorded, with its date: the
//     spectrum panel's chip, and one caveat sentence while recorded markers are drawn.
// R5  A missing file or an envelope that fails R1 changes nothing: the page behaves as without.
// ---------------------------------------------------------------------------------------------

/**
 * The recorded field whose recorded answers the page may use: the field on screen when it is a
 * recorded field opened for itself, else null. A recorded field shown INSTEAD of the place asked
 * for ("The archive is not responding. Showing the recorded field instead.") uses none, as before
 * recorded answers existed: under "Spectrum at your position" a recorded spectrum would read as
 * the spectrum of the place asked for, and with a mover banner too the rail at 1280 × 720 and
 * 1440 × 900 is past both of its floors (time.css), so the caveat that labels recorded markers
 * (R4) could fall below its edge.
 */
export function answersField(state: ViewState): RecordedId | null {
  if (state.load.phase !== "ready" || state.load.fallback) return null;
  return state.load.field.recorded;
}

/** A recorded answer of one route, as far as the hook has loaded it for a field. */
export type RecordedLoad<R extends RecordedRoute> =
  | { phase: "idle" }
  | { phase: "loading"; field: string; key: string }
  /** `answer` null: no usable recorded answer (no file, or one that fails R1). */
  | { phase: "done"; field: string; key: string; answer: RecordedAnswer<R> | null };

export interface RecordedLoads {
  overlays: RecordedLoad<"overlays">;
  spectrum: RecordedLoad<"spectrum">;
}

/**
 * R2: the engine's failures after which a recorded answer may stand in. It could not be reached
 * (network error), did not answer in time, has no such route or field (404), is busy (429), or
 * failed (5xx: "upstream_unavailable" for a 503, "internal" for the others). A request it refused
 * (400) or an answer that does not follow the contract is not among them.
 */
const RECORDED_STANDS_IN: ReadonlySet<FieldErrorCode | "unexpected"> = new Set([
  "unreachable",
  "timeout",
  "not_found",
  "busy",
  "upstream_unavailable",
  "internal",
]);

type Source = "api" | "bundled" | null;

/** R2 for the catalogue overlays of the field with this key: no live answer can be had. */
export function overlaysNeedRecorded(source: Source, overlays: OverlaysLoad, key: string): boolean {
  if (source === "bundled") return true;
  if (overlays.phase === "failed" && overlays.key === key) {
    return RECORDED_STANDS_IN.has(overlays.code);
  }
  if (overlays.phase === "ready" && overlays.key === key) {
    return catalogues(overlays.data.upstreams).length < 2;
  }
  return false;
}

/** R2 for the spectrum at `at`: no live answer can be had. */
export function spectrumNeedsRecorded(source: Source, spectrum: SpectrumLoad, at: SpectrumAt) {
  if (source === "bundled") return true;
  return (
    spectrum.phase === "failed" && sameAt(spectrum.at, at) && RECORDED_STANDS_IN.has(spectrum.code)
  );
}

/** The catalogues an overlays answer holds: those its upstreams do not mark unavailable. */
function catalogues(upstreams: { gaia: UpstreamState; catwise: UpstreamState }) {
  return (["gaia", "catwise"] as const).filter((name) => upstreams[name] !== "unavailable");
}

/**
 * R2 again: a recorded overlays answer stands in only when it marks every catalogue the live
 * answer marks, and more. It never trades a live catalogue for a recorded one.
 */
function recordedOverlaysHelp(recorded: OverlaysResponse, live: OverlaysLoad, key: string) {
  const had = live.phase === "ready" && live.key === key ? catalogues(live.data.upstreams) : [];
  const has = catalogues(recorded.upstreams);
  return has.length > had.length && had.every((name) => has.includes(name));
}

/** R3: the ring is on the image pixel of a sky position. */
export function ringOn(
  grid: SkyGrid,
  manifest: Manifest,
  ring: Offset,
  position: { ra: number; dec: number },
): boolean {
  const { x, y } = skyToPixel(grid, position.ra, position.dec);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return false;
  return (
    Math.round(x - manifest.grid.cx) === ring.dx && Math.round(y - manifest.grid.cy) === ring.dy
  );
}

/** R1: the answer of a load when it is the recorded answer of the field `name` with `key`. */
export function recordedOf<R extends RecordedRoute>(
  load: RecordedLoad<R> | undefined,
  name: string | null,
  key: string,
): RecordedAnswer<R> | null {
  if (name === null || load?.phase !== "done" || load.field !== name || load.key !== key) {
    return null;
  }
  const answer = load.answer;
  return answer !== null && answer.field === name && answer.key === key ? answer : null;
}

/** True while the recorded answer of the field `name` with `key` is on its way. */
const recordedLoading = (
  load: RecordedLoad<RecordedRoute> | undefined,
  name: string,
  key: string,
) => load?.phase === "loading" && load.field === name && load.key === key;

/**
 * The UTC date of `recorded_at` ("2026-11-14T23:47:33Z") as the page writes one date, in a fact
 * chip and elsewhere (format.ts shortDate): "14 Nov 2026".
 */
export function recordedDate(recordedAt: string): string {
  return shortDate(recordedAt.slice(0, 10));
}

/** R4: the caveat while recorded markers are drawn, in place of "Catalogue markers are off…". */
export function recordedMarkersSentence(recordedAt: string): string {
  return `Catalogue markers were recorded on ${recordedDate(recordedAt)}.`;
}

/** R4: the spectrum panel's chip while it shows a recorded answer. */
export function recordedSpectrumChip(recordedAt: string): string {
  return `Recorded ${recordedDate(recordedAt)}`;
}

/** The field on screen as the recorded answers need it. */
export interface RecordedField {
  manifest: Manifest;
  grid: SkyGrid;
  /** The recorded field this is, or null: only a recorded field has recorded answers. */
  recorded: RecordedId | null;
  source: "api" | "bundled";
}

/**
 * The recorded answers the rules may call for now: the hook loads these, and only these, so a page
 * whose engine answers never asks for a recorded file. The spectrum's is called for only with the
 * ring on the pixel of the manifest's request position (R3: where a recorded spectrum is recorded).
 */
export function recordedNeeded(
  state: ViewState,
  features: Readonly<Features>,
  field: RecordedField | null,
  overlays: OverlaysLoad,
  spectrum: SpectrumLoad,
): { overlays: boolean; spectrum: boolean } {
  if (!field || field.recorded === null) return { overlays: false, spectrum: false };
  const { manifest, grid, source } = field;
  const markers =
    features.catalogueMarkers &&
    state.markers &&
    overlaysNeedRecorded(source, overlays, manifest.key);
  const open = features.spectrum && state.spectrum;
  const at = open ? spectrumAt(manifest, grid, state.ring) : null;
  const measured =
    at !== null &&
    spectrumNeedsRecorded(source, spectrum, at) &&
    ringOn(grid, manifest, state.ring, manifest.request);
  return { overlays: markers, spectrum: measured };
}

// ---------------------------------------------------------------------------------------------
// Three-colour
// ---------------------------------------------------------------------------------------------

/**
 * The legend's channel ranges, the design's own strings (Handoff-copy, section 8). extras.test.ts
 * checks them against the detectors of presets.json.
 */
export const RGB_RANGES = { r: "3.8 to 5.0 µm", g: "1.6 to 3.8 µm", b: "0.74 to 1.65 µm" } as const;

const threeColourCache = new WeakMap<FieldSynth, NonNullable<ThreeColourVM["frames"]>>();

/**
 * The three channel frames of every visit (oldest first, as vm.field.sequence), each channel on
 * one scale pooled over the whole sequence. The limits are the pooled ones, before the Contrast
 * step: blocks apply model.ts displayLimits(limits, vm.state.contrast) to each, as for one band.
 */
export function threeColourFrames(synth: FieldSynth): NonNullable<ThreeColourVM["frames"]> {
  const cached = threeColourCache.get(synth);
  if (cached) return cached;
  const channels = rgbChannelsOf(synth);
  const limitsOf = (pick: "r" | "g" | "b"): Limits | null =>
    pooledLimits(channels.map((c) => c[pick]).filter((frame) => frame.waveBins.length > 0));
  const limits = { r: limitsOf("r"), g: limitsOf("g"), b: limitsOf("b") };
  const frames = channels.map((c) => ({
    r: { data: c.r.data, limits: c.r.waveBins.length > 0 ? limits.r : null },
    g: { data: c.g.data, limits: c.g.waveBins.length > 0 ? limits.g : null },
    b: { data: c.b.data, limits: c.b.waveBins.length > 0 ? limits.b : null },
  }));
  threeColourCache.set(synth, frames);
  return frames;
}

// ---------------------------------------------------------------------------------------------
// Then and now
// ---------------------------------------------------------------------------------------------

export const NO_OLDER_IMAGE = "No older survey image is stored for this field yet.";

/** How a legacy mission is named on screen: AllWISE images are WISE's ("WISE W2, 2010"). */
const SURVEY_NAMES: Readonly<Record<string, string>> = { AllWISE: "WISE", "2MASS": "2MASS" };

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "May to Nov 2010", "Jan 2010 to Feb 2011", "May 2010": the real span of the observations. */
export function monthSpan(startIso: string, endIso: string): string {
  const [ay, am] = startIso.split("-").map(Number);
  const [by, bm] = endIso.split("-").map(Number);
  if (!ay || !am || !by || !bm) return "";
  const a = MONTHS[am - 1];
  const b = MONTHS[bm - 1];
  if (ay !== by) return `${a} ${ay} to ${b} ${by}`;
  if (am !== bm) return `${a} to ${b} ${by}`;
  return `${b} ${by}`;
}

/** "WISE W2", "2MASS Ks". */
export function surveyName(plane: LegacyPlane): string {
  return `${SURVEY_NAMES[plane.mission] ?? plane.mission} ${plane.band}`;
}

/** "WISE W2, 2010", or "WISE W2, 2010–2011" when the images span two years. */
export function surveyTitle(plane: LegacyPlane): string {
  const a = plane.date_start.slice(0, 4);
  const b = plane.date_end.slice(0, 4);
  return `${surveyName(plane)}, ${a === b ? a : `${a}${EN_DASH}${b}`}`;
}

/** The legacy plane shown with a band: the one paired with it, else the first the field has. */
export function olderFor(
  synth: FieldSynth,
  band: BandId,
): { plane: LegacyPlane; preset: BandId; matches: boolean } | null {
  const planes = synth.legacyPlanes().filter((plane) => legacyPair(plane.band) !== null);
  const pairOf = (plane: LegacyPlane) => legacyPair(plane.band)?.spherex_preset as BandId;
  const match = planes.find((plane) => pairOf(plane) === band);
  const plane = match ?? planes[0];
  return plane ? { plane, preset: pairOf(plane), matches: match !== undefined } : null;
}

/** The note when the band on screen has no older image of its own: which pairing is shown. */
export function otherBandNote(band: BandId, survey: string, preset: BandId): string {
  return `No older survey image matches ${BANDS[band].spoken}. Then and now pairs ${survey} with ${BANDS[preset].spoken}.`;
}

const thenCache = new WeakMap<FieldSynth, Map<BandId, ThenAndNowVM>>();

/**
 * Then and now for the band on screen: the older survey's image (its own scale; never mixed into
 * a SPHEREx frame) beside one SPHEREx stack of the paired band over every visit (its own scale).
 */
export function thenAndNowOf(synth: FieldSynth, band: BandId): ThenAndNowVM {
  let byBand = thenCache.get(synth);
  if (!byBand) {
    byBand = new Map();
    thenCache.set(synth, byBand);
  }
  const cached = byBand.get(band);
  if (cached) return cached;
  let result: ThenAndNowVM;
  const older = olderFor(synth, band);
  if (!older) {
    result = { status: "none", note: NO_OLDER_IMAGE, older: null, sphx: null };
  } else {
    const { plane, preset, matches } = older;
    const data = synth.planeData(plane);
    const title = surveyTitle(plane);
    const stack = synth.stackFor(preset);
    const hasStack =
      stack.timeBins.length > 0 && stack.dateStart !== null && stack.dateEnd !== null;
    const notes: string[] = [];
    if (!matches) notes.push(otherBandNote(band, surveyName(plane), preset));
    if (!hasStack) notes.push(`No SPHEREx image in ${BANDS[preset].spoken} covers this field yet.`);
    result = {
      status: "ready",
      note: notes.length > 0 ? notes.join(" ") : null,
      older: {
        data,
        limits: pooledLimits([{ data, sigma: plane.sigma }]),
        title,
        dates: monthSpan(plane.date_start, plane.date_end),
      },
      sphx: hasStack
        ? {
            data: stack.data,
            limits: pooledLimits([stack]),
            title: `SPHEREx ${rangeFixed(stack.lamMin, stack.lamMax)}`,
            exposures: countFixed(stack.nExposures).trim(),
            dates: monthSpan(stack.dateStart ?? "", stack.dateEnd ?? ""),
          }
        : null,
    };
  }
  byBand.set(band, result);
  return result;
}

// ---------------------------------------------------------------------------------------------
// Catalogue markers
// ---------------------------------------------------------------------------------------------

export const MARKERS_NO_ENGINE = "Catalogue markers are off while the archive is not responding.";

/** The reader's sentence for a failed overlays load. */
export function markersFailure(code: FieldErrorCode | "unexpected"): string {
  switch (code) {
    case "unreachable":
      return MARKERS_NO_ENGINE;
    case "not_found":
      return "Catalogue markers are not available for this field yet.";
    case "timeout":
      return "The star catalogues did not answer in time.";
    case "upstream_unavailable":
      return "The Gaia and CatWISE catalogues could not be reached.";
    default:
      return "The catalogue markers could not be loaded.";
  }
}

/** A marker moves "enough to show" when its track spans at least one image pixel. */
const FAST_SPAN_PX = 1;
/**
 * Both catalogues are drawn as "neighbours" of the ring: the sources within this distance of it,
 * and every source the engine tracks as moving across the frames. All of them at once (hundreds
 * of Gaia stars in a 6′ field, 829 around Barnard's Star) would bury the sky that is meant to
 * blink, and at 30″ about nine CatWISE diamonds still covered the object in the ring (Epsilon
 * Indi B). 15″ is the distance within which the engine calls a source a neighbour that may
 * contaminate the spectrum (contract 7.1), about one and a half times the 10″ resolution. Our
 * choice; no board shows catalogue marks.
 */
export const NEIGHBOUR_ARCSEC = 15;

/** Neighbours of the ring: moving sources, and those within NEIGHBOUR_ARCSEC of it. */
export function neighboursOf(
  markers: readonly MarkerVM[],
  ring: { x: number; y: number },
  pixscaleArcsec: number,
): MarkerVM[] {
  const radius = NEIGHBOUR_ARCSEC / pixscaleArcsec;
  return markers.filter(
    (marker) =>
      marker.fast ||
      marker.xy.some((p) => p !== null && Math.hypot(p.x - ring.x, p.y - ring.y) <= radius),
  );
}

/** MJD of J2000.0 (2000 January 1, 12:00). */
const MJD_J2000 = 51544.5;
const DAYS_PER_JULIAN_YEAR = 365.25;

/** The Julian year of a modified Julian date. */
export const julianYear = (mjd: number) => 2000 + (mjd - MJD_J2000) / DAYS_PER_JULIAN_YEAR;

/**
 * True when a source without a track would be drawn where it no longer is: its catalogue proper
 * motion carries it at least one image pixel between the catalogue's epoch and the frame's. The
 * engine sends a track for every source it propagates (contract 7.3: "computed by the server so
 * there is a single implementation of propagation"); a moving source it did not track is left
 * out, never drawn at an old position. Without a proper motion there is nothing to say: drawn.
 */
export function staleWithoutTrack(
  pm: { pmra: number | null; pmdec: number | null },
  epoch: number,
  year: number,
  pixscaleArcsec: number,
): boolean {
  if (pm.pmra === null || pm.pmdec === null) return false;
  const moved = (Math.hypot(pm.pmra, pm.pmdec) / 1000) * Math.abs(year - epoch);
  return Number.isFinite(moved) && moved >= pixscaleArcsec;
}
/** Farther than this from the centre a position is not projected at all. */
const MAX_SEPARATION_ARCSEC = 7200;

/** Plane pixel of a sky position when it falls on the image, else null. */
export function onImage(
  grid: SkyGrid,
  manifest: Manifest,
  ra: number,
  dec: number,
): { x: number; y: number } | null {
  if (!Number.isFinite(ra) || !Number.isFinite(dec)) return null;
  if (separationArcsec(ra, dec, grid.ra0, grid.dec0) > MAX_SEPARATION_ARCSEC) return null;
  const { x, y } = skyToPixel(grid, ra, dec);
  const { nx, ny } = manifest.grid;
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  if (x < -0.5 || y < -0.5 || x > nx - 0.5 || y > ny - 0.5) return null;
  return { x, y };
}

function markerOf(
  id: string,
  ra: number,
  dec: number,
  epoch: number,
  pm: { pmra: number | null; pmdec: number | null },
  track: readonly TrackPoint[] | undefined,
  sequence: readonly SeqFrame[],
  place: (ra: number, dec: number) => { x: number; y: number } | null,
  pixscaleArcsec: number,
): MarkerVM | null {
  const byBin = track ? new Map(track.map((point) => [point.time_bin, point])) : null;
  const xy = sequence.map((frame) => {
    if (!byBin) {
      // No track: drawn at the catalogue position only while that is still where it is.
      const year = julianYear(frame.timeBin.mjd_mid);
      return staleWithoutTrack(pm, epoch, year, pixscaleArcsec) ? null : place(ra, dec);
    }
    // A moving source is drawn only where the engine propagated it: never at an old position.
    const point = byBin.get(frame.timeBin.id);
    return point ? place(point.ra, point.dec) : null;
  });
  const shown = xy.filter((p): p is { x: number; y: number } => p !== null);
  if (shown.length === 0) return null;
  const xs = shown.map((p) => p.x);
  const ys = shown.map((p) => p.y);
  const span = Math.hypot(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
  const fast = byBin !== null && span >= FAST_SPAN_PX;
  const total =
    pm.pmra !== null && pm.pmdec !== null ? Math.hypot(pm.pmra, pm.pmdec) / 1000 : Number.NaN;
  const label = fast && Number.isFinite(total) ? `${total.toFixed(1)}${ARCSEC}/yr` : null;
  return { id, label, xy, fast };
}

const markerCache = new WeakMap<
  OverlaysResponse,
  WeakMap<readonly SeqFrame[], { gaia: MarkerVM[]; catwise: MarkerVM[] }>
>();

/** The catalogue sources on the image, one position per frame of the sequence. */
export function catalogueMarkers(
  data: OverlaysResponse,
  sequence: readonly SeqFrame[],
  grid: SkyGrid,
  manifest: Manifest,
): { gaia: MarkerVM[]; catwise: MarkerVM[] } {
  let bySequence = markerCache.get(data);
  if (!bySequence) {
    bySequence = new WeakMap();
    markerCache.set(data, bySequence);
  }
  const cached = bySequence.get(sequence);
  if (cached) return cached;
  const place = (ra: number, dec: number) => onImage(grid, manifest, ra, dec);
  const pixscale = manifest.grid.pixscale_arcsec;
  const gaia = data.gaia
    .map((s: GaiaSource) =>
      markerOf(s.source_id, s.ra, s.dec, s.epoch, s, s.track, sequence, place, pixscale),
    )
    .filter((m): m is MarkerVM => m !== null);
  const catwise = data.catwise
    .map((s: CatwiseSource) =>
      markerOf(s.id, s.ra, s.dec, s.epoch, s, s.track, sequence, place, pixscale),
    )
    .filter((m): m is MarkerVM => m !== null);
  const result = { gaia, catwise };
  bySequence.set(sequence, result);
  return result;
}

/**
 * The markers of an overlays answer: the ring's neighbours in each catalogue it holds. `recorded`
 * is the caveat of a recorded answer (R4), null for a live one.
 */
function markersFrom(
  data: OverlaysResponse,
  state: ViewState,
  sequence: readonly SeqFrame[],
  grid: SkyGrid,
  manifest: Manifest,
  was: MarkersVM["was"],
  recorded: string | null,
): MarkersVM {
  const { gaia: gaiaUp, catwise: catwiseUp } = data.upstreams;
  if (gaiaUp === "unavailable" && catwiseUp === "unavailable") {
    return {
      status: "unavailable",
      note: markersFailure("upstream_unavailable"),
      gaia: [],
      catwise: [],
      was,
    };
  }
  const lists = catalogueMarkers(data, sequence, grid, manifest);
  let note: string | null = null;
  if (gaiaUp === "unavailable")
    note = "Gaia DR3 could not be reached: only CatWISE sources are marked.";
  else if (catwiseUp === "unavailable") {
    note = "CatWISE could not be reached: only Gaia DR3 stars are marked.";
  }
  const ring = { x: manifest.grid.cx + state.ring.dx, y: manifest.grid.cy + state.ring.dy };
  const pixscale = manifest.grid.pixscale_arcsec;
  return {
    status: "ready",
    note,
    ...(recorded === null ? {} : { recorded }),
    gaia: gaiaUp === "unavailable" ? [] : neighboursOf(lists.gaia, ring, pixscale),
    catwise: catwiseUp === "unavailable" ? [] : neighboursOf(lists.catwise, ring, pixscale),
    was,
  };
}

function markersOf(
  input: ExtrasInput,
  sequence: readonly SeqFrame[],
  grid: SkyGrid,
  manifest: Manifest,
  name: RecordedId | null,
): MarkersVM {
  const { state, was, overlays, source } = input;
  if (!state.markers) return { status: "off", note: null, gaia: [], catwise: [], was: null };
  const wasXY = was ? onImage(grid, manifest, was.ra, was.dec) : null;
  const wasVM = wasXY ? { ...wasXY, year: was?.year ?? Number.NaN } : null;
  const none = { gaia: [], catwise: [], was: wasVM };
  // R2: the recorded answer stands in only where no live one can be had; R1: only its own field's.
  if (name !== null && overlaysNeedRecorded(source, overlays, manifest.key)) {
    const load = input.recorded?.overlays;
    if (recordedLoading(load, name, manifest.key)) {
      return { status: "loading", note: null, ...none };
    }
    const answer = recordedOf(load, name, manifest.key);
    // A bundled copy means no engine answered: a live answer the hook still holds for this key
    // (from before the engine went away) is not one that can be had now.
    const live: OverlaysLoad = source === "bundled" ? { phase: "idle" } : overlays;
    if (answer && recordedOverlaysHelp(answer.response, live, manifest.key)) {
      const sentence = recordedMarkersSentence(answer.recorded_at);
      return markersFrom(answer.response, state, sequence, grid, manifest, wasVM, sentence);
    }
  }
  if (source === "bundled") return { status: "unavailable", note: MARKERS_NO_ENGINE, ...none };
  if (overlays.phase === "failed" && overlays.key === manifest.key) {
    return { status: "unavailable", note: markersFailure(overlays.code), ...none };
  }
  if (overlays.phase !== "ready" || overlays.key !== manifest.key) {
    return { status: "loading", note: null, ...none };
  }
  return markersFrom(overlays.data, state, sequence, grid, manifest, wasVM, null);
}

// ---------------------------------------------------------------------------------------------
// The spectrum
// ---------------------------------------------------------------------------------------------

export const SPECTRUM_NO_ENGINE =
  "The spectrum cannot be measured while the archive is not responding.";

/** The reader's sentence for a failed spectrum. */
export function spectrumFailure(code: FieldErrorCode | "unexpected"): string {
  switch (code) {
    case "unreachable":
      return SPECTRUM_NO_ENGINE;
    case "not_found":
      return "Spectra are not available for this field yet.";
    case "timeout":
      return "The spectrum did not finish in time.";
    case "upstream_unavailable":
      return "The archive cannot be reached, so the spectrum cannot be measured.";
    case "busy":
      return "Too many requests are being measured. Close and open the spectrum to try again.";
    default:
      return "The spectrum could not be measured.";
  }
}

const modelCache = new WeakMap<SpectrumResponse, ReturnType<typeof spectrumModel>>();

/** The panel's model of a loaded answer, memoised per answer. */
export function modelOf(data: SpectrumResponse, manifest: Manifest) {
  const cached = modelCache.get(data);
  if (cached) return cached;
  const model = spectrumModel(data, manifest);
  modelCache.set(data, model);
  return model;
}

/** What the spectrum panel has at the ring: an answer (live or recorded), a wait, or why not. */
export type SpectrumShown =
  | { kind: "answer"; data: SpectrumAnswer; recorded: RecordedAnswer<"spectrum"> | null }
  /** `measuring`: the engine is measuring (with its progress); else a recorded file is on its way. */
  | { kind: "waiting"; measuring: boolean; progress: MeasureProgress | null }
  | { kind: "none"; message: string };

export interface SpectrumInput {
  field: RecordedField;
  ring: Offset;
  spectrum: SpectrumLoad;
  recorded?: RecordedLoad<"spectrum">;
}

/**
 * The spectrum at the ring of the field on screen, as the panel shows it and the CSV holds it:
 * the engine's answer for this position; else, where R2 and R3 allow, the recorded one; else the
 * sentence for why there is none.
 */
export function spectrumShown(input: SpectrumInput): SpectrumShown {
  const { field, ring, spectrum } = input;
  const { manifest, grid, source } = field;
  const at = spectrumAt(manifest, grid, ring);
  const name = field.recorded;
  if (name !== null && spectrumNeedsRecorded(source, spectrum, at)) {
    const answer = recordedOf(input.recorded, name, manifest.key);
    // R1: recorded at the manifest's request position, as the format says; R3: and shown only on
    // that position's pixel.
    if (
      answer &&
      answer.request.ra === manifest.request.ra &&
      answer.request.dec === manifest.request.dec &&
      ringOn(grid, manifest, ring, answer.request)
    ) {
      return { kind: "answer", data: answer.response, recorded: answer };
    }
    if (
      recordedLoading(input.recorded, name, manifest.key) &&
      ringOn(grid, manifest, ring, manifest.request)
    ) {
      return { kind: "waiting", measuring: false, progress: null };
    }
  }
  if (source === "bundled") return { kind: "none", message: SPECTRUM_NO_ENGINE };
  if (spectrum.phase === "ready" && sameAt(spectrum.at, at)) {
    return { kind: "answer", data: spectrum.data, recorded: null };
  }
  if (spectrum.phase === "failed" && sameAt(spectrum.at, at)) {
    return { kind: "none", message: spectrumFailure(spectrum.code) };
  }
  const progress =
    spectrum.phase === "loading" && sameAt(spectrum.at, at) ? spectrum.progress : null;
  return { kind: "waiting", measuring: true, progress };
}

function spectrumOf(input: ExtrasInput, field: RecordedField): SpectrumVM {
  const mode = input.state.spectrumMode;
  const shown = spectrumShown({
    field,
    ring: input.state.ring,
    spectrum: input.spectrum,
    recorded: input.recorded?.spectrum,
  });
  if (shown.kind === "answer") {
    const recorded = shown.recorded ? recordedSpectrumChip(shown.recorded.recorded_at) : null;
    return { open: true, ...spectrumVM(modelOf(shown.data, field.manifest), mode), recorded };
  }
  const base: Pick<SpectrumVM, "open" | "visits" | "points" | "binned" | "mode" | "recorded"> = {
    open: true,
    visits: [],
    points: [],
    binned: [],
    mode,
    recorded: null,
  };
  if (shown.kind === "none") {
    return { ...base, status: "unavailable", messages: [shown.message] };
  }
  const { progress } = shown;
  return {
    ...base,
    status: "loading",
    // A recorded file on its way is not a measurement: nothing to say for that moment.
    messages: shown.measuring
      ? [measuringSentence(progress?.done ?? null, progress?.total ?? null)]
      : [],
  };
}

// ---------------------------------------------------------------------------------------------
// All four
// ---------------------------------------------------------------------------------------------

export interface ExtrasInput {
  state: ViewState;
  features: Readonly<Features>;
  /** The field on screen with frames, or null. */
  field: {
    manifest: Manifest;
    synth: FieldSynth;
    grid: SkyGrid;
    band: BandId;
    sequence: readonly SeqFrame[];
    /**
     * The recorded field whose recorded answers may be used (answersField), or null: a live build,
     * or a recorded field shown instead of the place asked for.
     */
    recorded?: RecordedId | null;
  } | null;
  /** Where the field came from: "bundled" means no engine answered. */
  source: "api" | "bundled" | null;
  /** The moved-object hint's position and year (vm.image.was), or null. */
  was: { ra: number; dec: number; year: number } | null;
  overlays: OverlaysLoad;
  spectrum: SpectrumLoad;
  /** The recorded answers of the field on screen, as far as they are loaded; absent: none. */
  recorded?: RecordedLoads;
}

/** vm.extras without its handlers (useComparator adds them). */
export function deriveExtras(input: ExtrasInput): Omit<ExtrasVM, "handlers"> {
  const { features, field, state } = input;
  const { handlers: _none, ...empty } = EMPTY_EXTRAS;
  if (!field) {
    return {
      ...empty,
      threeColour: {
        frames: null,
        ranges: features.threeColour ? RGB_RANGES : empty.threeColour.ranges,
      },
      spectrum: { ...empty.spectrum, mode: state.spectrumMode },
    };
  }
  const { synth, band, sequence, grid, manifest } = field;
  const name = field.recorded ?? null;
  const threeColour: ThreeColourVM = features.threeColour
    ? { frames: band === "rgb" ? threeColourFrames(synth) : null, ranges: RGB_RANGES }
    : empty.threeColour;
  const markers = features.catalogueMarkers
    ? markersOf(input, sequence, grid, manifest, name)
    : empty.markers;
  const thenAndNow = features.thenAndNow ? thenAndNowOf(synth, band) : empty.thenAndNow;
  const open = features.spectrum && state.spectrum;
  // A field with frames comes from somewhere; "api" stands for an unknown source (tests).
  const source = input.source ?? "api";
  const spectrum: SpectrumVM = open
    ? spectrumOf(input, { manifest, grid, recorded: name, source })
    : { ...empty.spectrum, mode: state.spectrumMode };
  return { threeColour, markers, thenAndNow, spectrum };
}
