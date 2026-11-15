/**
 * The comparator's view state, its actions, a pure reducer, and pure selectors over the loaded
 * field. No React and no DOM: everything here is tested on the recorded real fields.
 *
 * Words on screen come from docs/design/comparator/Handoff-copy.dc.html; the behaviour from
 * Main.dc.html (its logic class), Handoff-components (the pair, the ring bar) and
 * Handoff-behaviour. Values come from the manifest and the frames, never from the boards.
 */
import type { FieldErrorCode, FieldSource, LoadProgress } from "../api";
import {
  DEFAULT_FOV_ARCMIN,
  FIXTURE_NAMES,
  FOV_CHOICES_ARCMIN,
  type Manifest,
  NATIVE_PIXEL_ARCSEC,
  THIN_EXPOSURES,
  type TimeBin,
} from "../contract";
import { type Astrometry, EPOCH_NOW, propagate } from "../overlays/sky";
import type { MoverHint } from "../overlays/types";
import { gridOf, pixelToSky } from "../player/grid";
import { DEFAULT_FPS, MAX_FPS, stepIndex } from "../player/playback";
import { contractWaveBins } from "../player/presets";
import { type Limits, pooledLimits } from "../player/render";
import { type FieldSynth, type Frame, presetWaveBins, type RgbFrame } from "../player/synth";
import { FEATURES, type Features } from "./features";
import {
  ARCMIN,
  asSentence,
  brightness,
  countFixed,
  fixedDateRange,
  formatDec,
  formatRa,
  frameCounter,
  positionLine,
  rangeFixed,
  rangeSpoken,
  readAsSentence,
  rowCount,
  shortDate,
  shortDateRange,
  sigmas,
  speedLabel,
} from "./format";

// ---------------------------------------------------------------------------------------------
// Vocabulary
// ---------------------------------------------------------------------------------------------

/** The four views of Handoff-removable. "then" is Then and now. */
export type ViewId = "blink" | "side" | "difference" | "then";
export const VIEW_IDS: readonly ViewId[] = ["blink", "side", "difference", "then"];

/** The nine band options, ids as in docs/contract/presets.json. */
export type BandId = "d1" | "d2" | "d3" | "d4" | "d5" | "d6" | "all" | "cold" | "rgb";
export const BAND_IDS: readonly BandId[] = [
  "d1",
  "d2",
  "d3",
  "d4",
  "d5",
  "d6",
  "all",
  "cold",
  "rgb",
];

/** Field of view, arcmin (contract section 2). */
export type Fov = (typeof FOV_CHOICES_ARCMIN)[number];
export const FOVS: readonly Fov[] = FOV_CHOICES_ARCMIN;
export const DEFAULT_FOV: Fov = DEFAULT_FOV_ARCMIN as Fov;
/** The recorded fields exist at this field of view only. */
export const RECORDED_FOV: Fov = 6;

/** A recorded real field (contract section 8). */
export type RecordedId = (typeof FIXTURE_NAMES)[number];
/** The five targets of the brief. */
export type TargetId = RecordedId | "epsindi" | "rwaur" | "rdra";

/** Offset of a pixel from the field's centre pixel, in image pixels: dx grows west (right on screen), dy grows south (down). */
export interface Offset {
  dx: number;
  dy: number;
}
export const CENTRE: Offset = { dx: 0, dy: 0 };

/** What the reader asked to look at. */
export type Place =
  | { kind: "none" }
  | { kind: "recorded"; target: RecordedId }
  /** Any position, built by the engine. `name` is what the reader typed or picked, if a name. */
  | { kind: "position"; ra: number; dec: number; name: string | null };
export type AskedPlace = Exclude<Place, { kind: "none" }>;
export const NO_PLACE: Place = { kind: "none" };

/** One load: what was asked, at which field of view. A new id is a new load, even of the same place. */
export interface LoadRequest {
  id: number;
  place: AskedPlace;
  fov: Fov;
  /** The target row that asked for it, if any: its caption reads "Building this image…". */
  target: TargetId | null;
}

/** A field ready to show. */
export interface LoadedField {
  manifest: Manifest;
  synth: FieldSynth;
  /** "bundled": the copy shipped with the site, because the engine did not answer. */
  source: FieldSource;
  /** The recorded field this is, or null for a live build of a position. */
  recorded: RecordedId | null;
}

export type Load =
  /** Nothing asked for yet: "No position chosen yet." */
  | { phase: "idle" }
  /** Asked. `building` turns true once the engine reports a build stage (HTTP 202). */
  | { phase: "loading"; progress: LoadProgress | null; building: boolean }
  /**
   * On screen. `fallback` names the recorded field shown INSTEAD of the place asked for, when
   * the engine or the archive did not answer ("The archive is not responding...").
   */
  | { phase: "ready"; field: LoadedField; fallback: boolean }
  /** No public SPHEREx image covers the position (manifest status "empty"). */
  | { phase: "empty"; manifest: Manifest }
  /** The engine's queue is full; Try again opens at `retryAt` (ms since 1970). */
  | { phase: "busy"; retryAt: number }
  /** Any other failure, with the loader's own sentence for the reader. */
  | { phase: "failed"; code: FieldErrorCode | "unexpected"; message: string };

/** The message line while a name is being looked up (Handoff-copy). */
export const NAME_LOOKUP_MESSAGE = "Looking up the name.";

export interface SearchState {
  /** The entry exactly as typed. Never rewritten. */
  text: string;
  /** The message line, once something happened; null shows the default for the place. */
  message: string | null;
  /** The message is an error: warning icon, role alert, aria-invalid. */
  error: boolean;
  /** An entry is being resolved. */
  busy: boolean;
  /** The target row whose name is being resolved, if any. */
  target: TargetId | null;
}

export interface MoverNotice {
  hint: MoverHint;
  /** The position that was entered: where the object was in `hint.wasHereYear`. */
  from: { ra: number; dec: number };
  /** True once the reader jumped (or arrived) where it is now: the banner stays, without its button. */
  jumped: boolean;
}

export type CopyStatus = "idle" | "copied" | "failed";

/** The Chart and Table switch of the spectrum panel. */
export type SpectrumMode = "chart" | "table";

/** Everything the reader can change, and what is loading. */
export interface ViewState {
  /** What is asked for. Null: no position chosen. */
  request: LoadRequest | null;
  /** How many requests have been made: the next request's id. */
  requests: number;
  load: Load;
  /** Field of view for the next request (and of the current one). */
  fov: Fov;
  /** The chosen band; null: the field's default band. */
  band: BandId | null;
  view: ViewId;
  /** The frame on screen, as an index into the time-ordered sequence; null: the opening frame. */
  frame: number | null;
  /** The flip partner; null: the default (the full frame farthest from the frame). */
  partner: number | null;
  /** The flip key is held: the partner is on screen. */
  held: boolean;
  playing: boolean;
  /** Frame changes per second while playing, 1 to 6. */
  speed: number;
  /** The ring, as an offset from the centre pixel. */
  ring: Offset;
  /** The keyboard's pixel cursor, or null. */
  cursor: Offset | null;
  spotlight: boolean;
  /** Contrast step, 0 to 8; 5 is the shared scale as computed. */
  contrast: number;
  invert: boolean;
  /** Markers over the image, the ring included. */
  markers: boolean;
  /** The spectrum panel is open (Spectrum in the ring row is lit). A link restores it. */
  spectrum: boolean;
  /** What the open spectrum panel shows: the chart or the table of the same values. */
  spectrumMode: SpectrumMode;
  search: SearchState;
  /** The moved-object banner, when the search found a fast mover. */
  mover: MoverNotice | null;
  copy: CopyStatus;
}

export const CONTRAST_STEPS = 8;
export const DEFAULT_CONTRAST = 5;
export const DEFAULT_SPEED = DEFAULT_FPS;
export const MAX_SPEED = MAX_FPS;

export const INITIAL_STATE: ViewState = {
  request: null,
  requests: 0,
  load: { phase: "idle" },
  fov: DEFAULT_FOV,
  band: null,
  view: "blink",
  frame: null,
  partner: null,
  held: false,
  playing: false,
  speed: DEFAULT_SPEED,
  ring: CENTRE,
  cursor: null,
  spotlight: false,
  contrast: DEFAULT_CONTRAST,
  invert: false,
  markers: true,
  spectrum: false,
  spectrumMode: "chart",
  search: { text: "", message: null, error: false, busy: false, target: null },
  mover: null,
  copy: "idle",
};

// ---------------------------------------------------------------------------------------------
// The five targets (docs/design/system/components/TargetCard/README.md)
// ---------------------------------------------------------------------------------------------

export interface Target {
  id: TargetId;
  name: string;
  caption: string;
  /** Carries the "Saturated core" chip. */
  saturated: boolean;
  /** The recorded field it opens at once, or null when it opens a build of its position. */
  recorded: RecordedId | null;
  /**
   * Where a target without a recorded field is: a catalogue position at its epoch with its proper
   * motion, and where those numbers come from. The row opens a build centred where it is at the
   * frames' reference epoch (targetPosition), with no name lookup and no network but the engine.
   */
  astrometry: (Astrometry & { source: string }) | null;
  /** Its default band; null: the default for any position. */
  defaultBand: BandId | null;
}

export const TARGETS: readonly Target[] = [
  {
    id: "wise0855",
    name: "WISE 0855",
    caption: "Visible only at 4 to 5 µm. Moved 4.4″ in six months.",
    saturated: false,
    recorded: "wise0855",
    astrometry: null,
    defaultBand: "cold",
  },
  {
    id: "barnard",
    name: "Barnard's Star",
    caption: "Moves 10.25″ a year. Its centre is saturated.",
    saturated: true,
    recorded: "barnard",
    astrometry: null,
    defaultBand: "all",
  },
  {
    id: "epsindi",
    name: "Epsilon Indi B",
    caption: "An unresolved pair of brown dwarfs. Motion not yet measured.",
    saturated: false,
    recorded: null,
    // Gaia DR3 6412596012146801152 (Epsilon Indi Ba/Bb), ICRS at epoch 2016.0: read from the ESA
    // Gaia archive for science/prototypes/barnard_common.py, and the same values from the team
    // backend's /stars on 14 Nov 2026 (overlays/sky.test.ts checks the propagation with astropy).
    astrometry: {
      ra: 331.07645259656397,
      dec: -56.79381206688221,
      epoch: 2016.0,
      pmra: 3981.97666296105,
      pmdec: -2466.8318147663504,
      source: "Gaia DR3 6412596012146801152: position at epoch 2016.0 and proper motion",
    },
    defaultBand: null,
  },
  {
    id: "rwaur",
    name: "RW Aurigae",
    caption: "Brighter at 1.2 µm, fainter at 4.6 µm across three visits.",
    saturated: false,
    recorded: null,
    // SIMBAD (ICRS, epoch J2000), read on 14 Nov 2026 through the Harvard mirror for
    // science/prototypes/variability_phot.py.
    astrometry: {
      ra: 76.95652603458333,
      dec: 30.401438173888888,
      epoch: 2000.0,
      pmra: 7.23,
      pmdec: -20.33,
      source: "SIMBAD: position at epoch J2000 and proper motion",
    },
    defaultBand: null,
  },
  {
    id: "rdra",
    name: "R Draconis",
    caption: "Saturated in almost every exposure.",
    saturated: true,
    recorded: null,
    // SIMBAD (ICRS, epoch J2000), as for RW Aurigae.
    astrometry: {
      ra: 248.16761083295,
      dec: 66.75497941722,
      epoch: 2000.0,
      pmra: -20.643,
      pmdec: 6.149,
      source: "SIMBAD: position at epoch J2000 and proper motion",
    },
    defaultBand: null,
  },
];

/**
 * Where a target without a recorded field is at the frames' reference epoch (EPOCH_NOW, the
 * contract's epoch_ref), moved by proper motion with the front end's one propagation
 * (overlays/sky.ts), rounded to the contract's 4 decimals. Null for a recorded target.
 */
export function targetPosition(target: Target): { ra: number; dec: number } | null {
  if (!target.astrometry) return null;
  const now = propagate(target.astrometry, EPOCH_NOW);
  return { ra: round4(now.ra), dec: round4(now.dec) };
}

export function targetById(id: TargetId): Target {
  const target = TARGETS.find((candidate) => candidate.id === id);
  if (!target) throw new RangeError(`unknown target "${id}"`);
  return target;
}

/** The target that opens a recorded field. */
export function targetOfRecorded(id: RecordedId): Target {
  const target = TARGETS.find((candidate) => candidate.recorded === id);
  if (!target) throw new RangeError(`no target opens the recorded field "${id}"`);
  return target;
}

/**
 * Centres of the recorded fields, copied from their manifests (web/public/fixtures/<name>/
 * manifest.json, `centre`); model.test.ts checks them against the files. A position this close
 * to one, at 6′, opens the recorded copy at once instead of a build.
 */
export const RECORDED_CENTRES: Readonly<Record<RecordedId, { ra: number; dec: number }>> = {
  wise0855: { ra: 133.7598, dec: -7.2422 },
  barnard: { ra: 269.4463, dec: 4.7682 },
};

/** How close a position must be to a recorded centre to open it: one native pixel. */
export const RECORDED_MATCH_ARCSEC = NATIVE_PIXEL_ARCSEC;

/** Small-angle separation of two positions, arcsec. Fine below a few arcminutes. */
export function separationArcsec(ra1: number, dec1: number, ra2: number, dec2: number): number {
  let dRa = Math.abs(ra1 - ra2) % 360;
  if (dRa > 180) dRa = 360 - dRa;
  const cosDec = Math.cos((((dec1 + dec2) / 2) * Math.PI) / 180);
  return Math.hypot(dRa * cosDec, dec1 - dec2) * 3600;
}

/** The recorded field centred within one native pixel of a position, or null. */
export function recordedNear(ra: number, dec: number): RecordedId | null {
  for (const id of FIXTURE_NAMES) {
    const centre = RECORDED_CENTRES[id];
    if (separationArcsec(ra, dec, centre.ra, centre.dec) <= RECORDED_MATCH_ARCSEC) return id;
  }
  return null;
}

/** The recorded field nearest a position: the one shown instead when the engine is down. */
export function nearestRecorded(ra: number, dec: number): RecordedId {
  let best: RecordedId = FIXTURE_NAMES[0];
  let bestSeparation = Number.POSITIVE_INFINITY;
  for (const id of FIXTURE_NAMES) {
    const centre = RECORDED_CENTRES[id];
    const separation = separationArcsec(ra, dec, centre.ra, centre.dec);
    if (separation < bestSeparation) {
      best = id;
      bestSeparation = separation;
    }
  }
  return best;
}

/** Rounded to the contract's centre precision (4 decimals, 0.36″). */
export const round4 = (degrees: number) => Math.round(degrees * 1e4) / 1e4;

/** Where a position opens: its recorded copy when there is one at this field of view, else a build. */
export function placeAt(ra: number, dec: number, fov: Fov, name: string | null): AskedPlace {
  const recorded = fov === RECORDED_FOV ? recordedNear(ra, dec) : null;
  if (recorded) return { kind: "recorded", target: recorded };
  return { kind: "position", ra, dec, name };
}

/** The position of a place, or null. */
export function positionOf(place: Place): { ra: number; dec: number } | null {
  if (place.kind === "position") return { ra: place.ra, dec: place.dec };
  if (place.kind === "recorded") return RECORDED_CENTRES[place.target];
  return null;
}

/** The text the search field starts with for a place opened without typing. */
export function searchTextFor(place: Place): string {
  if (place.kind === "recorded") return targetOfRecorded(place.target).name;
  if (place.kind === "position") return place.name ?? `${place.ra} ${place.dec}`;
  return "";
}

// ---------------------------------------------------------------------------------------------
// Bands and the time-ordered sequence of frames
// ---------------------------------------------------------------------------------------------

export interface BandInfo {
  id: BandId;
  /** First line of the option: "D1", "All", "Cold objects", "Three-colour". */
  label: string;
  /** Second line, in Source Code Pro: "0.74–1.12 µm", "R · G · B". */
  meta: string;
  /** Named in sentences: "D2", "Cold objects". */
  spoken: string;
}

export const BANDS: Readonly<Record<BandId, BandInfo>> = {
  d1: { id: "d1", label: "D1", meta: "0.74–1.12 µm", spoken: "D1" },
  d2: { id: "d2", label: "D2", meta: "1.10–1.65 µm", spoken: "D2" },
  d3: { id: "d3", label: "D3", meta: "1.64–2.42 µm", spoken: "D3" },
  d4: { id: "d4", label: "D4", meta: "2.42–3.82 µm", spoken: "D4" },
  d5: { id: "d5", label: "D5", meta: "3.81–4.42 µm", spoken: "D5" },
  d6: { id: "d6", label: "D6", meta: "4.41–5.00 µm", spoken: "D6" },
  all: { id: "all", label: "All", meta: "0.74–5.00 µm", spoken: "All" },
  cold: { id: "cold", label: "Cold objects", meta: "4.0–5.0 µm", spoken: "Cold objects" },
  rgb: { id: "rgb", label: "Three-colour", meta: "R · G · B", spoken: "Three-colour" },
};

/** The text alternative of the wavelength rule (Handoff-copy, section 14). */
export function ruleLabel(band: BandId): string {
  const shown: Record<BandId, string> = {
    d1: "D1, 0.74 to 1.12 micrometres",
    d2: "D2, 1.10 to 1.65 micrometres",
    d3: "D3, 1.64 to 2.42 micrometres",
    d4: "D4, 2.42 to 3.82 micrometres",
    d5: "D5, 3.81 to 4.42 micrometres",
    d6: "D6, 4.41 to 5.00 micrometres",
    all: "All bands, 0.74 to 5.00 micrometres",
    cold: "Cold objects, 4.0 to 5.0 micrometres",
    rgb: "Three-colour: red 3.8 to 5.0, green 1.6 to 3.8, blue 0.74 to 1.65 micrometres",
  };
  return `Wavelength rule with one tick for each of 102 channels, from 0.74 to 5.00 micrometres. Shown: ${shown[band]}.`;
}

export function bandBuilt(band: BandId, features: Features = FEATURES): boolean {
  return band !== "rgb" || features.threeColour;
}

export function viewBuilt(view: ViewId, features: Features = FEATURES): boolean {
  if (view === "side") return features.sideBySide;
  if (view === "difference") return features.difference;
  if (view === "then") return features.thenAndNow;
  return true;
}

/** Wave-bin ids a band selects (all three channels for three-colour). */
export function bandWaveBins(band: BandId): number[] {
  const selection = presetWaveBins(band);
  return selection.kind === "mono"
    ? selection.bins
    : [...selection.r, ...selection.g, ...selection.b];
}

/** True when at least one SPHEREx plane of the field lies in the band. */
export function bandHasData(manifest: Manifest, band: BandId): boolean {
  const bins = new Set(bandWaveBins(band));
  return manifest.planes.some(
    (plane) => plane.kind === "sci" && plane.wave_bin !== null && bins.has(plane.wave_bin),
  );
}

/** The nominal wavelength range of a band, from the contract's wave bins: for "Building this image". */
export function bandRange(band: BandId): string {
  const bins = new Set(bandWaveBins(band));
  const selected = contractWaveBins().filter((bin) => bins.has(bin.id));
  if (selected.length === 0) return rangeFixed(Number.NaN, Number.NaN);
  return rangeFixed(
    Math.min(...selected.map((bin) => bin.lam_min)),
    Math.max(...selected.map((bin) => bin.lam_max)),
  );
}

/** One frame of the sequence, with what the contract says about it (section 4). */
export interface SeqFrame {
  /** Position in the time-ordered sequence: what `frame` and `partner` count in. */
  index: number;
  timeBin: TimeBin;
  /** Pixels and statistics from FieldSynth. */
  frame: Frame;
  /** At least one plane of the band contributes. */
  hasData: boolean;
  /** The set of contributing wave bins differs from the union across visits. */
  partial: boolean;
  /** Fewer than 8 exposures went in. */
  thin: boolean;
  /** Has data, and is neither partial nor thin: may open, be subtracted, be a default partner. */
  full: boolean;
  /** The frame's own dates (its contributing planes), else the visit's. ISO. */
  dateStart: string;
  dateEnd: string;
  /** At least one pixel is NaN (drawn hatched). */
  hasNoData: boolean;
}

const sequenceCache = new WeakMap<FieldSynth, Map<BandId, SeqFrame[]>>();
const rgbCache = new WeakMap<FieldSynth, RgbFrame[]>();

/** A field's time bins, oldest first: the order of every sequence. */
function timeOrdered(synth: FieldSynth): TimeBin[] {
  return [...synth.manifest.time_bins].sort((a, b) => a.mjd_mid - b.mjd_mid);
}

/**
 * The three channel frames of the three-colour band (presets.json "rgb": red D5 and D6, green D3
 * and D4, blue D1 and D2), one per time bin in time order, each by the contract's frame formula.
 * Memoised per field.
 */
export function rgbChannelsOf(synth: FieldSynth): RgbFrame[] {
  const cached = rgbCache.get(synth);
  if (cached) return cached;
  const channels = timeOrdered(synth).map((timeBin) => synth.rgbFrameFor(timeBin.id, "rgb"));
  rgbCache.set(synth, channels);
  return channels;
}

/**
 * The facts of one visit in three-colour: the frame of the union of the three channels' wave
 * bins. So its range is the whole range the channels really have, its count is theirs together,
 * and it is partial when any channel lacks a wave bin that channel has at another visit.
 */
function rgbVisitFrame(synth: FieldSynth, timeBinId: number): Frame {
  const selection = synth.presetBins("rgb");
  const bins = selection.kind === "rgb" ? [...selection.r, ...selection.g, ...selection.b] : [];
  return synth.frameForBins(timeBinId, bins);
}

const hasNaN = (data: Float32Array) => data.some((value) => Number.isNaN(value));

/**
 * The frames of one band in time order, one per time bin. Memoised per field and band, so
 * selectors and the reducer can ask for it as often as they like.
 * Three-colour: `frame` holds the facts of the three channels together (rgbVisitFrame) and a
 * pixel is "no data" when any channel has none there; the channels are in rgbChannelsOf.
 */
export function sequenceOf(synth: FieldSynth, band: BandId): SeqFrame[] {
  let byBand = sequenceCache.get(synth);
  if (!byBand) {
    byBand = new Map();
    sequenceCache.set(synth, byBand);
  }
  const cached = byBand.get(band);
  if (cached) return cached;
  const bins = timeOrdered(synth);
  const channels = band === "rgb" ? rgbChannelsOf(synth) : null;
  const sequence = bins.map((timeBin, index): SeqFrame => {
    const frame =
      band === "rgb" ? rgbVisitFrame(synth, timeBin.id) : synth.frameFor(timeBin.id, band);
    const hasData = frame.waveBins.length > 0;
    const rgb = channels?.[index] ?? null;
    return {
      index,
      timeBin,
      frame,
      hasData,
      partial: frame.partial,
      thin: frame.thin,
      full: hasData && !frame.partial && !frame.thin,
      dateStart: frame.dateStart ?? timeBin.date_start,
      dateEnd: frame.dateEnd ?? timeBin.date_end,
      hasNoData: rgb
        ? hasNaN(rgb.r.data) || hasNaN(rgb.g.data) || hasNaN(rgb.b.data)
        : hasNaN(frame.data),
    };
  });
  byBand.set(band, sequence);
  return sequence;
}

/** The newest full frame; else the newest with data; else the last. Never a greyed one when a full one exists. */
export function openingFrame(sequence: readonly SeqFrame[]): number {
  for (let i = sequence.length - 1; i >= 0; i--) if (sequence[i].full) return i;
  for (let i = sequence.length - 1; i >= 0; i--) if (sequence[i].hasData) return i;
  return Math.max(0, sequence.length - 1);
}

/** The frame farthest in the sequence from `from` that passes `test`, earliest on a tie; null if none. */
function farthest(
  sequence: readonly SeqFrame[],
  from: number,
  test: (frame: SeqFrame) => boolean,
): number | null {
  let best: number | null = null;
  let distance = -1;
  for (const candidate of sequence) {
    if (candidate.index === from || !test(candidate)) continue;
    const d = Math.abs(candidate.index - from);
    if (d > distance) {
      best = candidate.index;
      distance = d;
    }
  }
  return best;
}

/** The default flip partner: the full frame farthest from `frame`; else any with data; else itself. */
export function defaultPartner(sequence: readonly SeqFrame[], frame: number): number {
  return (
    farthest(sequence, frame, (f) => f.full) ?? farthest(sequence, frame, (f) => f.hasData) ?? frame
  );
}

/** The two frames the comparator holds, resolved against the sequence. */
export interface Pair {
  /** The frame on screen when nothing is held. */
  frame: number;
  /** The one the flip key goes to. */
  partner: number;
  /** What is on screen now: the partner while the key is held in Blink. */
  shown: number;
  /** The earlier of the two (A). */
  a: number;
  /** The later of the two (B). */
  b: number;
}

const validIndex = (value: number | null, count: number): value is number =>
  value !== null && Number.isInteger(value) && value >= 0 && value < count;

/**
 * Frame and partner after defaults and rules: the opening frame when none is chosen, a partner
 * that differs from the frame, and in Difference two full frames (greyed ones cannot be
 * subtracted).
 */
export function resolvePair(
  sequence: readonly SeqFrame[],
  frame: number | null,
  partner: number | null,
  view: ViewId,
  held: boolean,
): Pair | null {
  const count = sequence.length;
  if (count === 0) return null;
  let f = validIndex(frame, count) ? frame : openingFrame(sequence);
  let p = validIndex(partner, count) && partner !== f ? partner : defaultPartner(sequence, f);
  if (view === "difference") {
    if (!sequence[f].full) f = openingFrame(sequence);
    if (!sequence[p].full || p === f) p = farthest(sequence, f, (s) => s.full) ?? p;
  }
  const shown = view === "blink" && held ? p : f;
  return { frame: f, partner: p, shown, a: Math.min(f, p), b: Math.max(f, p) };
}

// ---------------------------------------------------------------------------------------------
// Resolved state: the band, view and pair actually in force
// ---------------------------------------------------------------------------------------------

/** The field on screen, or null. */
export function fieldOf(state: ViewState): LoadedField | null {
  return state.load.phase === "ready" ? state.load.field : null;
}

/** What is on screen: the recorded field shown instead when the archive did not answer. */
export function shownPlace(state: ViewState): Place {
  const field = fieldOf(state);
  if (field?.recorded && state.load.phase === "ready" && state.load.fallback) {
    return { kind: "recorded", target: field.recorded };
  }
  return state.request?.place ?? NO_PLACE;
}

/**
 * The default band of what is on screen: the target's own, else All. A target's field at another
 * size (or the field of a target row) keeps the target's band: WISE 0855 is visible only in Cold
 * objects, whatever the field of view.
 */
export function defaultBandOf(state: ViewState): BandId {
  const place = shownPlace(state);
  if (place.kind === "recorded") return targetOfRecorded(place.target).defaultBand ?? "all";
  const target = state.request?.target ?? null;
  if (target !== null) return targetById(target).defaultBand ?? "all";
  return "all";
}

/** The band in force: the chosen one when it is built and has data here, else the default. */
export function effectiveBand(state: ViewState, features: Features = FEATURES): BandId {
  const field = fieldOf(state);
  const usable = (band: BandId) =>
    bandBuilt(band, features) && (field === null || bandHasData(field.manifest, band));
  if (state.band !== null && usable(state.band)) return state.band;
  const fallback = defaultBandOf(state);
  if (usable(fallback)) return fallback;
  return BAND_IDS.find(usable) ?? "all";
}

/** The sequence of the band in force, or null while no field is on screen. */
export function sequenceIn(state: ViewState, features: Features = FEATURES): SeqFrame[] | null {
  const field = fieldOf(state);
  return field ? sequenceOf(field.synth, effectiveBand(state, features)) : null;
}

/** Why a view cannot be used on this field, or null when it can. */
export function viewBlocked(
  view: ViewId,
  sequence: readonly SeqFrame[] | null,
  manifest: Manifest | null,
): string | null {
  if (!sequence || !manifest) return null;
  // One line each in the 362px view rail (the view rail is laid out to fit at 1280 × 720).
  if (view === "side" && sequence.filter((f) => f.hasData).length < 2) {
    return "Side by side is greyed: only one frame covers this.";
  }
  if (view === "difference" && sequence.filter((f) => f.full).length < 2) {
    return "Difference is greyed: fewer than two full frames.";
  }
  if (view === "then" && !manifest.planes.some((plane) => plane.kind === "legacy")) {
    return "Then and now is greyed: no older survey image here.";
  }
  return null;
}

/** The view in force: Blink unless the chosen one is built and usable with a frame on screen. */
export function effectiveView(state: ViewState, features: Features = FEATURES): ViewId {
  const field = fieldOf(state);
  if (!field || !viewBuilt(state.view, features)) return "blink";
  return viewBlocked(state.view, sequenceIn(state, features), field.manifest)
    ? "blink"
    : state.view;
}

export interface Resolved {
  field: LoadedField;
  band: BandId;
  view: ViewId;
  sequence: SeqFrame[];
  pair: Pair;
}

/** Band, view, sequence and pair in force, or null when no field with frames is on screen. */
export function resolve(state: ViewState, features: Features = FEATURES): Resolved | null {
  const field = fieldOf(state);
  if (!field) return null;
  const band = effectiveBand(state, features);
  const sequence = sequenceOf(field.synth, band);
  const view = effectiveView(state, features);
  const pair = resolvePair(sequence, state.frame, state.partner, view, state.held);
  return pair ? { field, band, view, sequence, pair } : null;
}

// ---------------------------------------------------------------------------------------------
// Actions and the reducer
// ---------------------------------------------------------------------------------------------

export type Action =
  /** Open a place (or none). Starts a new load and resets the frame, pair, ring and spotlight. */
  | {
      type: "go";
      place: Place;
      fov?: Fov;
      /** The search field's text; kept as it is when absent. */
      text?: string;
      /** The message line; the place's default when absent. */
      message?: string | null;
      /** The moved-object banner to show with the place. */
      mover?: MoverNotice | null;
      /** The target row that asked (recorded places name their own). */
      target?: TargetId | null;
      /** From a link: honoured when they fit the field. */
      band?: BandId | null;
      frame?: number | null;
      partner?: number | null;
      ring?: Offset;
      spotlight?: boolean;
      /** The spectrum panel open (a link, or the same sky at another size); closed when absent. */
      spectrum?: boolean;
    }
  /** Load the same place again ("Try again"). */
  | { type: "retry" }
  | { type: "loadProgress"; requestId: number; progress: LoadProgress }
  | { type: "loaded"; requestId: number; field: LoadedField; fallback: boolean }
  | { type: "loadEmpty"; requestId: number; manifest: Manifest }
  | { type: "loadBusy"; requestId: number; retryAt: number }
  | { type: "loadFailed"; requestId: number; code: FieldErrorCode | "unexpected"; message: string }
  /** A new field of view. A recorded field exists at 6′ only: other sizes build its centre. */
  | { type: "setFov"; fov: Fov }
  | { type: "setBand"; band: BandId }
  | { type: "setView"; view: ViewId }
  /** Previous (−1) or next (+1) frame, in Blink. Stops playback; never changes the partner. */
  | { type: "step"; delta: number }
  /** One playback tick: the next frame, while playing. */
  | { type: "tick" }
  /** Show this frame; the frame it replaces becomes the flip partner. Stops playback. */
  | { type: "pickFrame"; index: number }
  /** Hold to flip: down shows the partner, up returns. */
  | { type: "flip"; held: boolean }
  | { type: "play" }
  | { type: "pause" }
  | { type: "setSpeed"; speed: number }
  /** Move the ring (a click or a tap on the image). Clears the pixel cursor. */
  | { type: "setRing"; ring: Offset }
  /** Move the pixel cursor; the first move starts from the ring. */
  | { type: "moveCursor"; dx: number; dy: number }
  /** Enter on the image: the ring moves to the cursor, and the cursor goes. */
  | { type: "commitCursor" }
  | { type: "clearCursor" }
  | { type: "setSpotlight"; on: boolean }
  /** Esc: stop playing; pressed again, close the spotlight. */
  | { type: "escape" }
  | { type: "setContrast"; contrast: number }
  | { type: "setInvert"; on: boolean }
  | { type: "setMarkers"; on: boolean }
  /** Open or close the spectrum panel (only with a field on screen, when the part is built). */
  | { type: "setSpectrum"; open: boolean }
  | { type: "setSpectrumMode"; mode: SpectrumMode }
  | { type: "setQuery"; text: string }
  /**
   * An entry is being resolved. The message line says what is known so far: "Looking up the
   * name." for a name, how a position was read ("Read as …") while the fast-mover check runs,
   * never the sentence of the field shown before.
   */
  | { type: "searchStarted"; nameLike: boolean; target?: TargetId | null; message?: string | null }
  | { type: "searchFailed"; message: string }
  /** A search still waiting was stopped (the reader chose something else): the field works again. */
  | { type: "searchCancelled" }
  /** "Go to where it is now": the mover's position at the reference epoch. */
  | { type: "jump" }
  | { type: "copy"; status: CopyStatus }
  /** Escape hatch for lanes: set fields directly. The reducer does not check them. */
  | { type: "patch"; patch: Partial<ViewState> };

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

/** The largest offset a pixel can have from the centre in a field of `imagePx` pixels. */
const halfSize = (imagePx: number) => Math.floor(imagePx / 2);

function clampOffset(offset: Offset, imagePx: number): Offset {
  const half = halfSize(imagePx);
  return {
    dx: clamp(Math.round(offset.dx), -half, half),
    dy: clamp(Math.round(offset.dy), -half, half),
  };
}

/** Image pixels along a side for a field of view (contract section 2). */
export function imagePxFor(fov: Fov): number {
  return 2 * Math.round((fov * 60) / (2 * (NATIVE_PIXEL_ARCSEC / 2))) + 1;
}

function imagePxOf(state: ViewState): number {
  return fieldOf(state)?.manifest.grid.nx ?? imagePxFor(state.fov);
}

const sameOffset = (a: Offset | null, b: Offset | null) =>
  a === b || (a !== null && b !== null && a.dx === b.dx && a.dy === b.dy);

function goTo(state: ViewState, action: Extract<Action, { type: "go" }>): ViewState {
  const fov = action.fov ?? state.fov;
  const place = action.place;
  const target =
    action.target ?? (place.kind === "recorded" ? targetOfRecorded(place.target).id : null);
  const request: LoadRequest | null =
    place.kind === "none" ? null : { id: state.requests + 1, place, fov, target };
  return {
    ...state,
    request,
    requests: request ? request.id : state.requests,
    load: request ? { phase: "loading", progress: null, building: false } : { phase: "idle" },
    fov,
    band: action.band ?? null,
    frame: action.frame ?? null,
    partner: action.partner ?? null,
    held: false,
    playing: false,
    ring: clampOffset(action.ring ?? CENTRE, imagePxFor(fov)),
    cursor: null,
    spotlight: action.spotlight ?? false,
    spectrum: action.spectrum ?? false,
    search: {
      text: action.text ?? state.search.text,
      message: action.message ?? null,
      error: false,
      busy: false,
      target: null,
    },
    mover: action.mover ?? null,
  };
}

/** True when an action answers the request in force (a late answer to an older one is dropped). */
const current = (state: ViewState, requestId: number) => state.request?.id === requestId;

/** The reducer, for a set of feature flags. */
export function createReducer(features: Features = FEATURES) {
  return function reduce(state: ViewState, action: Action): ViewState {
    switch (action.type) {
      case "go":
        return goTo(state, action);

      case "retry": {
        if (!state.request) return state;
        const request = { ...state.request, id: state.requests + 1 };
        return {
          ...state,
          request,
          requests: request.id,
          load: { phase: "loading", progress: null, building: false },
          held: false,
          playing: false,
        };
      }

      case "loadProgress": {
        if (!current(state, action.requestId) || state.load.phase !== "loading") return state;
        const building = state.load.building || action.progress.stage !== "frames";
        return { ...state, load: { phase: "loading", progress: action.progress, building } };
      }

      case "loaded":
        if (!current(state, action.requestId)) return state;
        return {
          ...state,
          load: { phase: "ready", field: action.field, fallback: action.fallback },
        };

      case "loadEmpty":
        if (!current(state, action.requestId)) return state;
        return { ...state, load: { phase: "empty", manifest: action.manifest } };

      case "loadBusy":
        if (!current(state, action.requestId)) return state;
        return { ...state, load: { phase: "busy", retryAt: action.retryAt } };

      case "loadFailed":
        if (!current(state, action.requestId)) return state;
        return { ...state, load: { phase: "failed", code: action.code, message: action.message } };

      case "setFov": {
        if (!FOVS.includes(action.fov) || action.fov === state.fov) return state;
        const place = state.request?.place ?? null;
        if (place === null) return { ...state, fov: action.fov };
        let next: AskedPlace;
        if (place.kind === "recorded") {
          const target = targetOfRecorded(place.target);
          const centre = RECORDED_CENTRES[place.target];
          next = placeAt(centre.ra, centre.dec, action.fov, target.name);
        } else {
          next = placeAt(place.ra, place.dec, action.fov, place.name);
        }
        // The same sky, at another size: band, view, ring and spotlight stay; the frames are new.
        return goTo(state, {
          type: "go",
          place: next,
          fov: action.fov,
          band: state.band,
          ring: state.ring,
          spotlight: state.spotlight,
          spectrum: state.spectrum,
          message: state.search.message,
          mover: state.mover,
          target: state.request?.target ?? null,
        });
      }

      case "setBand": {
        if (!bandBuilt(action.band, features)) return state;
        const field = fieldOf(state);
        if (field && !bandHasData(field.manifest, action.band)) return state;
        if (action.band === state.band) return state;
        // The same visits stay on screen: every band has one frame per time bin, in the same
        // order. A frame with no data in the new band is not kept (null: the default).
        let frame: number | null = null;
        let partner: number | null = null;
        const r = resolve(state, features);
        if (field && r) {
          const next = sequenceOf(field.synth, action.band);
          const usable = (i: number) => i >= 0 && i < next.length && next[i].hasData;
          if (usable(r.pair.frame)) frame = r.pair.frame;
          if (usable(r.pair.partner) && r.pair.partner !== frame) partner = r.pair.partner;
        }
        return {
          ...state,
          band: action.band,
          frame,
          partner,
          held: false,
          playing: false,
        };
      }

      case "setView": {
        if (!viewBuilt(action.view, features) || !fieldOf(state)) return state;
        const field = fieldOf(state);
        if (field && viewBlocked(action.view, sequenceIn(state, features), field.manifest)) {
          return state;
        }
        if (action.view === state.view) return state;
        return { ...state, view: action.view, held: false, playing: false };
      }

      case "step": {
        const r = resolve(state, features);
        if (r?.view !== "blink" || r.sequence.length < 2) return state;
        return {
          ...state,
          frame: stepIndex(r.pair.frame, r.sequence.length, action.delta),
          partner: r.pair.partner,
          held: false,
          playing: false,
        };
      }

      case "tick": {
        const r = resolve(state, features);
        if (!state.playing || r?.view !== "blink" || r.sequence.length < 2) return state;
        return {
          ...state,
          frame: stepIndex(r.pair.frame, r.sequence.length, 1),
          partner: r.pair.partner,
        };
      }

      case "pickFrame": {
        const r = resolve(state, features);
        if (!r || !validIndex(action.index, r.sequence.length)) return state;
        if (r.view === "difference" && !r.sequence[action.index].full) return state;
        const partner = action.index === r.pair.frame ? r.pair.partner : r.pair.frame;
        return { ...state, frame: action.index, partner, held: false, playing: false };
      }

      case "flip": {
        const r = resolve(state, features);
        if (action.held === state.held) return state;
        if (action.held && (r?.view !== "blink" || !features.holdToFlip)) return state;
        return {
          ...state,
          held: action.held,
          playing: action.held ? false : state.playing,
          // Freeze the default partner so that it cannot change while the key is held.
          frame: r ? r.pair.frame : state.frame,
          partner: r ? r.pair.partner : state.partner,
        };
      }

      case "play": {
        const r = resolve(state, features);
        if (state.playing || r?.view !== "blink" || r.sequence.length < 2) return state;
        return {
          ...state,
          playing: true,
          held: false,
          frame: r.pair.frame,
          partner: r.pair.partner,
        };
      }

      case "pause":
        return state.playing ? { ...state, playing: false } : state;

      case "setSpeed": {
        const speed = clamp(Math.round(action.speed), 1, MAX_SPEED);
        return Number.isFinite(speed) && speed !== state.speed ? { ...state, speed } : state;
      }

      case "setRing": {
        if (!fieldOf(state)) return state;
        const ring = clampOffset(action.ring, imagePxOf(state));
        if (sameOffset(ring, state.ring) && state.cursor === null) return state;
        return { ...state, ring, cursor: null };
      }

      case "moveCursor": {
        if (!fieldOf(state)) return state;
        const from = state.cursor ?? state.ring;
        const cursor = clampOffset(
          { dx: from.dx + action.dx, dy: from.dy + action.dy },
          imagePxOf(state),
        );
        return sameOffset(cursor, state.cursor) ? state : { ...state, cursor };
      }

      case "commitCursor":
        if (state.cursor === null) return state;
        return { ...state, ring: state.cursor, cursor: null };

      case "clearCursor":
        return state.cursor === null ? state : { ...state, cursor: null };

      case "setSpotlight": {
        const on = action.on && features.spotlight && fieldOf(state) !== null;
        return on === state.spotlight ? state : { ...state, spotlight: on };
      }

      case "escape":
        if (state.playing) return { ...state, playing: false };
        if (state.spotlight) return { ...state, spotlight: false };
        return state;

      case "setContrast": {
        const contrast = clamp(Math.round(action.contrast), 0, CONTRAST_STEPS);
        return Number.isFinite(contrast) && contrast !== state.contrast
          ? { ...state, contrast }
          : state;
      }

      case "setInvert":
        return action.on === state.invert ? state : { ...state, invert: action.on };

      case "setMarkers":
        return action.on === state.markers ? state : { ...state, markers: action.on };

      case "setSpectrum": {
        const open = action.open && features.spectrum && fieldOf(state) !== null;
        return open === state.spectrum ? state : { ...state, spectrum: open };
      }

      case "setSpectrumMode":
        return action.mode === state.spectrumMode ? state : { ...state, spectrumMode: action.mode };

      case "setQuery":
        // Typing clears an error, its sentence included: the line returns to the place's default.
        return {
          ...state,
          search: {
            ...state.search,
            text: action.text,
            error: false,
            message: state.search.error ? null : state.search.message,
          },
        };

      case "searchStarted":
        return {
          ...state,
          search: {
            ...state.search,
            busy: true,
            error: false,
            message: action.nameLike ? NAME_LOOKUP_MESSAGE : (action.message ?? null),
            target: action.target ?? null,
          },
        };

      case "searchFailed":
        return {
          ...state,
          search: {
            ...state.search,
            busy: false,
            error: true,
            message: action.message,
            target: null,
          },
        };

      case "searchCancelled":
        if (!state.search.busy) return state;
        return {
          ...state,
          search: { ...state.search, busy: false, error: false, message: null, target: null },
        };

      case "jump": {
        const mover = state.mover;
        if (!mover || mover.jumped) return state;
        const { ra, dec } = mover.hint.now;
        return goTo(state, {
          type: "go",
          place: placeAt(round4(ra), round4(dec), state.fov, mover.hint.name),
          message: state.search.message,
          mover: { ...mover, jumped: true },
          band: state.band,
          // The ring opens on the object where it is now: its spectrum, if the panel was open.
          spectrum: state.spectrum,
        });
      }

      case "copy":
        return action.status === state.copy ? state : { ...state, copy: action.status };

      case "patch":
        return { ...state, ...action.patch };
    }
  };
}

/** The reducer with the flags of this build. */
export const reduce = createReducer(FEATURES);

// ---------------------------------------------------------------------------------------------
// Selectors: the words and numbers the design shows, from the data
// ---------------------------------------------------------------------------------------------

/** "Partial: a different mix of wavelengths. Thin: fewer than 8 exposures." (each only when such a row is listed) */
export function timelineKey(sequence: readonly SeqFrame[], view: ViewId): string {
  const anyPartial = sequence.some((f) => f.partial);
  const anyThin = sequence.some((f) => f.thin);
  const parts: string[] = [];
  if (view === "difference" && (anyPartial || anyThin)) {
    parts.push("Greyed frames cannot be subtracted.");
  }
  if (anyPartial) parts.push("Partial: a different mix of wavelengths.");
  if (anyThin) parts.push(`Thin: fewer than ${THIN_EXPOSURES} exposures.`);
  return parts.join(" ");
}

export interface TimelineRow {
  index: number;
  /** Short form: "7–14 Nov 2025". */
  when: string;
  /** "32 exposures", "11 exposures, partial", "4 exposures, thin". */
  count: string;
  partial: boolean;
  thin: boolean;
  hasData: boolean;
  /** Greyed and labelled (bc-visit--qualified): partial or thin. */
  qualified: boolean;
  /** Not pressable: in Difference, a greyed frame cannot be subtracted. */
  disabled: boolean;
  /** The frame on screen, in Blink only: aria-current="true" and a filled mark. */
  current: boolean;
  /** In Side by side and Difference, the epoch tag of the pair's two rows. */
  tag: "A" | "B" | null;
}

export function timelineRows(r: Resolved): TimelineRow[] {
  const pairView = r.view === "side" || r.view === "difference";
  return r.sequence.map((f) => ({
    index: f.index,
    when: shortDateRange(f.dateStart, f.dateEnd),
    count: rowCount(f.frame.nExposures, f.thin, f.partial),
    partial: f.partial,
    thin: f.thin,
    hasData: f.hasData,
    qualified: f.partial || f.thin,
    disabled: r.view === "difference" && !f.full,
    current: r.view === "blink" && f.index === r.pair.shown,
    tag: pairView ? (f.index === r.pair.a ? "A" : f.index === r.pair.b ? "B" : null) : null,
  }));
}

/** The plate annotation of one frame, every field at fixed length. */
export interface FrameLabel {
  /** "07 Nov to 14 Nov 2025": 21 characters, padded to the longest of the sequence. */
  when: string;
  /** "3.96 to 5.00 µm": the mix this frame really has. */
  range: string;
  /** "  9 exposures": right-aligned in three characters. */
  count: string;
  partial: boolean;
  thin: boolean;
  /** "Saturated core": the pipeline found a saturated core near the centre of this field. */
  saturated: boolean;
  hasData: boolean;
}

/**
 * How much of the field's centre the pipeline found saturated: "most" when its warning says a
 * saturated core in at least half of the exposures ("in 359 of 360 exposures"; a warning without
 * the count counts as most), "some" when it says fewer, "none" without such a warning.
 */
export type Saturation = "none" | "some" | "most";

/** The engine looks for a saturated core within this distance of the centre (its warning says so). */
export const SATURATED_CORE_ARCSEC = 15;

export function saturationOf(manifest: Manifest): Saturation {
  let saturation: Saturation = "none";
  for (const warning of manifest.warnings) {
    if (!/saturated core/i.test(warning)) continue;
    const count = /\bin (\d+) of (\d+) exposures\b/i.exec(warning);
    const most = count === null || Number(count[1]) * 2 >= Number(count[2]);
    if (most) return "most";
    saturation = "some";
  }
  return saturation;
}

/** True when a frame has a no-data pixel within SATURATED_CORE_ARCSEC of the field's centre. */
export function blankCore(data: Float32Array, manifest: Manifest): boolean {
  const { nx, ny, cx, cy, pixscale_arcsec: pixscale } = manifest.grid;
  const radius = SATURATED_CORE_ARCSEC / pixscale;
  const reach = Math.floor(radius);
  for (let dy = -reach; dy <= reach; dy++) {
    const row = cy + dy;
    if (row < 0 || row >= ny) continue;
    for (let dx = -reach; dx <= reach; dx++) {
      const column = cx + dx;
      if (column < 0 || column >= nx || Math.hypot(dx, dy) > radius) continue;
      if (Number.isNaN(data[row * nx + column])) return true;
    }
  }
  return false;
}

/**
 * The frame label of every frame of a sequence: one fixed width for all of them. "Saturated core"
 * goes on a frame when the pipeline found the centre saturated in most exposures, or in a few
 * and this frame's own centre has no data: never on a field where a handful of the hundreds of
 * exposures overflowed and every frame has a value there (Epsilon Indi B: 3 of 461).
 */
export function frameLabels(sequence: readonly SeqFrame[], manifest: Manifest): FrameLabel[] {
  const dates = sequence.map((f) => fixedDateRange(f.dateStart, f.dateEnd));
  const width = Math.max(0, ...dates.map((text) => text.length));
  const saturation = saturationOf(manifest);
  return sequence.map((f, i) => ({
    when: dates[i].padEnd(width, " "),
    range: rangeFixed(f.frame.lamMin, f.frame.lamMax),
    count: countFixed(f.frame.nExposures),
    partial: f.partial,
    thin: f.thin,
    saturated:
      f.hasData &&
      (saturation === "most" || (saturation === "some" && blankCore(f.frame.data, manifest))),
    hasData: f.hasData,
  }));
}

/** An engine warning about an older-survey plane: "AllWISE W1: plane left out: <reason>". */
const LEFT_OUT = /^\s*(\S+) (\S+): plane left out: (.+)$/i;

/**
 * The engine writes one warning per older-survey plane it leaves out (five on most live fields
 * of pipeline 0.3.0). They concern Then and now only, so planes left out for the same reason
 * become one sentence: "Older survey images left out (AllWISE W1, W2; 2MASS J, H, Ks): their
 * brightness could not be matched to SPHEREx on field stars." The other warnings stay as they are.
 */
export function mergeLeftOut(warnings: readonly string[]): string[] {
  const byReason = new Map<string, Array<{ survey: string; band: string }>>();
  const out: Array<string | { reason: string }> = [];
  for (const warning of warnings) {
    const match = LEFT_OUT.exec(warning);
    if (!match) {
      out.push(warning);
      continue;
    }
    const [, survey, band, reason] = match;
    const planes = byReason.get(reason);
    if (planes) planes.push({ survey, band });
    else {
      byReason.set(reason, [{ survey, band }]);
      out.push({ reason });
    }
  }
  return out.map((item) => {
    if (typeof item === "string") return item;
    const planes = byReason.get(item.reason) ?? [];
    if (planes.length === 1) {
      return `${planes[0].survey} ${planes[0].band}: plane left out: ${item.reason}`;
    }
    const surveys = [...new Set(planes.map((p) => p.survey))].map(
      (survey) =>
        `${survey} ${planes
          .filter((p) => p.survey === survey)
          .map((p) => p.band)
          .join(", ")}`,
    );
    const reason = item.reason.replace(/^its /i, "their ");
    return `Older survey images left out (${surveys.join("; ")}): ${reason}`;
  });
}

/**
 * Every caveat about the whole field, one sentence each (CaveatList card): the manifest's
 * warnings with time bins written as dates (older-survey planes left out merged into one),
 * exposures that could not be used or were not read, and how many visits are partial or thin
 * in the band shown.
 */
export function caveatSentences(
  manifest: Manifest,
  sequence: readonly SeqFrame[] | null,
): string[] {
  const out: string[] = [];
  if (manifest.status === "partial") {
    out.push("The build stopped at its deadline, so some exposures are missing.");
  }
  const { found, used, sampled } = manifest.exposures;
  const warnings = mergeLeftOut(manifest.warnings).map((warning) =>
    rewriteWarning(warning, manifest.time_bins),
  );
  const saysUnused = manifest.warnings.some((warning) => /could not be used/i.test(warning));
  if (sampled) {
    // docs/CONTRACT_FIELDS.md: at most 600 exposures are used per field, sampled evenly per time
    // bin and detector. Found minus used is then mostly the sample, not exposures that failed.
    out.push(`${found} exposures cover this field; an even sample of at most 600 was read.`);
  } else if (found > used && !saysUnused) {
    const n = found - used;
    out.push(`${n} ${n === 1 ? "exposure" : "exposures"} could not be used.`);
  }
  out.push(...warnings);
  if (sequence && sequence.length > 0) {
    const n = sequence.length;
    const partial = sequence.filter((f) => f.partial).length;
    const thinOnly = sequence.filter((f) => f.thin && !f.partial).length;
    if (partial > 0) {
      out.push(
        `${partial} of ${n} visits ${partial === 1 ? "is" : "are"} partial, marked in Frames.`,
      );
    }
    if (thinOnly > 0) {
      out.push(
        `${thinOnly} of ${n} visits ${thinOnly === 1 ? "is" : "are"} thin, marked in Frames.`,
      );
    }
  }
  return [...new Set(out)];
}

/** Engine 0.3.0 names a visit by its ISO dates: "the visit of 2025-09-30 to 2025-10-01". */
const ISO_VISIT = /\bthe visit of (\d{4}-\d{2}-\d{2})(?: to (\d{4}-\d{2}-\d{2}))?/gi;
/** Engine 0.3.0 adds a reason after the count of a saturated core (below). */
const SATURATED_TAIL = /^(saturated core within .+? in \d+ of \d+ exposures?)\s*:.*$/i;
/** "bright core within 15″ of the centre flagged as overflowing in 119 of 360 exposures, but
 * measured: brightness there is indicative only" (engine 0.3.0). */
const OVERFLOW_CORE =
  /^(bright core within .+? of the centre) flagged as overflowing (in \d+ of \d+ exposures?), but measured: (.+)$/i;
/** "AllWISE W1: 1 image(s) not read (3306m561_ac51: UpstreamError: … HTTP 503)." */
const LEGACY_NOT_READ = /^(.+?): (\d+) image\(s\) not read \(.*\)\.?$/i;
/** "AllWISE: archive unavailable (UpstreamError: …); no AllWISE plane." */
const LEGACY_UNAVAILABLE = /^(\S+): archive unavailable \(.*\); no \S+ plane\.?$/i;

/**
 * "time bin 1 has only 9 exposures" -> "The visit of 30 Sep–1 Oct 2025 has only 9 exposures."
 * "2 exposures could not be used (no valid pixel or unknown noise)" -> "2 exposures could not be
 * used." (Handoff-copy: the reason is the engine's detail, not the reader's.) Engine 0.3.0's
 * words are brought to the same forms: a visit named by ISO dates is written as above; the
 * saturated core keeps Handoff-copy's form ("Saturated core within 15″ of the centre in 359 of 360
 * exposures.") without the reason it adds; an overflowing core is said in fewer words, keeping
 * "indicative only"; an older survey's failure is told without the archive's image ids and error
 * codes ("AllWISE W1: 1 image could not be read.").
 */
export function rewriteWarning(warning: string, timeBins: readonly TimeBin[]): string {
  const dated = warning
    .replace(/\btime bin (\d+)\b/gi, (whole, id: string) => {
      const bin = timeBins.find((candidate) => candidate.id === Number(id));
      return bin ? `the visit of ${shortDateRange(bin.date_start, bin.date_end)}` : whole;
    })
    .replace(ISO_VISIT, (whole, start: string, end: string | undefined) => {
      const range = shortDateRange(start, end ?? start);
      return range.includes("undefined") || range.includes("NaN") ? whole : `the visit of ${range}`;
    });
  const arcsec = dated.replace(/(\d+(?:\.\d+)?) ?arcsec\b/g, "$1″");
  const plain = arcsec
    .replace(/(could not be used)\s*\([^)]*\)/i, "$1")
    .replace(SATURATED_TAIL, "$1")
    .replace(OVERFLOW_CORE, "$1 overflowed $2: $3")
    .replace(LEGACY_NOT_READ, (_whole, label: string, count: string) => {
      const n = Number(count);
      return `${label}: ${n} ${n === 1 ? "image" : "images"} could not be read`;
    })
    .replace(LEGACY_UNAVAILABLE, (_whole, survey: string) => {
      return `${survey}: archive unavailable, so no ${survey} image`;
    });
  return asSentence(plain);
}

/** The shared brightness scale after the Contrast step: one scale for every frame. */
export function displayLimits(limits: Limits | null, contrast: number): Limits | null {
  if (!limits) return null;
  const factor = 2 ** ((DEFAULT_CONTRAST - clamp(contrast, 0, CONTRAST_STEPS)) / 2);
  return { ...limits, vmax: limits.vmin + (limits.vmax - limits.vmin) * factor };
}

/** Pooled limits of a sequence: computed once per sequence (render.ts), memoised here. */
const limitsCache = new WeakMap<readonly SeqFrame[], Limits | null>();
export function sequenceLimits(sequence: readonly SeqFrame[]): Limits | null {
  if (limitsCache.has(sequence)) return limitsCache.get(sequence) ?? null;
  const limits = pooledLimits(sequence.filter((f) => f.hasData).map((f) => f.frame));
  limitsCache.set(sequence, limits);
  return limits;
}

const RELEASES: Readonly<Record<string, string>> = {
  spherex_dr1: "DR1",
  spherex_dr1_deep: "DR1 deep",
  spherex_qr3: "QR3",
  spherex_qr3_deep: "QR3 deep",
};

/** Which release each DOI cites (docs/design/comparator/Phone.dc.html, Details). */
const DOI_RELEASES: Readonly<Record<string, string>> = {
  "10.26131/IRSA678": "DR1",
  "10.26131/IRSA662": "QR3",
};

export interface Provenance {
  /** "254 of 258". */
  used: string;
  sampled: boolean;
  /** "SPHEREx Spectral Images, DR1 and QR3": the releases whose exposures were used. */
  release: string;
  /** The DOIs of those releases, with the release each cites when known. */
  dois: { doi: string; release: string | null; href: string }[];
  /** "0.2.0". */
  pipeline: string;
  /** ISO timestamp of the build. */
  builtAt: string;
  /** The manifest's notes, as written. */
  notes: string[];
  /** "Resampled to 3.075″ per pixel; native pixel 6.15″". */
  pixels: string;
  /** "−0.0180 to 0.440 MJy/sr": the scale in force, or null without frames. */
  stretch: string | null;
  /** The caveat sentences, or ["None"]. */
  warnings: string[];
}

export function provenanceOf(
  manifest: Manifest,
  limits: Limits | null,
  caveats: readonly string[],
): Provenance {
  const releases = Object.keys(manifest.exposures.collections)
    .filter((name) => manifest.exposures.collections[name] > 0)
    .map((name) => RELEASES[name] ?? name);
  const unique = [...new Set(releases)];
  const release =
    unique.length === 0
      ? "SPHEREx Spectral Images"
      : `SPHEREx Spectral Images, ${unique.length === 1 ? unique[0] : `${unique.slice(0, -1).join(", ")} and ${unique.at(-1)}`}`;
  const dois = manifest.provenance.data_dois
    .map((doi) => ({ doi, release: DOI_RELEASES[doi] ?? null, href: `https://doi.org/${doi}` }))
    .filter((entry) => entry.release === null || unique.includes(entry.release));
  const pixscale = manifest.grid.pixscale_arcsec;
  return {
    used: `${manifest.exposures.used} of ${manifest.exposures.found}`,
    sampled: manifest.exposures.sampled,
    release,
    dois,
    pipeline: manifest.provenance.pipeline_version,
    builtAt: manifest.provenance.built_at,
    notes: manifest.provenance.notes,
    pixels: `Resampled to ${pixscale}″ per pixel; native pixel ${NATIVE_PIXEL_ARCSEC}″`,
    stretch: limits ? `${brightness(limits.vmin)} to ${brightness(limits.vmax)} MJy/sr` : null,
    warnings: caveats.length > 0 ? [...caveats] : ["None"],
  };
}

/** What the readout shows for one pixel: three fixed fields. */
export interface Readout {
  /** "133.75977°", or "—" when no pixel. */
  ra: string;
  /** "−7.24183°", or "—". */
  dec: string;
  /** "0.142 MJy/sr"; "A 0.142   B 0.150   MJy/sr"; "+2.3 σ"; "" in Then and now. */
  value: string;
}

export const NO_READOUT: Readout = { ra: "—", dec: "—", value: "— MJy/sr" };

/** The readout at an offset from the centre, for the view in force. */
export function readoutAt(r: Resolved, at: Offset): Readout {
  const { grid } = r.field.manifest;
  const column = grid.cx + at.dx;
  const row = grid.cy + at.dy;
  if (column < 0 || row < 0 || column >= grid.nx || row >= grid.ny) return NO_READOUT;
  const sky = pixelToSky(gridOf(r.field.manifest), column, row);
  const pixel = row * grid.nx + column;
  const pixelOf = (index: number) => r.sequence[index].frame.data[pixel];
  let value: string;
  if (r.view === "side") {
    value = `A ${brightness(pixelOf(r.pair.a))}   B ${brightness(pixelOf(r.pair.b))}   MJy/sr`;
  } else if (r.view === "difference") {
    const a = r.sequence[r.pair.a].frame;
    const b = r.sequence[r.pair.b].frame;
    value = sigmas((b.data[pixel] - a.data[pixel]) / Math.hypot(a.sigma, b.sigma));
  } else if (r.view === "then") {
    value = "";
  } else {
    const v = pixelOf(r.pair.shown);
    value = Number.isFinite(v) ? `${brightness(v)} MJy/sr` : "no data";
  }
  return { ra: formatRa(sky.ra), dec: formatDec(sky.dec), value };
}

/** The sentence of the moved-object banner, written from the mover hint. */
export function moverSentence(hint: MoverHint): string {
  return hint.sentence;
}

/** Name of the frame for screen readers (Handoff-copy, section 14). */
export function frameAriaLabel(r: Resolved, phone: boolean): string {
  const f = r.sequence[r.pair.shown];
  const tail = phone
    ? "Tap to move the ring."
    : "Arrow keys move the readout by one pixel. Enter moves the ring there.";
  return `Sky image, ${fixedDateRange(f.dateStart, f.dateEnd)}, ${rangeSpoken(f.frame.lamMin, f.frame.lamMax)}. ${tail}`;
}

/** What a step or a flip announces: "Frame 2 of 4, 07 Nov to 14 Nov 2025." */
export function frameAnnouncement(r: Resolved): string {
  const f = r.sequence[r.pair.shown];
  return `${frameCounter(r.pair.shown, r.sequence.length)}, ${fixedDateRange(f.dateStart, f.dateEnd)}.`;
}

/** Title strip (phone) and the name of what is on screen. */
export function titleOf(state: ViewState): { title: string; line: string } {
  const place = shownPlace(state);
  if (state.search.busy && state.search.message === NAME_LOOKUP_MESSAGE) {
    return { title: state.search.text || "Sky position", line: NAME_LOOKUP_MESSAGE };
  }
  if (place.kind === "none")
    return { title: "No position yet", line: "Type a position or a name below." };
  const field = fieldOf(state);
  const centre = field?.manifest.centre ?? positionOf(place);
  const line = centre ? positionLine(centre.ra, centre.dec) : "";
  if (place.kind === "recorded") return { title: targetOfRecorded(place.target).name, line };
  return { title: place.name ?? "Sky position", line };
}

/** The search message line when nothing new was said: the hint, or how the place was read. */
export function defaultSearchMessage(state: ViewState, hint: string): string {
  const place = state.request?.place ?? NO_PLACE;
  if (place.kind === "none") return hint;
  if (place.kind === "recorded") {
    return `Showing the recorded field for ${targetOfRecorded(place.target).name}.`;
  }
  return readAsSentence(place.ra, place.dec);
}

/** "Newest SPHEREx image: 5 Oct 2026" date part, from an ISO date. */
export const newestChipDate = shortDate;

/** The field-of-view option label: "6′". */
export const fovLabel = (fov: Fov) => `${fov}${ARCMIN}`;

/** "Frame 2 of 4" and "2 per second", re-exported for blocks that print them. */
export { frameCounter, speedLabel };
