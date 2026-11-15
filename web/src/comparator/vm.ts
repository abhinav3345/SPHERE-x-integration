/**
 * The ViewModel: everything a block of the comparator reads, and every handler it calls.
 * useComparator() returns one; Comparator passes it to every block as `{ vm }`.
 *
 * Rules for blocks (web/src/comparator/CONTRACT.md has the full list):
 * - Read from `vm`; never fetch, never keep a second copy of the state.
 * - Change things only through `vm.handlers` (or `vm.dispatch` / `vm.patch` for something the
 *   handlers do not cover). Picture changes (step, pick, flip, tick) MUST go through handlers:
 *   they pass the 6-per-second gate.
 * - Strings below are the design's own (Handoff-copy). Print them as they are.
 * - Anything a block needs that is not here can be derived from `vm.state`, `vm.field` and the
 *   selectors of model.ts, inside the lane's own folder.
 */

import type { FocusEvent, KeyboardEvent, MouseEvent, PointerEvent } from "react";
import type { FieldSource } from "../api";
import type { Manifest } from "../contract";
import type { SkyGrid } from "../player/grid";
import type { Limits } from "../player/render";
import type { DifferenceFrame, FieldSynth } from "../player/synth";
import type { ExtrasVM } from "./extras/types";
import type { Features } from "./features";
import type { Geometry, Layout } from "./geometry";
import type {
  Action,
  BandId,
  Fov,
  FrameLabel,
  Offset,
  Pair,
  Provenance,
  Readout,
  RecordedId,
  SeqFrame,
  TargetId,
  TimelineRow,
  ViewId,
  ViewState,
} from "./model";

/** Whether the frames engine answers: from GET /api/status at start, then from every load. */
export type EngineState = "unknown" | "up" | "down";

/**
 * What the image frame shows (ImageFrame card, StateGrammar):
 * - "image": a frame (or a pair) is on screen.
 * - "loading": a field is downloading and no build was reported (a recorded field): keep the
 *   square, show nothing in it.
 * - "building": the engine is building: the BuildProgress block (vm.image.build).
 * - "busy": "Too many requests are being built. Try again in NN seconds." (vm.image.busy).
 * - "empty": "No public SPHEREx image covers this position yet."
 * - "none": "No position chosen yet."
 * - "failed": the loader's own sentence (vm.image.failure) with Try again. Not on a board: the
 *   plain notice of the empty state, with that sentence.
 */
export type FrameState = "image" | "loading" | "building" | "busy" | "empty" | "none" | "failed";

/** The field on screen, its frames in the band in force, and the scale they share. */
export interface FieldVM {
  manifest: Manifest;
  /** Planes of the field; use synth.planeData / frameFor for anything not precomputed. */
  synth: FieldSynth;
  /** The projection of this field (player/grid.ts): pixelToSky, skyToPixel. */
  grid: SkyGrid;
  /** "api" from the engine, "bundled" from the copy shipped with the site. */
  source: FieldSource;
  /** The recorded field this is, or null for a live build. */
  recorded: RecordedId | null;
  /** True when this recorded field stands in for a place the archive could not build. */
  standIn: boolean;
  /** The band in force (the chosen one, or the field's default). */
  band: BandId;
  /** The view in force (Blink when the chosen one is not built or not usable here). */
  view: ViewId;
  /** The frames of the band, one per visit, oldest first. `index` is what frame numbers count. */
  sequence: SeqFrame[];
  /** Frame, partner, the one on screen (`shown`) and the earlier (a) and later (b) of the pair. */
  pair: Pair;
  /** sequence[pair.shown]: the frame on screen in Blink. */
  shown: SeqFrame;
  /** Pooled limits of the whole sequence (render.ts pooledLimits): one scale for every frame. */
  limits: Limits | null;
  /** The limits after the Contrast step (model.ts displayLimits). Draw EVERY frame with these. */
  displayLimits: Limits | null;
  /** Later minus earlier (B − A), in MJy/sr with its noise, in Difference; else null. */
  difference: DifferenceFrame | null;
  /** The frame label of every frame of the sequence, all of one width. */
  labels: FrameLabel[];
  /** True when any frame of the sequence has a no-data pixel: "No data" stays in the legend. */
  anyNoData: boolean;
}

export interface BuildStepVM {
  /** "Finding exposures", "Reading exposures", "Stacking". */
  label: string;
  /** "120 of 258" once the stage has started and the engine gave counts; else null. */
  value: string | null;
  /** The system's marks: empty, half (aria-current="step"), full. */
  state: "todo" | "doing" | "done";
}

export interface BuildVM {
  steps: [BuildStepVM, BuildStepVM, BuildStepVM];
  /** The bar follows the stage in progress; it is updated at most once a second. */
  bar: { now: number; max: number; label: string };
  /** "The first build takes about a minute; it is saved, so next time this position opens at once." */
  sentence: string;
}

export interface ImageVM {
  state: FrameState;
  /** Name of the frame for screen readers (Handoff-copy, section 14). */
  aria: string;
  /** Side by side: "Frame A, 07 Nov to 14 Nov 2025" and "Frame B, …"; else null. */
  pairAria: { a: string; b: string } | null;
  /** Present while building. */
  build: BuildVM | null;
  /** Present while the engine's queue is full. */
  busy: { secondsLeft: number; canRetry: boolean } | null;
  /** The loader's sentence when state is "failed". */
  failure: string | null;
  ring: Offset;
  cursor: Offset | null;
  /** Markers on: the ring (and, when built, the catalogue markers) are drawn. */
  markers: boolean;
  spotlight: boolean;
  invert: boolean;
  /** Where the object of the moved-object banner was, when catalogue markers are built; else null. */
  was: { ra: number; dec: number; year: number } | null;
}

export interface FrameLabelVM {
  /** Which label to draw: one frame (Blink), "B … minus A …" (Difference), two labels (Side by side), or a state. */
  kind: "one" | "diff" | "two" | "state";
  /** Blink: the frame on screen. States: when = "Building this image", "Waiting to build" or "No frames here". */
  one: FrameLabel;
  /** Side by side: the earlier (A) and later (B) frames. */
  a: FrameLabel | null;
  b: FrameLabel | null;
  /** Difference: the short dates, "21 Apr–14 May 2026" and "7–14 Nov 2025". */
  diff: { a: string; b: string } | null;
  /** "Resampled to 3.075″ per pixel; native pixel 6.15″". */
  pixels: string;
  /** The note is shown at 1440 × 900 and on a phone, not at 1280 × 720. */
  showPixels: boolean;
}

export interface PlaybackVM {
  /** Blink with at least two frames: the controls work. */
  enabled: boolean;
  /** Why they are greyed, when they are: "Frames can be flipped once the first one is built." … */
  why: string | null;
  playing: boolean;
  /** 1 to 6 changes a second. */
  speed: number;
  /** "2 per second". */
  speedLabel: string;
  /** "Frame 2 of 4", or "" without frames. Set in a 14-character fixed field. */
  counter: string;
  /** prefers-reduced-motion: Play, Speed and the shortcut list are not rendered. */
  reduced: boolean;
  /** "Reduced motion is on, so frames change only when you step or hold." when reduced. */
  reducedNote: string | null;
  /** The flip key is held (aria-pressed). */
  held: boolean;
  /** The shortcut list: 1440 × 900, Blink, a frame on screen, motion allowed. */
  shortcuts: boolean;
}

export interface PairInfoVM {
  /** "07 Nov to 14 Nov 2025": the fixed form, for the pair block. */
  aWhen: string;
  bWhen: string;
  /** "7–14 Nov 2025": the short form, for the Difference label. */
  aShort: string;
  bShort: string;
}

export interface TargetRowVM {
  id: TargetId;
  name: string;
  /** The caption; "Building this image…" while this target loads. */
  caption: string;
  saturated: boolean;
  /** The field on screen is this target's: an 8px filled mark, aria-current="true". */
  current: boolean;
  /** False when the row cannot open here; `unavailable` says why, on screen. */
  available: boolean;
  unavailable: string | null;
  loading: boolean;
}

export interface OptionVM<T> {
  id: T;
  label: string;
  /** Second line (bands): "0.74–1.12 µm". */
  meta: string | null;
  checked: boolean;
  /** aria-disabled, with the reason in the group's note. */
  disabled: boolean;
}

export interface SearchVM {
  /** The entry as typed. */
  text: string;
  /** The message line: hint, "Read as …", "Looking up the name.", or an error. Always present. */
  message: string;
  /** An error: warning icon, role="alert", aria-invalid. */
  error: boolean;
  /** Resolving: input read-only, the button reads "Searching…" with aria-busy. */
  busy: boolean;
  /** Off while a recorded field stands in for an unreachable archive. */
  disabled: boolean;
  /** "Search" or "Searching…". */
  button: string;
}

export interface NoticesVM {
  /** "The archive is not responding. Showing the recorded field instead." with Try again. */
  archive: boolean;
  /** The moved-object banner (only when features.movedBanner). */
  mover: { sentence: string; canJump: boolean } | null;
  /** Every caveat of the field, one sentence each, by date. Empty when none or no field. */
  caveats: string[];
}

export interface Handlers {
  // Search and places
  setQuery(text: string): void;
  submitSearch(): void;
  openTarget(id: TargetId): void;
  /** Try again: the archive notice, the busy state, a failure. */
  retry(): void;
  /** "Go to where it is now". */
  jump(): void;

  // Playback (all picture changes pass the 6-per-second gate)
  step(delta: -1 | 1): void;
  togglePlay(): void;
  setSpeed(speed: number): void;
  pickFrame(index: number): void;
  flipDown(): void;
  flipUp(): void;
  /** Spread onto the flip key (Playback at 1280, FlipDock on a phone): pointer, blur, Space and Enter held, no long-press menu. */
  flipKey: {
    onPointerDown(event: PointerEvent<HTMLElement>): void;
    onPointerUp(event: PointerEvent<HTMLElement>): void;
    onPointerLeave(event: PointerEvent<HTMLElement>): void;
    onPointerCancel(event: PointerEvent<HTMLElement>): void;
    onBlur(event: FocusEvent<HTMLElement>): void;
    onKeyDown(event: KeyboardEvent<HTMLElement>): void;
    onKeyUp(event: KeyboardEvent<HTMLElement>): void;
    onContextMenu(event: MouseEvent<HTMLElement>): void;
  };

  // Image
  /** A click or a tap on the image: the ring moves there (offset from the centre pixel). */
  setRing(offset: Offset): void;
  /** onKeyDown of the image frame: arrows move the pixel cursor (Shift: ten), Enter moves the ring there. */
  frameKeyDown(event: KeyboardEvent<HTMLElement>): void;
  clearCursor(): void;
  toggleSpotlight(): void;
  /** "Builds this field again with the ring at its centre." */
  recentre(): void;

  // View
  setView(view: ViewId): void;
  setBand(band: BandId): void;
  setFov(fov: Fov): void;
  setContrast(step: number): void;
  setInvert(on: boolean): void;
  setMarkers(on: boolean): void;
  copyLink(): void;

  /** Ref callback for the phone and rail column: its width sizes the square. Comparator uses it. */
  measureColumn(element: HTMLElement | null): void;
}

export interface ViewModel {
  /** The raw state. Read it to derive what is not listed here. */
  state: ViewState;
  /** The reducer's dispatch (model.ts Action). Synchronous: state is current right after. */
  dispatch(action: Action): void;
  /** Sets state fields directly, unchecked. For lanes that need a field no action covers. */
  patch(patch: Partial<ViewState>): void;
  features: Readonly<Features>;

  layout: Layout;
  /** Square, scale and plate for one frame, a pair and the spotlight; the scale bar. */
  geometry: Geometry;
  reducedMotion: boolean;
  engine: EngineState;

  /** The field on screen, or null. */
  field: FieldVM | null;
  image: ImageVM;

  /** Header: "Recorded field" (dashed chip), "Live data", or no chip without an image. */
  chip: "recorded" | "live" | null;
  /** Copy link: "", "Link copied", or "Could not copy. Select the address bar instead.". */
  copyStatus: string;
  /** Title strip (phone and rail): "WISE 0855" / "Sky position" / "No position yet", then the position line. */
  title: { title: string; line: string };

  search: SearchVM;
  notices: NoticesVM;
  playback: PlaybackVM;
  /** Side by side and Difference: the pair's dates. */
  pairInfo: PairInfoVM | null;

  timeline: {
    rows: TimelineRow[];
    /** "Partial: a different mix of wavelengths. Thin: fewer than 8 exposures." or "". */
    key: string;
    /** "5 Oct 2026" for the chip "Newest SPHEREx image: …": the newest exposure the engine has read; null when no engine answers. */
    newest: string | null;
  };
  targets: TargetRowVM[];
  /** At 1280 and 1440, with no field on screen, the target list takes the timeline's place. */
  targetsInRail: boolean;

  frameLabel: FrameLabelVM;
  /** The readout at the pixel cursor, else at the ring (Handoff-behaviour, Pointer and touch). */
  readout: Readout;
  /** The readout at any pixel: for the pixel under the pointer, kept in the image lane. */
  readoutAt(offset: Offset): Readout;
  ringBar: {
    /** A frame is on screen: the buttons show. Without one the row keeps its 44px and holds nothing. */
    show: boolean;
    /** Ring away from the centre: Recentre appears (never greyed). */
    canRecentre: boolean;
    spotlight: boolean;
  };
  legend: {
    /** "Your position": the ring is drawn. */
    position: boolean;
    /** "Where it was in 2010": only with catalogue markers. */
    was: boolean;
    /** "No data": any frame of the sequence has a hatched pixel. */
    noData: boolean;
    /** The three channels: only with three-colour. */
    rgb: boolean;
  };

  /** The view switch: only built views are listed. With Blink alone, the group is not rendered. */
  views: OptionVM<ViewId>[];
  /** "The other views open once a frame is on screen." or why a view is greyed; else null. */
  viewNote: string | null;
  /** The band options: only built bands are listed (8 without three-colour: Cold objects spans two cells). */
  bands: OptionVM<BandId>[];
  /** "D2 is greyed: no D2 image covers this position yet." or null. */
  bandNote: string | null;
  /** The band the wavelength rule lights, and its text alternative. */
  rule: { band: BandId; label: string };
  fovs: OptionVM<Fov>[];
  /** Why sizes are greyed, or null. */
  fovNote: string | null;
  display: {
    contrast: number;
    invert: boolean;
    markers: boolean;
    /** No frame on screen: the controls are greyed with the note below. */
    disabled: boolean;
    /** "Display controls are off until a frame is on screen." or null. */
    note: string | null;
  };
  /** From the manifest; null without a field. While building, `loadingLine` says "Reading 120 of 258". */
  provenance: Provenance | null;
  loadingLine: string | null;

  /** Polite announcement of the frame after a step or a flip, never during play. */
  announcement: string;
  handlers: Handlers;

  /** Three-colour, catalogue markers, Then and now and the spectrum (extras/types.ts). */
  extras: ExtrasVM;
}
