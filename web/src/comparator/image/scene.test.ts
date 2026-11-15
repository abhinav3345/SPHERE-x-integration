/**
 * What the image column draws, checked on the recorded REAL fields (public/fixtures) through the
 * same derivation the page uses, plus synthetic arrays for the painters' rules.
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { Manifest } from "../../contract";
import { decodeFloat16 } from "../../player/float16";
import { type Limits, paintGrey, type SigmaRamp } from "../../player/render";
import { FieldSynth } from "../../player/synth";
import { deriveView, type Env } from "../derive";
import type { ExtrasVM } from "../extras/types";
import { FEATURES } from "../features";
import {
  type Action,
  displayLimits,
  INITIAL_STATE,
  type LoadedField,
  type RecordedId,
  reduce,
  type ViewState,
} from "../model";
import type { Handlers, ViewModel } from "../vm";
import { hasNoData, noDataOf, paintPicture } from "./picture";
import {
  cropOf,
  fitInUse,
  framePicture,
  legendOf,
  marksOf,
  NO_DIFFERENCE,
  squaresOf,
  wasOf,
  withContrast,
} from "./scene";

const NAN = Number.NaN;
const fixturesDir = fileURLToPath(new URL("../../../public/fixtures/", import.meta.url));

function loadRecorded(name: RecordedId): LoadedField | null {
  const dir = join(fixturesDir, name);
  if (!existsSync(join(dir, "manifest.json"))) return null;
  const manifest: Manifest = JSON.parse(readFileSync(join(dir, "manifest.json"), "utf8"));
  const bytes = readFileSync(join(dir, "frames.bin"));
  const synth = new FieldSynth(manifest, decodeFloat16(new Uint8Array(bytes).buffer));
  return { manifest, synth, source: "bundled", recorded: name };
}

const wise = loadRecorded("wise0855");
const barnard = loadRecorded("barnard");
const haveFixtures = wise !== null && barnard !== null;

const ENV: Env = {
  layout: "three",
  columnWidth: 0,
  dpr: 1,
  reducedMotion: false,
  engine: "down",
  newest: null,
  now: 0,
  announcement: "",
  searchHint: "Try 133.7599 -7.2418.",
};

function opened(field: LoadedField, ...actions: Action[]): ViewState {
  const asked = reduce(INITIAL_STATE, {
    type: "go",
    place: { kind: "recorded", target: field.recorded ?? "wise0855" },
  });
  const loaded = reduce(asked, {
    type: "loaded",
    requestId: asked.request?.id ?? -1,
    field,
    fallback: false,
  });
  return actions.reduce(reduce, loaded);
}

/** The ViewModel the page would build, with extras as given and no handlers. */
function viewOf(state: ViewState, extras?: Partial<ExtrasVM>, env: Partial<Env> = {}): ViewModel {
  const derived = deriveView(state, { ...ENV, ...env }, FEATURES);
  return {
    ...derived,
    extras: { ...derived.extras, ...extras },
    state,
    dispatch: () => {},
    patch: () => {},
    handlers: {} as Handlers,
  };
}

describe.skipIf(!haveFixtures)("squares on the recorded fields", () => {
  const field = () => wise as LoadedField;

  it("Blink: one square, the frame on screen, on the sequence's one scale", () => {
    const vm = viewOf(opened(field()));
    const squares = squaresOf(vm);
    expect(squares).toHaveLength(1);
    const [one] = squares;
    expect(one.markerFrame).toBe(vm.field?.pair.shown);
    expect(one.picture).toMatchObject({ kind: "grey", invert: false });
    if (one.picture?.kind !== "grey" || !vm.field) throw new Error("grey expected");
    expect(one.picture.limits).toBe(vm.field.displayLimits);
    expect(one.picture.data).toBe(vm.field.shown.frame.data);
    expect(one.aria).toBe(vm.image.aria);
  });

  it("uses the same limits for every frame, whichever is on screen", () => {
    const first = viewOf(opened(field()));
    const stepped = viewOf(opened(field(), { type: "step", delta: -1 }));
    const a = squaresOf(first)[0].picture;
    const b = squaresOf(stepped)[0].picture;
    if (a?.kind !== "grey" || b?.kind !== "grey") throw new Error("grey expected");
    expect(a.data).not.toBe(b.data);
    expect(a.limits).toBe(b.limits);
  });

  it("applies Contrast and Invert to every frame alike", () => {
    const vm = viewOf(
      opened(field(), { type: "setContrast", contrast: 7 }, { type: "setInvert", on: true }),
    );
    const picture = squaresOf(vm)[0].picture;
    if (picture?.kind !== "grey" || !vm.field) throw new Error("grey expected");
    expect(picture.invert).toBe(true);
    expect(picture.limits).toEqual(displayLimits(vm.field.limits, 7));
    const other = framePicture(vm, 0);
    if (other?.kind !== "grey") throw new Error("grey expected");
    expect(other.limits).toBe(picture.limits);
    expect(other.invert).toBe(true);
  });

  it("Side by side: frames A and B, earlier first, with their own names", () => {
    const vm = viewOf(opened(field(), { type: "setView", view: "side" }));
    const squares = squaresOf(vm);
    expect(squares.map((s) => s.id)).toEqual(["a", "b"]);
    expect(squares.map((s) => s.markerFrame)).toEqual([vm.field?.pair.a, vm.field?.pair.b]);
    expect(squares[0].aria).toMatch(/^Frame A, /);
    expect(squares[1].aria).toMatch(/^Frame B, /);
    expect(fitInUse(vm)).toBe(vm.geometry.two);
    expect(fitInUse(vm).scale).toBe(2);
  });

  it("Difference: later minus earlier in units of its noise", () => {
    const vm = viewOf(opened(field(), { type: "setView", view: "difference" }));
    const [one] = squaresOf(vm);
    expect(vm.field?.view).toBe("difference");
    expect(one.note).toBeNull();
    expect(one.picture).toMatchObject({ kind: "sigma" });
    if (one.picture?.kind !== "sigma" || !vm.field?.difference) throw new Error("sigma expected");
    expect(one.picture.data).toBe(vm.field.difference.data);
    expect(one.picture.sigma).toBeGreaterThan(0);
    expect(NO_DIFFERENCE).toBe("Greyed frames cannot be subtracted.");
  });

  it("Spotlight: a crop of 39 pixels centred on the ring at three times the scale", () => {
    const state = opened(
      field(),
      { type: "setRing", ring: { dx: 50, dy: -3 } },
      { type: "setSpotlight", on: true },
    );
    const vm = viewOf(state);
    const fit = fitInUse(vm);
    expect(fit).toBe(vm.geometry.spot);
    expect(fit.scale).toBe(12);
    expect(cropOf(vm, fit)).toEqual({ x0: 59 + 50 - 19, y0: 59 - 3 - 19, size: 39, scale: 12 });
  });

  it("the legend keys the hatch for the whole sequence, never per frame", () => {
    const states = [
      opened(barnard as LoadedField),
      opened(barnard as LoadedField, { type: "step", delta: 1 }),
    ];
    const legends = states.map((state) => legendOf(viewOf(state)));
    expect(legends[0]).toEqual(legends[1]);
    expect(legends[0].position).toBe(true);
    expect(legends[0].rgb).toBeNull();
  });

  it("draws nothing and keys nothing without a frame", () => {
    const vm = viewOf(INITIAL_STATE);
    expect(squaresOf(vm)).toEqual([]);
    expect(legendOf(vm)).toMatchObject({ position: false, noData: false, was: null });
  });
});

describe.skipIf(!haveFixtures)("the extras on a recorded field", () => {
  const field = () => wise as LoadedField;
  const n = 119 * 119;
  const channel = (value: number, limits: Limits | null) => ({
    data: new Float32Array(n).fill(value),
    limits,
  });
  const limits: Limits = { sigmaRef: 1, vmin: -2, vmax: 10, soften: 3 };

  it("draws three-colour frames from their channels, with Contrast on each channel's own limits", () => {
    const state = opened(field(), { type: "setContrast", contrast: 6 });
    const count = state.load.phase === "ready" ? 4 : 0;
    const frames = Array.from({ length: count }, () => ({
      r: channel(1, limits),
      g: channel(2, limits),
      b: channel(3, null),
    }));
    const vm = viewOf(state, {
      threeColour: {
        frames,
        ranges: { r: "3.8 to 5.0 µm", g: "1.6 to 3.8 µm", b: "0.74 to 1.65 µm" },
      },
    });
    const picture = squaresOf(vm)[0].picture;
    if (picture?.kind !== "rgb") throw new Error("rgb expected");
    expect(picture.limits.r).toEqual(displayLimits(limits, 6));
    expect(picture.limits.r).toBe(withContrast(limits, 6));
    expect(picture.limits.b).toBeNull();
    // Blue has no scale, so every pixel is hatched and "No data" is keyed.
    expect(hasNoData(picture)).toBe(true);
    const legend = legendOf(vm);
    expect(legend.noData).toBe(true);
    expect(legend.rgb).toEqual({ r: "3.8 to 5.0 µm", g: "1.6 to 3.8 µm", b: "0.74 to 1.65 µm" });
  });

  it("ignores three-colour frames that do not match the sequence", () => {
    const vm = viewOf(opened(field()), {
      threeColour: {
        frames: [{ r: channel(1, limits), g: channel(1, limits), b: channel(1, limits) }],
        ranges: { r: "", g: "", b: "" },
      },
    });
    expect(squaresOf(vm)[0].picture?.kind).toBe("grey");
    expect(legendOf(vm).rgb).toBeNull();
  });

  it("draws catalogue marks only when ready, and keys them for the whole sequence", () => {
    const markers = {
      status: "ready" as const,
      note: null,
      gaia: [
        { id: "g1", label: null, xy: [{ x: 10, y: 10 }, null, null, { x: 12, y: 10 }], fast: true },
      ],
      catwise: [],
      was: { x: 18, y: 62, year: 2010 },
    };
    const vm = viewOf(opened(field()), { markers });
    const legend = legendOf(vm);
    // Both catalogues answered (no note): both overlays are on and keyed, though no CatWISE
    // diamond is drawn near the ring right now.
    expect(legend).toMatchObject({ gaia: true, catwise: true, track: true, was: 2010 });
    expect(wasOf(vm)).toEqual({ x: 18, y: 62, year: 2010 });
    const hidden = viewOf(opened(field(), { type: "setMarkers", on: false }), { markers });
    expect(legendOf(hidden)).toMatchObject({
      position: false,
      gaia: false,
      catwise: false,
      was: null,
    });
    const loading = viewOf(opened(field()), { markers: { ...markers, status: "loading" } });
    expect(legendOf(loading)).toMatchObject({ gaia: false, catwise: false, track: false });
    const unavailable = viewOf(opened(field()), {
      markers: { ...markers, status: "unavailable", note: "The catalogues could not be reached." },
    });
    expect(legendOf(unavailable)).toMatchObject({
      gaia: false,
      catwise: false,
      note: "The catalogues could not be reached.",
    });
  });

  it("keeps the legend line when the ring moves and the marks around it change", () => {
    // The extras lane draws each catalogue's neighbours of the ring and every mover: after a
    // click the list can hold no Gaia star at all. The line must not drop "Gaia DR3" for that
    // (it would move the rows under it): the key says which overlay is on.
    const mover = {
      id: "c1",
      label: "8.0″/yr",
      xy: [{ x: 60, y: 60 }, { x: 59, y: 60 }, null, { x: 57, y: 60 }],
      fast: true,
    };
    const star = { id: "g1", label: null, xy: [{ x: 61, y: 58 }, null, null, null], fast: false };
    const near = viewOf(opened(field()), {
      markers: { status: "ready", note: null, gaia: [star], catwise: [mover], was: null },
    });
    const away = viewOf(opened(field(), { type: "setRing", ring: { dx: 40, dy: -40 } }), {
      markers: { status: "ready", note: null, gaia: [], catwise: [mover], was: null },
    });
    expect(legendOf(away)).toEqual(legendOf(near));
    expect(legendOf(away)).toMatchObject({ gaia: true, catwise: true, track: true });

    // One catalogue could not be reached: only the other is keyed, never a mark that cannot be
    // drawn.
    const gaiaDown = viewOf(opened(field()), {
      markers: {
        status: "ready",
        note: "Gaia DR3 could not be reached: only CatWISE sources are marked.",
        gaia: [],
        catwise: [mover],
        was: null,
      },
    });
    expect(legendOf(gaiaDown)).toMatchObject({ gaia: false, catwise: true });
  });

  it("Then and now on the recorded fields: the older image and the stack, each on its own scale", () => {
    // Pipeline 0.3.0 recorded both fields with their older-survey images, so the model opens the
    // view on them (Barnard's Star: All pairs WISE W1 with D4; WISE 0855: Cold objects with W2).
    for (const recorded of [wise, barnard] as LoadedField[]) {
      const vm = viewOf(
        opened(recorded, { type: "setView", view: "then" }, { type: "setContrast", contrast: 6 }),
      );
      expect(vm.field?.view).toBe("then");
      const then = vm.extras.thenAndNow;
      if (!then.older || !then.sphx) throw new Error("Then and now is not ready");
      const [a, b] = squaresOf(vm);
      expect(a).toMatchObject({ id: "a", survey: true, markerFrame: null, note: null });
      expect(a.aria).toBe(`Image from another survey: ${then.older.title}`);
      expect(b).toMatchObject({ id: "b", survey: false, markerFrame: "stack", note: null });
      if (a.picture?.kind !== "grey" || b.picture?.kind !== "grey")
        throw new Error("grey expected");
      expect(a.picture.data).toBe(then.older.data);
      expect(a.picture.limits).toBe(withContrast(then.older.limits, 6));
      expect(b.picture.data).toBe(then.sphx.data);
      expect(b.picture.limits).toBe(withContrast(then.sphx.limits, 6));
      expect(a.picture.limits).not.toEqual(b.picture.limits);
      expect(a.picture.limits).not.toEqual(vm.field?.displayLimits);
      expect(fitInUse(vm)).toBe(vm.geometry.two);
      // Every pixel of these older images and stacks has a value: no hatch to key.
      expect(legendOf(vm).noData).toBe(false);
    }
  });

  // Then and now models made by hand, the view set by hand: what the two squares draw for any
  // model the extras lane can give, the one without an older image included.
  function thenView(thenAndNow: ExtrasVM["thenAndNow"], contrast = 5): ViewModel {
    const vm = viewOf(opened(field(), { type: "setContrast", contrast }), { thenAndNow });
    if (!vm.field) throw new Error("field expected");
    return {
      ...vm,
      field: { ...vm.field, view: "then" },
    };
  }

  it("Then and now: each survey on its own scale, with Contrast on each", () => {
    const older = channel(1, limits);
    const sphx = channel(2, { ...limits, vmax: 4 });
    const vm = thenView(
      {
        status: "ready",
        note: null,
        older: { ...older, title: "WISE W2, 2010", dates: "May to Nov 2010" },
        sphx: {
          ...sphx,
          title: "SPHEREx 4.0–5.0 µm",
          exposures: "82 exposures",
          dates: "May 2025 to May 2026",
        },
      },
      7,
    );
    const [a, b] = squaresOf(vm);
    expect(a).toMatchObject({ id: "a", survey: true, markerFrame: null, note: null });
    expect(a.aria).toBe("Image from another survey: WISE W2, 2010");
    expect(b.aria).toBe("SPHEREx frame, May 2025 to May 2026");
    if (a.picture?.kind !== "grey" || b.picture?.kind !== "grey") throw new Error("grey expected");
    expect(a.picture.limits).toEqual(displayLimits(limits, 7));
    expect(b.picture.limits).toEqual(displayLimits({ ...limits, vmax: 4 }, 7));
    expect(a.picture.limits).not.toEqual(b.picture.limits);
    expect(fitInUse(vm)).toBe(vm.geometry.two);
  });

  it("marks a frame at its date, and a stack of every visit with each mover's whole track", () => {
    const still = {
      id: "still",
      label: null,
      xy: [
        { x: 30, y: 40 },
        { x: 30, y: 40 },
        { x: 30, y: 40 },
        { x: 30, y: 40 },
      ],
      fast: false,
    };
    const mover = {
      id: "mover",
      label: "8.0″/yr",
      xy: [{ x: 60, y: 60 }, { x: 59, y: 60 }, null, { x: 57, y: 60 }],
      fast: true,
    };
    const path = [
      { x: 60, y: 60 },
      { x: 59, y: 60 },
      { x: 57, y: 60 },
    ];
    const markers = {
      status: "ready" as const,
      note: null,
      gaia: [still],
      catwise: [mover],
      was: null,
    };

    // Blink: every source where it is at the date of the frame on screen, the mover with its track.
    const blink = viewOf(opened(field()), { markers });
    const shown = blink.field?.pair.shown ?? -1;
    const onFrame = marksOf(blink, squaresOf(blink)[0]);
    expect(onFrame.gaia).toEqual([{ id: "still", point: { x: 30, y: 40 }, track: null }]);
    expect(onFrame.catwise).toEqual([{ id: "mover", point: mover.xy[shown] ?? null, track: path }]);

    // Then and now: the SPHEREx square is one stack of every visit, so the mover is its track
    // alone (never the newest visit's place); the older survey's square carries no catalogue mark.
    const then = viewOf(opened(field()), {
      markers,
      thenAndNow: { status: "none", note: "No older image.", older: null, sphx: null },
    });
    if (!then.field) throw new Error("field expected");
    const thenVm = { ...then, field: { ...then.field, view: "then" as const } };
    const [survey, stack] = squaresOf(thenVm);
    expect(stack.markerFrame).toBe("stack");
    expect(marksOf(thenVm, survey)).toEqual({ gaia: [], catwise: [] });
    const onStack = marksOf(thenVm, stack);
    expect(onStack.gaia).toEqual([{ id: "still", point: { x: 30, y: 40 }, track: null }]);
    expect(onStack.catwise).toEqual([{ id: "mover", point: null, track: path }]);
  });

  it("Then and now with no older image: the square says why, in the extras lane's words", () => {
    const vm = thenView({
      status: "none",
      note: "No older survey image is stored for this position.",
      older: null,
      sphx: null,
    });
    const [a, b] = squaresOf(vm);
    expect(a.picture).toBeNull();
    expect(a.note).toBe("No older survey image is stored for this position.");
    expect(b.picture).toBeNull();
    expect(b.note).toBeNull();
  });
});

describe("pictures", () => {
  const ramp: SigmaRamp = {
    zero: [0, 0, 0],
    earlier: [
      [1, 0, 0],
      [2, 0, 0],
      [3, 0, 0],
      [4, 0, 0],
      [5, 0, 0],
    ],
    later: [
      [0, 0, 1],
      [0, 0, 2],
      [0, 0, 3],
      [0, 0, 4],
      [0, 0, 5],
    ],
  };
  const limits: Limits = { sigmaRef: 1, vmin: -2, vmax: 10, soften: 3 };

  it("mask exactly the pixels the painters hatch", () => {
    const synthetic_data = new Float32Array([0, NAN, 3, Number.POSITIVE_INFINITY]);
    const grey = { kind: "grey" as const, data: synthetic_data, limits, invert: true };
    expect(Array.from(noDataOf(grey))).toEqual([0, 1, 0, 1]);
    const painted = paintPicture(grey, 2, ramp);
    expect(Array.from(painted.rgba)).toEqual(
      Array.from(paintGrey(synthetic_data, 2, limits, { invert: true })),
    );
    expect(painted.any).toBe(true);
    expect(Array.from(noDataOf({ ...grey, limits: null }))).toEqual([1, 1, 1, 1]);
  });

  it("hatch a difference with no noise everywhere", () => {
    const sigma = { kind: "sigma" as const, data: new Float32Array([0, 1]), sigma: 0 };
    expect(Array.from(noDataOf(sigma))).toEqual([1, 1]);
    expect(hasNoData({ ...sigma, sigma: 0.5 })).toBe(false);
  });
});
