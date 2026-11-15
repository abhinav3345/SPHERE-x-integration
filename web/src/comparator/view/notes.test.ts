import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { Manifest } from "../../contract";
import { decodeFloat16 } from "../../player/float16";
import { FieldSynth } from "../../player/synth";
import { deriveView, type Env } from "../derive";
import {
  type Action,
  INITIAL_STATE,
  type LoadedField,
  type RecordedId,
  reduce,
  resolve,
  sequenceOf,
  type ViewId,
  type ViewState,
  viewBlocked,
} from "../model";
import type { OptionVM } from "../vm";
import { greyedReason, switchNotes, viewColumns, viewNotes } from "./notes";

const view = (id: ViewId, label: string, disabled = false, checked = false): OptionVM<ViewId> => ({
  id,
  label,
  meta: null,
  checked,
  disabled,
});

// The ViewModel's sentences (model.ts viewBlocked and derive.ts), as these tests' inputs.
const SIDE = "Side by side is greyed: only one frame covers this.";
const DIFF = "Difference is greyed: fewer than two full frames.";
const THEN = "Then and now is greyed: no older survey image here.";
const PAIRING = "No older survey image matches All. Then and now pairs WISE W1 with D4.";
const NO_FRAME = "The other views open once a frame is on screen.";

describe("view notes", () => {
  it("gives each greyed view its reason, the ViewModel's note naming the first", () => {
    const views = [view("blink", "Blink", false, true), view("then", "Then and now", true)];
    expect(viewNotes(views, THEN, () => THEN)).toEqual([THEN]);
  });

  it("names every greyed view, in the switch's order, each sentence once", () => {
    const views = [
      view("blink", "Blink", false, true),
      view("side", "Side by side"),
      view("difference", "Difference", true),
      view("then", "Then and now", true),
    ];
    const reasons = new Map<ViewId, string>([
      ["difference", DIFF],
      ["then", THEN],
    ]);
    expect(viewNotes(views, DIFF, (id) => reasons.get(id) ?? null)).toEqual([DIFF, THEN]);
    expect(viewNotes(views, null, (id) => reasons.get(id) ?? null)).toEqual([DIFF, THEN]);
    expect(viewNotes(views, null, () => DIFF)).toEqual([DIFF]);
  });

  it("keeps the ViewModel's single note while no frame is on screen", () => {
    const views = [
      view("blink", "Blink", true, true),
      view("side", "Side by side", true),
      view("difference", "Difference", true),
      view("then", "Then and now", true),
    ];
    expect(viewNotes(views, NO_FRAME, () => null)).toEqual([NO_FRAME]);
  });

  it("says nothing when nothing is greyed", () => {
    const views = [view("blink", "Blink", false, true), view("side", "Side by side")];
    expect(viewNotes(views, null, () => SIDE)).toEqual([]);
  });

  it("leaves the Then and now pairing to the Then and now block", () => {
    const views = [
      view("blink", "Blink", false, true),
      view("side", "Side by side"),
      view("difference", "Difference"),
      view("then", "Then and now"),
    ];
    expect(viewNotes(views, PAIRING, () => null)).toEqual([]);
  });
});

// The recorded REAL fields in public/fixtures (copied in from cache/fixtures).
const fixturesDir = fileURLToPath(new URL("../../../public/fixtures/", import.meta.url));

function loadRecorded(name: RecordedId): LoadedField | null {
  const dir = join(fixturesDir, name);
  if (!existsSync(join(dir, "manifest.json"))) return null;
  const manifest: Manifest = JSON.parse(readFileSync(join(dir, "manifest.json"), "utf8"));
  const bytes = readFileSync(join(dir, "frames.bin"));
  const synth = new FieldSynth(manifest, decodeFloat16(new Uint8Array(bytes).buffer));
  return { manifest, synth, source: "api", recorded: name };
}

const wise = loadRecorded("wise0855");
const barnard = loadRecorded("barnard");
const haveFixtures = wise !== null && barnard !== null;

/**
 * The recorded field minus its older-survey planes (and the provenance notes about them): the same
 * real SPHEREx pixels, fewer planes. It stands for a field with no older-survey image, as a live
 * build gives when the archives failed, or an engine older than pipeline 0.3.0.
 */
function withoutOlderSurveys(field: LoadedField): LoadedField {
  const older = field.manifest.planes.filter((plane) => plane.kind === "legacy");
  const missions = [...new Set(older.map((plane) => plane.mission))];
  const planes = field.manifest.planes.filter((plane) => plane.kind !== "legacy");
  const npix = field.synth.npix;
  const values = new Float32Array(Math.max(...planes.map((plane) => plane.offset / 2 + npix)));
  for (const plane of planes) values.set(field.synth.planeData(plane), plane.offset / 2);
  const notes = field.manifest.provenance.notes.filter(
    (note) => !missions.some((mission) => note.startsWith(`${mission} `)),
  );
  const manifest: Manifest = {
    ...field.manifest,
    planes,
    provenance: { ...field.manifest.provenance, notes },
  };
  return { ...field, manifest, synth: new FieldSynth(manifest, values) };
}

const run = (state: ViewState, ...actions: Action[]) => actions.reduce(reduce, state);

function opened(field: LoadedField, fallback = false): ViewState {
  const asked = run(INITIAL_STATE, {
    type: "go",
    place: { kind: "recorded", target: field.recorded ?? "wise0855" },
  });
  return run(asked, { type: "loaded", requestId: asked.request?.id ?? -1, field, fallback });
}

const ENV: Env = {
  layout: "three",
  columnWidth: 0,
  dpr: 1,
  reducedMotion: false,
  engine: "up",
  newest: null,
  now: 0,
  announcement: "",
  searchHint: "Try 133.7599 -7.2418.",
};

/**
 * One line of the 362px rail at 1280: the notes' type measured 5.1 to 5.6px a character in Chromium
 * (14 Nov: "Then and now is greyed: no older survey image here." 284px, the 64-character field-of-view
 * note 347px), so 60 characters stay under about 340px. The two-line sentence this replaced had 74.
 */
const ONE_LINE = 60;

describe.skipIf(!haveFixtures)("notes under the view switch on the recorded fields", () => {
  const fields = [wise, barnard] as LoadedField[];

  it("say why each greyed view is greyed, once each, in one line of the 362px rail", () => {
    // The recorded fields hold older-survey images (pipeline 0.3.0); the same fields without them
    // stand for a field that has none.
    const cases = fields.flatMap((field) => [
      { field, older: true },
      { field: withoutOlderSurveys(field), older: false },
    ]);
    for (const { field, older } of cases) {
      for (const engine of ["up", "down"] as const) {
        for (const band of ["all", "cold", "rgb"] as const) {
          const vm = deriveView(run(opened(field), { type: "setBand", band }), {
            ...ENV,
            engine,
          });
          const on = vm.field;
          if (!on) throw new Error("no field on screen");
          const greyed = vm.views
            .filter((option) => option.disabled)
            .map((option) => viewBlocked(option.id, on.sequence, on.manifest));
          const notes = switchNotes(vm);
          expect(notes).toEqual([...new Set(greyed)]);
          const then = vm.views.find((option) => option.id === "then");
          if (older) {
            // Then and now is offered, so nothing is said about it here.
            expect(then?.disabled).toBe(false);
            expect(notes.some((note) => note.startsWith("Then and now"))).toBe(false);
          } else {
            expect(then?.disabled).toBe(true);
            expect(notes).toContain(THEN);
          }
          for (const note of notes) expect(note.length).toBeLessThanOrEqual(ONE_LINE);
        }
      }
    }
  });

  it("keeps the no-frame note before a field is on screen", () => {
    const vm = deriveView(INITIAL_STATE, ENV);
    expect(switchNotes(vm)).toEqual([NO_FRAME]);
  });

  it("gives a reason only for a view that is greyed", () => {
    const field = wise as LoadedField;
    const sequence = sequenceOf(field.synth, "cold");
    const on = { sequence, manifest: field.manifest };
    expect(greyedReason("blink", on)).toBeNull();
    expect(greyedReason("side", on)).toBeNull();
    expect(greyedReason("difference", on)).toBeNull();
    // The recorded field holds older-survey images: Then and now is not greyed.
    expect(greyedReason("then", on)).toBeNull();
    const bare = withoutOlderSurveys(field);
    expect(
      greyedReason("then", { sequence: sequenceOf(bare.synth, "cold"), manifest: bare.manifest }),
    ).toBe(THEN);
    expect(greyedReason("then", null)).toBeNull();
    // One visit of the real field alone: nothing to set beside it or to subtract from it.
    const one = { sequence: sequence.slice(0, 1), manifest: field.manifest };
    expect(greyedReason("side", one)).toMatch(/^Side by side is greyed: /);
    expect(greyedReason("difference", one)).toMatch(/^Difference is greyed: /);
  });
});

describe("view switch columns", () => {
  it("is one row from 1280 and 2 × 2 with four views on a phone and in the rail", () => {
    expect(viewColumns("three", 4)).toBe(4);
    expect(viewColumns("wide", 3)).toBe(3);
    expect(viewColumns("phone", 4)).toBe(2);
    expect(viewColumns("rail", 4)).toBe(2);
    expect(viewColumns("phone", 3)).toBe(3);
    expect(viewColumns("phone", 2)).toBe(2);
  });
});

describe.skipIf(!haveFixtures)("a band change keeps the visits on screen", () => {
  // BandSelector calls vm.handlers.setBand alone: the reducer keeps frame and partner wherever
  // the new band has data at those visits (model.ts setBand).
  it("keeps frame and partner where the new band has data, and lets the default stand elsewhere", () => {
    for (const field of [wise, barnard] as LoadedField[]) {
      const picked = run(opened(field), { type: "pickFrame", index: 1 });
      const pair = resolve(picked)?.pair;
      if (!pair) throw new Error("no pair on screen");
      for (const band of ["all", "cold", "rgb", "d1", "d6"] as const) {
        const next = sequenceOf(field.synth, band);
        const changed = run(picked, { type: "setBand", band });
        expect(changed.band).toBe(band);
        const usable = (i: number) => next[i]?.hasData === true;
        expect(changed.frame).toBe(usable(pair.frame) ? pair.frame : null);
        expect(changed.partner).toBe(
          usable(pair.partner) && pair.partner !== changed.frame ? pair.partner : null,
        );
      }
    }
  });
});
