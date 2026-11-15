/**
 * Everything the ViewModel shows, derived from the state and the environment by one pure
 * function. useComparator adds the handlers; model.test.ts checks this on the real fields.
 */

import { gridOf } from "../player/grid";
import type { Limits } from "../player/render";
import { type DifferenceFrame, differenceFrame, type Frame } from "../player/synth";
import {
  answersField,
  deriveExtras,
  type OverlaysLoad,
  type RecordedLoads,
  type SpectrumLoad,
} from "./extras/derive";
import { EMPTY_EXTRAS } from "./extras/empty";
import { FEATURES, type Features } from "./features";
import {
  countFixed,
  fixedDateRange,
  frameCounter,
  shortDate,
  shortDateRange,
  speedLabel,
} from "./format";
import { type Geometry, geometryFor, type Layout } from "./geometry";
import {
  BAND_IDS,
  BANDS,
  type BandId,
  bandBuilt,
  bandHasData,
  bandRange,
  caveatSentences,
  defaultSearchMessage,
  displayLimits,
  effectiveBand,
  FOVS,
  type FrameLabel,
  fieldOf,
  fovLabel,
  frameAriaLabel,
  frameLabels,
  imagePxFor,
  NO_READOUT,
  type Offset,
  provenanceOf,
  RECORDED_FOV,
  type Readout,
  type Resolved,
  readoutAt,
  resolve,
  ruleLabel,
  type SeqFrame,
  sequenceLimits,
  shownPlace,
  TARGETS,
  timelineKey,
  timelineRows,
  titleOf,
  VIEW_IDS,
  type ViewId,
  type ViewState,
  viewBlocked,
  viewBuilt,
} from "./model";
import type {
  BuildStepVM,
  BuildVM,
  EngineState,
  FieldVM,
  FrameLabelVM,
  FrameState,
  ImageVM,
  OptionVM,
  TargetRowVM,
  ViewModel,
} from "./vm";

/** What the page knows besides the state. */
export interface Env {
  layout: Layout;
  /** Width of the phone or rail column, CSS px (0 until measured). */
  columnWidth: number;
  dpr: number;
  reducedMotion: boolean;
  engine: EngineState;
  /** ISO date of the newest exposure the engine has read (GET /api/status), or null. */
  newest: string | null;
  /** Clock, ms: for the busy countdown. */
  now: number;
  /** The last frame announcement. */
  announcement: string;
  /** The search lane's hint for an empty field: only the forms that work in this build. */
  searchHint: string;
  /** The catalogue overlays of the field on screen, as loaded by the hook (extras). */
  overlays?: OverlaysLoad;
  /** The spectrum at the ring, as loaded by the hook (extras). */
  spectrum?: SpectrumLoad;
  /** The recorded answers of the field on screen, as loaded by the hook (extras); absent: none. */
  recorded?: RecordedLoads;
}

export type Derived = Omit<ViewModel, "state" | "dispatch" | "patch" | "handlers">;

/** The view switch's words. (A function: an object with a "then" key reads as a promise to linters.) */
function viewLabel(view: ViewId): string {
  switch (view) {
    case "blink":
      return "Blink";
    case "side":
      return "Side by side";
    case "difference":
      return "Difference";
    case "then":
      return "Then and now";
  }
}

const BUILD_SENTENCE =
  "The first build takes about a minute; it is saved, so next time this position opens at once.";

// Memoised so that blocks can key their own memos on identity.
const differenceCache = new WeakMap<Frame, WeakMap<Frame, DifferenceFrame | null>>();
function laterMinusEarlier(later: Frame, earlier: Frame): DifferenceFrame | null {
  let byEarlier = differenceCache.get(later);
  if (!byEarlier) {
    byEarlier = new WeakMap();
    differenceCache.set(later, byEarlier);
  }
  if (!byEarlier.has(earlier)) byEarlier.set(earlier, differenceFrame(later, earlier));
  return byEarlier.get(earlier) ?? null;
}

const displayCache = new WeakMap<Limits, Map<number, Limits | null>>();
function shownLimits(limits: Limits | null, contrast: number): Limits | null {
  if (!limits) return null;
  let byStep = displayCache.get(limits);
  if (!byStep) {
    byStep = new Map();
    displayCache.set(limits, byStep);
  }
  if (!byStep.has(contrast)) byStep.set(contrast, displayLimits(limits, contrast));
  return byStep.get(contrast) ?? null;
}

const labelCache = new WeakMap<readonly SeqFrame[], FrameLabel[]>();

function frameStateOf(state: ViewState, r: Resolved | null): FrameState {
  switch (state.load.phase) {
    case "idle":
      return "none";
    case "loading":
      return state.load.building ? "building" : "loading";
    case "ready":
      return r ? "image" : "empty";
    case "empty":
      return "empty";
    case "busy":
      return "busy";
    case "failed":
      return "failed";
  }
}

function buildOf(state: ViewState): BuildVM | null {
  if (state.load.phase !== "loading" || !state.load.building) return null;
  const progress = state.load.progress;
  const stage = progress?.stage ?? "discover";
  const counted =
    progress !== null && progress.done !== null && progress.total !== null && progress.total > 0;
  const of = (done: number, total: number) => `${done} of ${total}`;
  const step = (label: string, value: string | null, s: BuildStepVM["state"]): BuildStepVM => ({
    label,
    value,
    state: s,
  });
  if (stage === "fetch") {
    return {
      steps: [
        step("Finding exposures", null, "done"),
        step(
          "Reading exposures",
          counted ? of(progress.done ?? 0, progress.total ?? 0) : null,
          "doing",
        ),
        step("Stacking", null, "todo"),
      ],
      bar: {
        now: counted ? (progress.done ?? 0) : 0,
        max: counted ? (progress.total ?? 1) : 1,
        label: "Reading exposures",
      },
      sentence: BUILD_SENTENCE,
    };
  }
  if (stage === "stack") {
    const total = counted ? (progress.total ?? 0) : 0;
    return {
      steps: [
        step("Finding exposures", null, "done"),
        step("Reading exposures", counted ? of(total, total) : null, "done"),
        step("Stacking", counted ? of(progress.done ?? 0, total) : null, "doing"),
      ],
      bar: { now: counted ? (progress.done ?? 0) : 0, max: counted ? total : 1, label: "Stacking" },
      sentence: BUILD_SENTENCE,
    };
  }
  if (stage === "frames") {
    return {
      steps: [
        step("Finding exposures", null, "done"),
        step("Reading exposures", null, "done"),
        step("Stacking", null, "done"),
      ],
      bar: { now: 1, max: 1, label: "Stacking" },
      sentence: BUILD_SENTENCE,
    };
  }
  return {
    steps: [
      step("Finding exposures", null, "doing"),
      step("Reading exposures", null, "todo"),
      step("Stacking", null, "todo"),
    ],
    bar: { now: 0, max: 1, label: "Reading exposures" },
    sentence: BUILD_SENTENCE,
  };
}

/** Exposures found, once the engine has counted them: for "Building this image … 258 exposures". */
function foundSoFar(state: ViewState): number | null {
  if (state.load.phase !== "loading" || !state.load.building) return null;
  const progress = state.load.progress;
  if (!progress || (progress.stage !== "fetch" && progress.stage !== "stack")) return null;
  return progress.total !== null && progress.total > 0 ? progress.total : null;
}

function stateLabel(state: ViewState, frameState: FrameState, band: BandId): FrameLabel {
  const blank: FrameLabel = {
    when: "No frames here",
    range: " ",
    count: "",
    partial: false,
    thin: false,
    saturated: false,
    hasData: false,
  };
  if (frameState === "building" || frameState === "loading") {
    const found = foundSoFar(state);
    return {
      ...blank,
      when: frameState === "building" ? "Building this image" : " ",
      range: frameState === "building" ? bandRange(band) : " ",
      count: found === null ? "" : countFixed(found),
    };
  }
  if (frameState === "busy") return { ...blank, when: "Waiting to build" };
  return blank;
}

function emptyReadout(view: ViewId): Readout {
  if (view === "side") return { ...NO_READOUT, value: "A —   B —   MJy/sr" };
  if (view === "difference") return { ...NO_READOUT, value: "— σ" };
  if (view === "then") return { ...NO_READOUT, value: "" };
  return NO_READOUT;
}

function joinBands(ids: readonly BandId[]): string {
  const names = ids.map((id) => BANDS[id].spoken);
  if (names.length === 1) return names[0];
  return `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}

export function deriveView(
  state: ViewState,
  env: Env,
  features: Readonly<Features> = FEATURES,
): Derived {
  const r = resolve(state, features);
  const field = fieldOf(state);
  const frameState = frameStateOf(state, r);
  const onScreen = frameState === "image" && r !== null;
  const phoneLike = env.layout === "phone" || env.layout === "rail";
  const band = effectiveBand(state, features);
  const view: ViewId = r ? r.view : "blink";
  const manifest = field?.manifest ?? null;

  const geometry: Geometry = geometryFor(
    env.layout,
    env.columnWidth,
    env.dpr,
    manifest?.grid.nx ?? imagePxFor(state.fov),
    manifest?.grid.pixscale_arcsec,
  );

  // The field on screen -------------------------------------------------------------------------
  let fieldVM: FieldVM | null = null;
  if (r && field) {
    const limits = sequenceLimits(r.sequence);
    let labels = labelCache.get(r.sequence);
    if (!labels) {
      labels = frameLabels(r.sequence, field.manifest);
      labelCache.set(r.sequence, labels);
    }
    const a = r.sequence[r.pair.a];
    const b = r.sequence[r.pair.b];
    fieldVM = {
      manifest: field.manifest,
      synth: field.synth,
      grid: gridOf(field.manifest),
      source: field.source,
      recorded: field.recorded,
      standIn: state.load.phase === "ready" && state.load.fallback,
      band: r.band,
      view: r.view,
      sequence: r.sequence,
      pair: r.pair,
      shown: r.sequence[r.pair.shown],
      limits,
      displayLimits: shownLimits(limits, state.contrast),
      difference: r.view === "difference" ? laterMinusEarlier(b.frame, a.frame) : null,
      labels,
      anyNoData: r.sequence.some((f) => f.hasNoData),
    };
  }
  const standIn = fieldVM?.standIn ?? false;

  // Image ---------------------------------------------------------------------------------------
  const busy =
    state.load.phase === "busy"
      ? (() => {
          const secondsLeft = Math.max(0, Math.ceil((state.load.retryAt - env.now) / 1000));
          return { secondsLeft, canRetry: secondsLeft === 0 };
        })()
      : null;
  const mover = features.movedBanner ? state.mover : null;
  const extras = deriveExtras({
    state,
    features,
    field:
      fieldVM && onScreen
        ? {
            manifest: fieldVM.manifest,
            synth: fieldVM.synth,
            grid: fieldVM.grid,
            band: fieldVM.band,
            sequence: fieldVM.sequence,
            // Recorded answers: only for a recorded field opened for itself, never a stand-in.
            recorded: answersField(state),
          }
        : null,
    source: fieldVM?.source ?? null,
    was:
      features.catalogueMarkers && mover
        ? { ra: mover.from.ra, dec: mover.from.dec, year: mover.hint.wasHereYear }
        : null,
    overlays: env.overlays ?? { phase: "idle" },
    spectrum: env.spectrum ?? { phase: "idle" },
    recorded: env.recorded,
  });
  const then = extras.thenAndNow;
  const image: ImageVM = {
    state: frameState,
    aria: r && onScreen ? frameAriaLabel(r, phoneLike) : "Sky image. No frame is on screen.",
    pairAria:
      r && onScreen && r.view === "then" && then.older
        ? {
            // Handoff-copy, section 14: "Image from another survey: WISE W2, 2010".
            a: `Image from another survey: ${then.older.title}`,
            b: then.sphx
              ? `SPHEREx frame, ${then.sphx.title.replace(/^SPHEREx /, "")}, ${then.sphx.dates}`
              : "SPHEREx frame. No SPHEREx image of this band covers the field yet.",
          }
        : r && onScreen && (r.view === "side" || r.view === "then")
          ? {
              a: `Frame A, ${fixedDateRange(r.sequence[r.pair.a].dateStart, r.sequence[r.pair.a].dateEnd)}`,
              b: `Frame B, ${fixedDateRange(r.sequence[r.pair.b].dateStart, r.sequence[r.pair.b].dateEnd)}`,
            }
          : null,
    build: buildOf(state),
    busy,
    failure: state.load.phase === "failed" ? state.load.message : null,
    ring: state.ring,
    cursor: state.cursor,
    markers: state.markers,
    spotlight: state.spotlight && features.spotlight && onScreen,
    invert: state.invert,
    was:
      features.catalogueMarkers && mover
        ? { ra: mover.from.ra, dec: mover.from.dec, year: mover.hint.wasHereYear }
        : null,
  };

  // Header, title, search, notices --------------------------------------------------------------
  const chip: Derived["chip"] = onScreen && field ? (field.recorded ? "recorded" : "live") : null;
  const copyStatus =
    state.copy === "copied"
      ? "Link copied"
      : state.copy === "failed"
        ? "Could not copy. Select the address bar instead."
        : "";
  const searchMessage = standIn
    ? "Search is off while the recorded field is shown."
    : (state.search.message ?? defaultSearchMessage(state, env.searchHint));
  const caveats = onScreen && manifest && r ? caveatSentences(manifest, r.sequence) : [];

  // Playback ------------------------------------------------------------------------------------
  const count = r?.sequence.length ?? 0;
  let why: string | null = null;
  if (frameState === "building" || frameState === "loading") {
    why = "Frames can be flipped once the first one is built.";
  } else if (!onScreen) why = "No frame is on screen, so there is nothing to blink yet.";
  else if (count < 2)
    why = "Only one frame covers this position, so there is nothing to blink yet.";

  // Frame label -----------------------------------------------------------------------------------
  const labels = fieldVM?.labels ?? [];
  const pixscale = manifest?.grid.pixscale_arcsec ?? 3.075;
  const frameLabel: FrameLabelVM = {
    kind:
      !r || !onScreen ? "state" : view === "difference" ? "diff" : view === "blink" ? "one" : "two",
    one: r && onScreen ? labels[r.pair.shown] : stateLabel(state, frameState, band),
    a: r && onScreen && view !== "blink" && view !== "difference" ? labels[r.pair.a] : null,
    b: r && onScreen && view !== "blink" && view !== "difference" ? labels[r.pair.b] : null,
    diff:
      r && onScreen && view === "difference"
        ? {
            a: shortDateRange(r.sequence[r.pair.a].dateStart, r.sequence[r.pair.a].dateEnd),
            b: shortDateRange(r.sequence[r.pair.b].dateStart, r.sequence[r.pair.b].dateEnd),
          }
        : null,
    pixels: `Resampled to ${pixscale}″ per pixel; native pixel ${pixscale * 2}″`,
    showPixels: env.layout !== "three",
  };

  // Targets ---------------------------------------------------------------------------------------
  const shown = shownPlace(state);
  const targets: TargetRowVM[] = TARGETS.map((target) => {
    const loading =
      (state.search.busy && state.search.target === target.id) ||
      (state.request?.target === target.id &&
        (state.load.phase === "loading" || state.load.phase === "busy"));
    const current =
      onScreen &&
      ((target.recorded !== null &&
        shown.kind === "recorded" &&
        shown.target === target.recorded) ||
        (!standIn && state.request?.target === target.id));
    // A target without a recorded field opens a build at its catalogue position moved to the
    // frames' epoch (model.ts targetPosition): it needs the engine, never a name lookup.
    let unavailable: string | null = null;
    if (target.recorded === null) {
      if (env.engine === "down") {
        unavailable = "Not available right now: the archive is not responding.";
      } else if (target.astrometry === null && !features.nameSearch) {
        unavailable = "Not available here yet: names cannot be looked up.";
      }
    }
    return {
      id: target.id,
      name: target.name,
      caption: loading ? "Building this image…" : target.caption,
      saturated: target.saturated,
      current,
      available: unavailable === null,
      unavailable,
      loading,
    };
  });

  // View, band, field of view, display ----------------------------------------------------------
  const views: OptionVM<ViewId>[] = VIEW_IDS.filter((id) => viewBuilt(id, features)).map((id) => ({
    id,
    label: viewLabel(id),
    meta: null,
    checked: view === id,
    disabled:
      !onScreen || (manifest !== null && viewBlocked(id, r?.sequence ?? null, manifest) !== null),
  }));
  // Why a view is greyed, one line. Which band Then and now pairs with is not repeated here: the
  // pair block says it in Then and now (vm.extras.thenAndNow.note), where it applies.
  let viewNote: string | null = null;
  if (!onScreen) viewNote = "The other views open once a frame is on screen.";
  else if (manifest && r) {
    viewNote =
      views.map((option) => viewBlocked(option.id, r.sequence, manifest)).find((n) => n !== null) ??
      null;
  }

  const bands: OptionVM<BandId>[] = BAND_IDS.filter((id) => bandBuilt(id, features)).map((id) => ({
    id,
    label: BANDS[id].label,
    meta: BANDS[id].meta,
    checked: band === id,
    disabled: manifest !== null && field !== null && !bandHasData(manifest, id),
  }));
  const greyedBands = bands.filter((option) => option.disabled).map((option) => option.id);
  const bandNote =
    greyedBands.length === 0
      ? null
      : greyedBands.length === 1
        ? `${joinBands(greyedBands)} is greyed: no ${joinBands(greyedBands)} image covers this position yet.`
        : `${joinBands(greyedBands)} are greyed: no image in these bands covers this position yet.`;

  const recordedOnly = env.engine === "down" && shown.kind === "recorded";
  const fovs: OptionVM<(typeof FOVS)[number]>[] = FOVS.map((fov) => ({
    id: fov,
    label: fovLabel(fov),
    meta: null,
    // A recorded field standing in for the archive is 6′, whatever size was asked for.
    checked: (standIn ? RECORDED_FOV : state.fov) === fov,
    disabled: recordedOnly && fov !== RECORDED_FOV,
  }));

  const displayOff = !onScreen;

  // Provenance --------------------------------------------------------------------------------------
  const provenance =
    manifest && onScreen ? provenanceOf(manifest, fieldVM?.displayLimits ?? null, caveats) : null;
  let loadingLine: string | null = null;
  if (state.load.phase === "loading" && state.load.building) {
    const p = state.load.progress;
    if (p && p.stage === "fetch" && p.done !== null && p.total !== null && p.total > 0) {
      loadingLine = `Reading ${p.done} of ${p.total}`;
    }
  }

  const readoutFor = (offset: Offset): Readout =>
    r && onScreen ? readoutAt(r, offset) : emptyReadout(view);

  return {
    features,
    layout: env.layout,
    geometry,
    reducedMotion: env.reducedMotion,
    engine: env.engine,
    field: fieldVM,
    image,
    chip,
    copyStatus,
    title: titleOf(state),
    search: {
      text: state.search.text,
      message: searchMessage,
      error: !standIn && state.search.error,
      busy: state.search.busy,
      disabled: standIn,
      button: state.search.busy ? "Searching…" : "Search",
    },
    notices: {
      archive: standIn,
      mover: mover ? { sentence: mover.hint.sentence, canJump: !mover.jumped } : null,
      caveats,
    },
    playback: {
      enabled: onScreen && view === "blink" && count >= 2,
      why,
      playing: state.playing,
      speed: state.speed,
      speedLabel: speedLabel(state.speed),
      counter: r && onScreen ? frameCounter(r.pair.shown, count) : "",
      reduced: env.reducedMotion,
      reducedNote: env.reducedMotion
        ? "Reduced motion is on, so frames change only when you step or hold."
        : null,
      held: state.held,
      shortcuts: env.layout === "wide" && onScreen && view === "blink" && !env.reducedMotion,
    },
    pairInfo:
      r && onScreen && (view === "side" || view === "difference")
        ? {
            aWhen: fixedDateRange(r.sequence[r.pair.a].dateStart, r.sequence[r.pair.a].dateEnd),
            bWhen: fixedDateRange(r.sequence[r.pair.b].dateStart, r.sequence[r.pair.b].dateEnd),
            aShort: shortDateRange(r.sequence[r.pair.a].dateStart, r.sequence[r.pair.a].dateEnd),
            bShort: shortDateRange(r.sequence[r.pair.b].dateStart, r.sequence[r.pair.b].dateEnd),
          }
        : null,
    timeline: {
      rows: r && onScreen ? timelineRows(r) : [],
      key: r && onScreen ? timelineKey(r.sequence, view) : "",
      newest: env.newest ? shortDate(env.newest) : null,
    },
    targets,
    targetsInRail: (env.layout === "three" || env.layout === "wide") && !onScreen,
    frameLabel,
    readout: readoutFor(state.cursor ?? state.ring),
    readoutAt: readoutFor,
    ringBar: {
      show: onScreen,
      canRecentre: onScreen && (state.ring.dx !== 0 || state.ring.dy !== 0),
      spotlight: image.spotlight,
    },
    legend: {
      position: onScreen && state.markers,
      was: features.catalogueMarkers && onScreen && state.markers && mover !== null,
      noData: onScreen && (fieldVM?.anyNoData ?? false),
      rgb: features.threeColour && onScreen && band === "rgb",
    },
    views,
    viewNote,
    bands,
    bandNote,
    rule: { band, label: ruleLabel(band) },
    fovs,
    fovNote: recordedOnly
      ? "Only 6′ is recorded. Other sizes open when the archive responds."
      : null,
    display: {
      contrast: state.contrast,
      invert: state.invert,
      markers: state.markers,
      disabled: displayOff,
      note: displayOff ? "Display controls are off until a frame is on screen." : null,
    },
    provenance,
    loadingLine,
    announcement: env.announcement,
    extras: { ...extras, handlers: EMPTY_EXTRAS.handlers },
  };
}
