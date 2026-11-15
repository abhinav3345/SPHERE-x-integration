/**
 * What the image column draws, derived from the ViewModel alone (CONTRACT.md: data only from vm).
 * Pure: the blocks turn this into canvases, SVG and words.
 *
 * - Blink: one square, the frame on screen.
 * - Side by side: frames A (earlier) and B (later) of the pair.
 * - Difference: later minus earlier, in units of its noise.
 * - Then and now: the older survey's image (its own scale, dashed frame) and the SPHEREx stack
 *   (its own scale), from vm.extras.thenAndNow.
 * Every frame of a sequence is drawn with one scale (vm.field.displayLimits, or the channel's own
 * pooled limits in three-colour); Contrast acts through those limits and Invert on every frame.
 */

import { skyToPixel } from "../../player/grid";
import type { Limits } from "../../player/render";
import { cropCentredOn, type PlateCrop } from "../../player/screen";
import type { MarkerVM, RgbChannelVM } from "../extras/types";
import type { Fit } from "../geometry";
import { displayLimits, type Offset } from "../model";
import type { ViewModel } from "../vm";
import type { Picture } from "./picture";

export interface SquareModel {
  id: "one" | "a" | "b";
  /** What to paint; null leaves the plate empty (its data has not arrived). */
  picture: Picture | null;
  /**
   * Whose catalogue positions are drawn here: a frame of the sequence; "stack" for one image of
   * every visit (Then and now), where a moving source is its whole track; null: none.
   */
  markerFrame: number | "stack" | null;
  /** Another survey's image: the dashed outline. */
  survey: boolean;
  /** Accessible name of the square. */
  aria: string;
  /** A sentence shown in the square instead of a picture, or null. */
  note: string | null;
}

/** "Greyed frames cannot be subtracted." (Handoff-copy, section 6): the pair has no difference. */
export const NO_DIFFERENCE = "Greyed frames cannot be subtracted.";

// The Contrast step applied to a channel's or a survey's own limits: memoised so that the same
// limits keep one identity (the canvas repaints only when what it shows changes).
const contrastCache = new WeakMap<Limits, Map<number, Limits | null>>();
export function withContrast(limits: Limits | null, contrast: number): Limits | null {
  if (!limits) return null;
  let byStep = contrastCache.get(limits);
  if (!byStep) {
    byStep = new Map();
    contrastCache.set(limits, byStep);
  }
  if (!byStep.has(contrast)) byStep.set(contrast, displayLimits(limits, contrast));
  return byStep.get(contrast) ?? null;
}

/** The three-colour channels of every frame, when they are here and match the sequence. */
export function rgbFrames(
  vm: ViewModel,
): Array<{ r: RgbChannelVM; g: RgbChannelVM; b: RgbChannelVM }> | null {
  const frames = vm.extras.threeColour.frames;
  if (!vm.features.threeColour || !vm.field || !frames) return null;
  return frames.length === vm.field.sequence.length ? frames : null;
}

/** Frame `index` of the sequence: from its three channels when they are here, else grey. */
export function framePicture(vm: ViewModel, index: number): Picture | null {
  const field = vm.field;
  const frame = field?.sequence[index];
  if (!field || !frame) return null;
  const invert = vm.image.invert;
  const rgb = rgbFrames(vm)?.[index];
  if (rgb) {
    const contrast = vm.state.contrast;
    return {
      kind: "rgb",
      r: rgb.r.data,
      g: rgb.g.data,
      b: rgb.b.data,
      limits: {
        r: withContrast(rgb.r.limits, contrast),
        g: withContrast(rgb.g.limits, contrast),
        b: withContrast(rgb.b.limits, contrast),
      },
      invert,
    };
  }
  return { kind: "grey", data: frame.frame.data, limits: field.displayLimits, invert };
}

/** True for the views that show two squares. */
export function isTwoUp(vm: ViewModel): boolean {
  const view = vm.field?.view;
  return vm.image.state === "image" && (view === "side" || view === "then");
}

/** The squares on screen, in reading order. Empty when no frame is on screen. */
export function squaresOf(vm: ViewModel): SquareModel[] {
  const field = vm.field;
  if (vm.image.state !== "image" || !field) return [];
  const { pair } = field;
  const base = { survey: false, note: null };
  if (field.view === "side") {
    return [
      {
        ...base,
        id: "a",
        picture: framePicture(vm, pair.a),
        markerFrame: pair.a,
        aria: vm.image.pairAria?.a ?? vm.image.aria,
      },
      {
        ...base,
        id: "b",
        picture: framePicture(vm, pair.b),
        markerFrame: pair.b,
        aria: vm.image.pairAria?.b ?? vm.image.aria,
      },
    ];
  }
  if (field.view === "then") {
    const then = vm.extras.thenAndNow;
    const contrast = vm.state.contrast;
    const invert = vm.image.invert;
    const older = then.status === "ready" ? then.older : null;
    const sphx = then.sphx;
    return [
      {
        id: "a",
        survey: true,
        picture: older
          ? {
              kind: "grey",
              data: older.data,
              limits: withContrast(older.limits, contrast),
              invert,
            }
          : null,
        markerFrame: null,
        aria: older
          ? `Image from another survey: ${older.title}`
          : "Image from another survey. None is shown.",
        note: then.status === "none" ? then.note : null,
      },
      {
        ...base,
        id: "b",
        picture: sphx
          ? { kind: "grey", data: sphx.data, limits: withContrast(sphx.limits, contrast), invert }
          : null,
        // The stack spans every visit: a moving source is drawn as its track, not at one visit.
        markerFrame: "stack",
        aria: sphx ? `SPHEREx frame, ${sphx.dates}` : vm.image.aria,
      },
    ];
  }
  if (field.view === "difference") {
    const difference = field.difference;
    return [
      {
        ...base,
        id: "one",
        picture: difference
          ? { kind: "sigma", data: difference.data, sigma: difference.sigma }
          : null,
        markerFrame: pair.b,
        aria: vm.image.aria,
        note: difference ? null : NO_DIFFERENCE,
      },
    ];
  }
  return [
    {
      ...base,
      id: "one",
      picture: framePicture(vm, pair.shown),
      markerFrame: pair.shown,
      aria: vm.image.aria,
    },
  ];
}

/** The fit in use: one frame or a pair, at the frame's scale or the spotlight's. */
export function fitInUse(vm: ViewModel): Fit {
  const g = vm.geometry;
  const spot = vm.image.spotlight;
  if (isTwoUp(vm)) return spot ? g.spotTwo : g.two;
  return spot ? g.spot : g.one;
}

/** Image pixels along a side of the field on screen. */
export function imageSize(vm: ViewModel): { nx: number; ny: number; cx: number; cy: number } {
  const grid = vm.field?.manifest.grid;
  if (grid) return { nx: grid.nx, ny: grid.ny, cx: grid.cx, cy: grid.cy };
  const n = vm.geometry.imagePx;
  return { nx: n, ny: n, cx: Math.floor(n / 2), cy: Math.floor(n / 2) };
}

/** What a plate shows: the whole frame, or the spotlight's crop centred on the ring. */
export function cropOf(vm: ViewModel, fit: Fit): PlateCrop {
  const { nx, cx, cy } = imageSize(vm);
  if (!vm.image.spotlight) return { x0: 0, y0: 0, size: nx, scale: fit.scale };
  return cropCentredOn(cx + vm.image.ring.dx, cy + vm.image.ring.dy, fit.imagePx, fit.scale);
}

/** An offset from the centre pixel as image pixel coordinates. */
export function pixelOf(vm: ViewModel, offset: Offset): { x: number; y: number } {
  const { cx, cy } = imageSize(vm);
  return { x: cx + offset.dx, y: cy + offset.dy };
}

/** Catalogue marks are drawn: built, switched on, and not hidden by the reader. */
export function marksOn(vm: ViewModel): boolean {
  return (
    vm.features.catalogueMarkers &&
    vm.image.markers &&
    vm.image.state === "image" &&
    vm.extras.markers.status !== "off"
  );
}

/** Where the catalogue says the object was (image pixels) with its year, or null. */
export function wasOf(vm: ViewModel): { x: number; y: number; year: number } | null {
  if (!marksOn(vm) || !vm.field) return null;
  const was = vm.extras.markers.was;
  if (was) return was;
  const asked = vm.image.was;
  if (!asked) return null;
  const at = skyToPixel(vm.field.grid, asked.ra, asked.dec);
  const { nx, ny } = imageSize(vm);
  const inside = at.x >= -0.5 && at.y >= -0.5 && at.x <= nx - 0.5 && at.y <= ny - 0.5;
  return inside ? { x: at.x, y: at.y, year: asked.year } : null;
}

/** Gaia and CatWISE sources to draw, or none while the catalogues are loading or unavailable. */
export function catalogueOf(vm: ViewModel): { gaia: MarkerVM[]; catwise: MarkerVM[] } {
  if (!marksOn(vm) || vm.extras.markers.status !== "ready") return { gaia: [], catwise: [] };
  return { gaia: vm.extras.markers.gaia, catwise: vm.extras.markers.catwise };
}

/** The positions of a source through the frames, oldest first, where it is inside the image. */
export function trackOf(marker: MarkerVM): Array<{ x: number; y: number }> {
  return marker.xy.filter((p): p is { x: number; y: number } => p !== null);
}

/** One catalogue source as a square draws it, in image pixels. */
export interface DrawnMarker {
  id: string;
  /** Where its mark goes, or null: not in this frame, or a mover on a stack of every visit. */
  point: { x: number; y: number } | null;
  /** The positions its predicted track passes through (two or more), or null. */
  track: Array<{ x: number; y: number }> | null;
}

/**
 * The catalogue marks of one square. On a frame: each source at that frame's date, and a mover's
 * track. On a stack of every visit (Then and now): a mover is smeared along its path there, so it
 * gets its track and no single position; a source that does not move gets its mark.
 */
export function marksOf(
  vm: ViewModel,
  square: Pick<SquareModel, "markerFrame">,
): { gaia: DrawnMarker[]; catwise: DrawnMarker[] } {
  const frame = square.markerFrame;
  if (frame === null) return { gaia: [], catwise: [] };
  const drawn = (marker: MarkerVM): DrawnMarker => {
    const path = trackOf(marker);
    const track = marker.fast && path.length >= 2 ? path : null;
    if (frame === "stack") {
      return { id: marker.id, point: track ? null : (path[path.length - 1] ?? null), track };
    }
    return { id: marker.id, point: marker.xy[frame] ?? null, track };
  };
  const { gaia, catwise } = catalogueOf(vm);
  return { gaia: gaia.map(drawn), catwise: catwise.map(drawn) };
}

// "Any pixel without data" per array, computed once per array.
const anyNaNCache = new WeakMap<Float32Array, boolean>();
function anyNoData(data: Float32Array): boolean {
  let known = anyNaNCache.get(data);
  if (known === undefined) {
    known = data.some((value) => !Number.isFinite(value));
    anyNaNCache.set(data, known);
  }
  return known;
}

function pictureHasNoData(picture: Picture | null): boolean {
  if (!picture) return false;
  if (picture.kind === "grey") return picture.limits === null || anyNoData(picture.data);
  if (picture.kind === "rgb") {
    const { limits } = picture;
    return (
      limits.r === null ||
      limits.g === null ||
      limits.b === null ||
      anyNoData(picture.r) ||
      anyNoData(picture.g) ||
      anyNoData(picture.b)
    );
  }
  return !(Number.isFinite(picture.sigma) && picture.sigma > 0) || anyNoData(picture.data);
}

export interface LegendModel {
  /** "Your position": the ring is drawn. */
  position: boolean;
  /** "Where it was in {year}": the dashed square is drawn. */
  was: number | null;
  /** The Gaia DR3 overlay is on: its crosses can be on screen (see legendOf). */
  gaia: boolean;
  /** The CatWISE overlay is on: its diamonds can be on screen (see legendOf). */
  catwise: boolean;
  /** A predicted track is drawn. */
  track: boolean;
  /** "No data": a hatched pixel can be on screen in this view, in ANY frame of the sequence. */
  noData: boolean;
  /** The three channels and their ranges, while three-colour frames are drawn. */
  rgb: { r: string; g: string; b: string } | null;
  /** Why the catalogue marks are missing, in the extras lane's words. */
  note: string | null;
}

/**
 * The legend line. Every item depends on the whole sequence, never on the frame on screen, so
 * the line does not change at a flip.
 *
 * Nor on where the ring is. The extras lane draws each catalogue's neighbours of the ring and
 * every mover, so which crosses and diamonds are drawn changes when the ring moves; keying only
 * those would add and drop "Gaia DR3" at a click and move the rows under the line (on a phone,
 * the ring buttons the reader taps next). So a catalogue is keyed while its overlay is on, as a
 * view's legend is while the view is on: both while both catalogues answered (the extras lane
 * leaves `note` empty then), otherwise the one whose marks are here.
 */
export function legendOf(vm: ViewModel): LegendModel {
  const empty: LegendModel = {
    position: false,
    was: null,
    gaia: false,
    catwise: false,
    track: false,
    noData: false,
    rgb: null,
    note: null,
  };
  const field = vm.field;
  if (vm.image.state !== "image" || !field) return empty;

  let noData: boolean;
  if (field.view === "difference" || field.view === "then") {
    noData = squaresOf(vm).some((square) => pictureHasNoData(square.picture));
  } else if (rgbFrames(vm)) {
    noData = field.sequence.some((f) => pictureHasNoData(framePicture(vm, f.index)));
  } else {
    noData = field.anyNoData || field.displayLimits === null;
  }

  const { gaia, catwise } = catalogueOf(vm);
  const drawn = (list: MarkerVM[]) => list.some((m) => m.xy.some((p) => p !== null));
  const markers = vm.extras.markers;
  // catalogueOf is empty unless the marks are on and ready, so this is false otherwise too.
  const bothAnswered = marksOn(vm) && markers.status === "ready" && markers.note === null;
  const rgb = rgbFrames(vm) && field.view !== "difference" && field.view !== "then";
  return {
    position: vm.image.markers,
    was: wasOf(vm)?.year ?? null,
    gaia: bothAnswered || drawn(gaia),
    catwise: bothAnswered || drawn(catwise),
    track: [...gaia, ...catwise].some((m) => m.fast && trackOf(m).length >= 2),
    noData,
    rgb: rgb ? vm.extras.threeColour.ranges : null,
    note:
      vm.features.catalogueMarkers && vm.image.markers && markers.status === "unavailable"
        ? markers.note
        : null,
  };
}
