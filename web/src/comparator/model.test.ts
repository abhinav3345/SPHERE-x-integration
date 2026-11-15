/**
 * The comparator's reducer and selectors, checked on the recorded REAL fields in public/fixtures
 * (as player/fixtures.test.ts loads them). The expected strings are the design's own
 * (Handoff-copy), which were written from the same data.
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { Manifest } from "../contract";
import type { MoverHint } from "../overlays/types";
import { decodeFloat16 } from "../player/float16";
import { FieldSynth } from "../player/synth";
import { type Derived, deriveView, type Env } from "./derive";
import { withFeatures } from "./features";
import {
  type Action,
  BAND_IDS,
  bandRange,
  CENTRE,
  caveatSentences,
  createReducer,
  displayLimits,
  effectiveBand,
  effectiveView,
  frameLabels,
  INITIAL_STATE,
  type LoadedField,
  mergeLeftOut,
  nearestRecorded,
  openingFrame,
  placeAt,
  provenanceOf,
  RECORDED_CENTRES,
  type RecordedId,
  readoutAt,
  reduce,
  resolve,
  resolvePair,
  rewriteWarning,
  type SeqFrame,
  saturationOf,
  sequenceLimits,
  sequenceOf,
  TARGETS,
  targetPosition,
  timelineKey,
  timelineRows,
  type ViewState,
  viewBlocked,
} from "./model";

const fixturesDir = fileURLToPath(new URL("../../public/fixtures/", import.meta.url));

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

/** Applies actions in order. */
function run(state: ViewState, ...actions: Action[]): ViewState {
  return actions.reduce(reduce, state);
}

/** A recorded field opened and loaded, as the hook does it. */
function opened(field: LoadedField, extra: Partial<ViewState> = {}): ViewState {
  const target = field.recorded ?? "wise0855";
  const asked = run(
    { ...INITIAL_STATE, ...extra },
    {
      type: "go",
      place: { kind: "recorded", target },
      band: extra.band ?? null,
    },
  );
  return run(asked, {
    type: "loaded",
    requestId: asked.request?.id ?? -1,
    field,
    fallback: false,
  });
}

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

/** A mover hint shaped as the search lane returns one; its values are made up for this test. */
const synthetic_hint: MoverHint = {
  name: "Test mover",
  wasHereYear: 2010,
  now: { ra: RECORDED_CENTRES.wise0855.ra, dec: RECORDED_CENTRES.wise0855.dec },
  offsetArcsec: 126,
  direction: "west",
  source: "test",
  sentence: "Test mover was here in 2010. It is now 126″ to the west.",
};

describe("places", () => {
  it.skipIf(!haveFixtures)(
    "knows the recorded centres exactly as their manifests state them",
    () => {
      expect(RECORDED_CENTRES.wise0855).toEqual(wise?.manifest.centre);
      expect(RECORDED_CENTRES.barnard).toEqual(barnard?.manifest.centre);
    },
  );

  it("opens the recorded copy for a position on its centre at 6′, a build otherwise", () => {
    expect(placeAt(133.7599, -7.2418, 6, null)).toEqual({ kind: "recorded", target: "wise0855" });
    expect(placeAt(133.7599, -7.2418, 8, null)).toMatchObject({ kind: "position" });
    expect(placeAt(133.79513, -7.24515, 6, null)).toMatchObject({ kind: "position" });
    expect(placeAt(269.4463, 4.7682, 6, "x")).toEqual({ kind: "recorded", target: "barnard" });
  });

  it("finds the recorded field nearest a position", () => {
    expect(nearestRecorded(270, 5)).toBe("barnard");
    expect(nearestRecorded(133, -7)).toBe("wise0855");
  });
});

describe.skipIf(!haveFixtures)("the sequence of a recorded field", () => {
  const wiseCold = () => sequenceOf((wise as LoadedField).synth, "cold");
  const barnardAll = () => sequenceOf((barnard as LoadedField).synth, "all");

  it("is time-ordered with the contract's partial and thin flags (WISE 0855, Cold objects)", () => {
    const sequence = wiseCold();
    expect(sequence.map((f) => f.frame.nExposures)).toEqual([11, 32, 9, 32]);
    expect(sequence.map((f) => f.partial)).toEqual([true, false, true, false]);
    expect(sequence.map((f) => f.full)).toEqual([false, true, false, true]);
  });

  it("is time-ordered with the contract's flags (Barnard's Star, All)", () => {
    const sequence = barnardAll();
    expect(sequence.map((f) => f.frame.nExposures)).toEqual([104, 9, 111, 8, 116]);
    expect(sequence.map((f) => f.partial)).toEqual([false, true, false, true, false]);
  });

  it("keeps a visit with no data in the band, labelled, never dropped", () => {
    const sequence = sequenceOf((barnard as LoadedField).synth, "cold");
    expect(sequence).toHaveLength(5);
    const empty = sequence[1];
    expect(empty.hasData).toBe(false);
    expect(empty.partial && empty.thin).toBe(true);
    expect(empty.frame.data.every((value) => Number.isNaN(value))).toBe(true);
  });

  it("is computed once per field and band", () => {
    expect(wiseCold()).toBe(wiseCold());
  });

  it("opens on the newest full frame, its partner the oldest full one (Handoff-images)", () => {
    expect(resolvePair(wiseCold(), null, null, "blink", false)).toEqual({
      frame: 3,
      partner: 1,
      shown: 3,
      a: 1,
      b: 3,
    });
    expect(resolvePair(barnardAll(), null, null, "blink", false)).toMatchObject({
      frame: 4,
      partner: 0,
    });
  });

  it("shows the partner only while the key is held, in Blink", () => {
    expect(resolvePair(wiseCold(), 3, 1, "blink", true)?.shown).toBe(1);
    expect(resolvePair(wiseCold(), 3, 1, "side", true)?.shown).toBe(3);
  });

  it("never subtracts a greyed frame", () => {
    const pair = resolvePair(wiseCold(), 0, 2, "difference", false);
    expect(pair).toMatchObject({ frame: 3, partner: 1 });
  });

  it("repairs a frame or partner that does not fit the sequence", () => {
    expect(resolvePair(wiseCold(), 9, null, "blink", false)?.frame).toBe(3);
    expect(resolvePair(wiseCold(), 1, 1, "blink", false)?.partner).toBe(3);
  });
});

describe.skipIf(!haveFixtures)("the reducer", () => {
  const field = () => wise as LoadedField;

  it("starts a load for a place and drops a late answer to an older request", () => {
    const first = run(INITIAL_STATE, {
      type: "go",
      place: { kind: "recorded", target: "wise0855" },
    });
    expect(first.load.phase).toBe("loading");
    expect(first.request).toMatchObject({ id: 1, target: "wise0855", fov: 6 });
    const second = run(first, { type: "go", place: { kind: "recorded", target: "barnard" } });
    const late = run(second, { type: "loaded", requestId: 1, field: field(), fallback: false });
    expect(late.load.phase).toBe("loading");
  });

  it("uses the field's default band unless a built band with data was chosen", () => {
    const state = opened(field());
    expect(effectiveBand(state)).toBe("cold");
    expect(effectiveBand(opened(barnard as LoadedField))).toBe("all");
    expect(effectiveBand({ ...state, band: "d1" })).toBe("d1");
    // Three-colour: the band when the part is built, the field's default when it is not.
    expect(effectiveBand({ ...state, band: "rgb" }, withFeatures({ threeColour: true }))).toBe(
      "rgb",
    );
    expect(effectiveBand({ ...state, band: "rgb" }, withFeatures({ threeColour: false }))).toBe(
      "cold",
    );
  });

  it("steps in Blink, stops playback, and never changes the partner", () => {
    const state = run(opened(field()), { type: "play" });
    expect(state.playing).toBe(true);
    const stepped = run(state, { type: "step", delta: 1 });
    expect(stepped).toMatchObject({ frame: 0, partner: 1, playing: false });
    const back = run(stepped, { type: "step", delta: -1 }, { type: "step", delta: -1 });
    expect(back).toMatchObject({ frame: 2, partner: 1 });
  });

  it("advances on a tick only while playing", () => {
    const paused = opened(field());
    expect(run(paused, { type: "tick" })).toBe(paused);
    const playing = run(paused, { type: "play" }, { type: "tick" }, { type: "tick" });
    expect(playing).toMatchObject({ frame: 1, partner: 1, playing: true });
  });

  it("makes the frame you came from the partner when a row is chosen", () => {
    const picked = run(opened(field()), { type: "pickFrame", index: 0 });
    expect(picked).toMatchObject({ frame: 0, partner: 3, playing: false });
  });

  it("refuses a greyed row in Difference", () => {
    const diff = run(opened(field()), { type: "setView", view: "difference" });
    expect(diff.view).toBe("difference");
    expect(run(diff, { type: "pickFrame", index: 2 })).toBe(diff);
  });

  it("flips to the partner and back; not without the flip key; not outside Blink", () => {
    const held = run(opened(field()), { type: "flip", held: true });
    expect(resolve(held)?.pair.shown).toBe(1);
    expect(resolve(run(held, { type: "flip", held: false }))?.pair.shown).toBe(3);
    const noFlip = createReducer(withFeatures({ holdToFlip: false }));
    expect(noFlip(opened(field()), { type: "flip", held: true }).held).toBe(false);
    const side = run(opened(field()), { type: "setView", view: "side" });
    expect(run(side, { type: "flip", held: true }).held).toBe(false);
  });

  it("ignores views and bands that are not built", () => {
    const state = opened(field());
    const without = createReducer(withFeatures({ thenAndNow: false, threeColour: false }));
    expect(without(state, { type: "setView", view: "then" })).toBe(state);
    expect(without(state, { type: "setBand", band: "rgb" })).toBe(state);
    const built = createReducer(withFeatures({ thenAndNow: true, threeColour: true }));
    // Built, and the recorded field holds older-survey images (pipeline 0.3.0): it opens.
    expect(built(state, { type: "setView", view: "then" }).view).toBe("then");
    // Built, but a field with no older-survey image: Then and now stays greyed.
    const bare = opened(withoutOlderSurveys(field()));
    expect(built(bare, { type: "setView", view: "then" })).toBe(bare);
    expect(effectiveView({ ...bare, view: "then" })).toBe("blink");
    expect(built(state, { type: "setBand", band: "rgb" }).band).toBe("rgb");
    const noSide = createReducer(withFeatures({ sideBySide: false }));
    expect(noSide(state, { type: "setView", view: "side" }).view).toBe("blink");
    expect(effectiveView({ ...state, view: "side" }, withFeatures({ sideBySide: false }))).toBe(
      "blink",
    );
  });

  it("keeps the same visits on screen when the band changes, where the new band has them", () => {
    const picked = run(opened(field()), { type: "pickFrame", index: 1 });
    expect(resolve(picked)?.pair).toMatchObject({ frame: 1, partner: 3 });
    const state = run(picked, { type: "setBand", band: "all" });
    expect(state).toMatchObject({ band: "all", frame: 1, partner: 3 });
    expect(resolve(state)?.pair).toMatchObject({ frame: 1, partner: 3 });
    // Barnard's Star has no Cold objects image at its second visit: that frame is not kept, and
    // the band opens on its own opening frame instead.
    const barnardPicked = run(opened(barnard as LoadedField), { type: "pickFrame", index: 1 });
    const cold = run(barnardPicked, { type: "setBand", band: "cold" });
    expect(cold.frame).toBeNull();
    expect(resolve(cold)?.pair.frame).toBe(
      openingFrame(sequenceOf((barnard as LoadedField).synth, "cold")),
    );
  });

  it("keeps a target's own band when the same sky is built at another size", () => {
    // WISE 0855 is visible only in Cold objects: at 8′ it is a build, still in Cold objects.
    const wider = run(opened(field()), { type: "setFov", fov: 8 });
    expect(wider.request).toMatchObject({
      place: { kind: "position" },
      fov: 8,
      target: "wise0855",
    });
    expect(wider.band).toBeNull();
    expect(effectiveBand(wider)).toBe("cold");
    // A position typed by hand has no target: All.
    const typed = run(INITIAL_STATE, {
      type: "go",
      place: { kind: "position", ra: 133.7951, dec: -7.2451, name: null },
    });
    expect(effectiveBand(typed)).toBe("all");
  });

  it("clears a search error and its sentence once the entry is edited", () => {
    const failed = run(
      INITIAL_STATE,
      { type: "setQuery", text: "133.7599 -97.2" },
      { type: "searchStarted", nameLike: false },
      { type: "searchFailed", message: "Declination must be between −90 and +90 degrees." },
    );
    expect(failed.search).toMatchObject({ error: true, busy: false });
    const edited = run(failed, { type: "setQuery", text: "133.7599 -7.2" });
    expect(edited.search).toMatchObject({ text: "133.7599 -7.2", error: false, message: null });
    // Without an error, editing keeps the line as it was.
    const kept = run(
      { ...INITIAL_STATE, search: { ...INITIAL_STATE.search, message: "Read as RA 1°, Dec 2°." } },
      { type: "setQuery", text: "x" },
    );
    expect(kept.search.message).toBe("Read as RA 1°, Dec 2°.");
  });

  it("says how a position was read while the fast-mover check runs, never the last field's sentence", () => {
    const shown = opened(field());
    const started = run(
      {
        ...shown,
        search: { ...shown.search, message: "Showing the recorded field for WISE 0855." },
      },
      { type: "searchStarted", nameLike: false, message: "Read as RA 269.44630°, Dec 4.76820°." },
    );
    expect(started.search).toMatchObject({
      busy: true,
      message: "Read as RA 269.44630°, Dec 4.76820°.",
    });
    const name = run(shown, { type: "searchStarted", nameLike: true });
    expect(name.search.message).toBe("Looking up the name.");
    const cancelled = run(name, { type: "searchCancelled" });
    expect(cancelled.search).toMatchObject({ busy: false, error: false, message: null });
    expect(run(shown, { type: "searchCancelled" })).toBe(shown);
  });

  it("stops playing on Esc, then closes the spotlight", () => {
    const state = run(opened(field()), { type: "setSpotlight", on: true }, { type: "play" });
    const once = run(state, { type: "escape" });
    expect(once).toMatchObject({ playing: false, spotlight: true });
    expect(run(once, { type: "escape" }).spotlight).toBe(false);
    expect(run(INITIAL_STATE, { type: "setSpotlight", on: true }).spotlight).toBe(false);
  });

  it("moves the ring within the field, and the pixel cursor from the ring", () => {
    const ringed = run(opened(field()), { type: "setRing", ring: { dx: 80, dy: -3 } });
    expect(ringed.ring).toEqual({ dx: 59, dy: -3 });
    const cursor = run(ringed, { type: "moveCursor", dx: -10, dy: 1 });
    expect(cursor.cursor).toEqual({ dx: 49, dy: -2 });
    const committed = run(cursor, { type: "commitCursor" });
    expect(committed).toMatchObject({ ring: { dx: 49, dy: -2 }, cursor: null });
  });

  it("builds a recorded field's centre at another field of view, and returns to the copy at 6′", () => {
    const state = run(opened(field()), { type: "setBand", band: "d6" }, { type: "setFov", fov: 8 });
    expect(state.request?.place).toEqual({
      kind: "position",
      ra: RECORDED_CENTRES.wise0855.ra,
      dec: RECORDED_CENTRES.wise0855.dec,
      name: "WISE 0855",
    });
    expect(state).toMatchObject({ fov: 8, band: "d6" });
    const back = run(state, { type: "setFov", fov: 6 });
    expect(back.request?.place).toEqual({ kind: "recorded", target: "wise0855" });
  });

  it("jumps to where a mover is now, and keeps the banner without its button", () => {
    const asked = run(INITIAL_STATE, {
      type: "go",
      place: { kind: "position", ra: 133.79513, dec: -7.24515, name: null },
      mover: { hint: synthetic_hint, from: { ra: 133.79513, dec: -7.24515 }, jumped: false },
    });
    const jumped = run(asked, { type: "jump" });
    expect(jumped.request?.place).toEqual({ kind: "recorded", target: "wise0855" });
    expect(jumped.mover?.jumped).toBe(true);
    expect(run(jumped, { type: "jump" })).toBe(jumped);
  });

  it("keeps what was typed through a search error", () => {
    const state = run(
      INITIAL_STATE,
      { type: "setQuery", text: "Planet X" },
      { type: "searchStarted", nameLike: true },
    );
    expect(state.search).toMatchObject({ busy: true, message: "Looking up the name." });
    const failed = run(state, {
      type: "searchFailed",
      message: "No object of that name was found.",
    });
    expect(failed.search).toMatchObject({ text: "Planet X", error: true, busy: false });
    expect(run(failed, { type: "setQuery", text: "Planet" }).search.error).toBe(false);
  });

  it("tries the same place again under a new request", () => {
    const asked = run(INITIAL_STATE, {
      type: "go",
      place: { kind: "recorded", target: "barnard" },
    });
    const failed = run(asked, {
      type: "loadFailed",
      requestId: 1,
      code: "internal",
      message: "The API failed while building this field.",
    });
    const again = run(failed, { type: "retry" });
    expect(again.request).toMatchObject({ id: 2, place: { kind: "recorded", target: "barnard" } });
    expect(again.load.phase).toBe("loading");
  });
});

describe.skipIf(!haveFixtures)("what the design shows, from the real fields", () => {
  const wiseState = () => opened(wise as LoadedField);
  const barnardState = () => opened(barnard as LoadedField);

  it("lists WISE 0855's visits in Cold objects as the design's copy does", () => {
    const r = resolve(wiseState());
    if (!r) throw new Error("no field");
    const rows = timelineRows(r);
    expect(rows.map((row) => row.when)).toEqual([
      "5–6 May 2025",
      "7–14 Nov 2025",
      "11–13 Dec 2025",
      "21 Apr–14 May 2026",
    ]);
    expect(rows.map((row) => row.count)).toEqual([
      "11 exposures, partial",
      "32 exposures",
      "9 exposures, partial",
      "32 exposures",
    ]);
    expect(rows.map((row) => row.current)).toEqual([false, false, false, true]);
    expect(timelineKey(r.sequence, "blink")).toBe("Partial: a different mix of wavelengths.");
    expect(timelineKey(r.sequence, "difference")).toBe(
      "Greyed frames cannot be subtracted. Partial: a different mix of wavelengths.",
    );
  });

  it("tags the pair A and B in Side by side", () => {
    const r = resolve(run(wiseState(), { type: "setView", view: "side" }));
    if (!r) throw new Error("no field");
    expect(timelineRows(r).map((row) => row.tag)).toEqual([null, "A", null, "B"]);
    expect(timelineRows(r).some((row) => row.current)).toBe(false);
  });

  it("lists Barnard's Star's visits as the design's copy does", () => {
    const r = resolve(barnardState());
    if (!r) throw new Error("no field");
    expect(timelineRows(r).map((row) => `${row.when}, ${row.count}`)).toEqual([
      "15 Aug–5 Sep 2025, 104 exposures",
      "30 Sep–1 Oct 2025, 9 exposures, partial",
      "11 Mar–10 Apr 2026, 111 exposures",
      "4–5 May 2026, 8 exposures, partial",
      "16 Aug–22 Sep 2026, 116 exposures",
    ]);
  });

  it("writes every frame label at one fixed width", () => {
    const sequence = sequenceOf((wise as LoadedField).synth, "cold");
    const labels = frameLabels(sequence, (wise as LoadedField).manifest);
    expect(labels[3]).toMatchObject({
      when: "21 Apr to 14 May 2026",
      range: "3.96 to 5.00 µm",
      count: " 32 exposures",
      partial: false,
      saturated: false,
    });
    expect(labels[1].when).toBe("07 Nov to 14 Nov 2025");
    expect(new Set(labels.map((l) => l.when.length)).size).toBe(1);
    expect(new Set(labels.map((l) => l.count.length)).size).toBe(1);
    const all = frameLabels(
      sequenceOf((wise as LoadedField).synth, "all"),
      (wise as LoadedField).manifest,
    );
    expect(all[0]).toMatchObject({ range: "0.93 to 5.00 µm", partial: true });
  });

  it("marks Barnard's Star's frames with a saturated core", () => {
    const labels = frameLabels(
      sequenceOf((barnard as LoadedField).synth, "all"),
      (barnard as LoadedField).manifest,
    );
    expect(labels.every((label) => label.saturated)).toBe(true);
  });

  it("marks a saturated core only where most exposures saturated, or where the frame's core is blank", () => {
    const manifest = (wise as LoadedField).manifest;
    const sequence = sequenceOf((wise as LoadedField).synth, "cold");
    // The engine's own warnings (pipeline 0.3.0, live builds of 14 Nov 2026).
    const withWarning = (warning: string): Manifest => ({ ...manifest, warnings: [warning] });
    const few = withWarning(
      "saturated core within 15 arcsec of the centre in 3 of 461 exposures: those pixels have no value, so no brightness can be read there",
    );
    const most = withWarning(
      "saturated core within 15 arcsec of the centre in 591 of 594 exposures: those pixels have no value, so no brightness can be read there",
    );
    expect(saturationOf(few)).toBe("some");
    expect(saturationOf(most)).toBe("most");
    expect(saturationOf(manifest)).toBe("none");
    expect(saturationOf((barnard as LoadedField).manifest)).toBe("most");
    // WISE 0855's Cold objects frames have a value at every pixel near the centre: no chip from a
    // handful of exposures (Epsilon Indi B's case), the chip on every frame from most of them.
    expect(frameLabels(sequence, few).some((label) => label.saturated)).toBe(false);
    expect(frameLabels(sequence, most).every((label) => label.saturated)).toBe(true);
    // A frame whose centre is blank does carry it with a few saturated exposures.
    const synthetic_blank = sequence.map((f) => {
      const data = new Float32Array(f.frame.data);
      data[manifest.grid.cy * manifest.grid.nx + manifest.grid.cx + 2] = Number.NaN;
      return { ...f, frame: { ...f.frame, data } };
    });
    expect(frameLabels(synthetic_blank, few).every((label) => label.saturated)).toBe(true);
  });

  it("merges the older-survey planes left out for one reason into one caveat", () => {
    const reason = "its brightness could not be matched to SPHEREx on field stars.";
    expect(
      mergeLeftOut([
        "5 exposures could not be used (no valid pixel or unknown noise)",
        `AllWISE W1: plane left out: ${reason}`,
        `AllWISE W2: plane left out: ${reason}`,
        `2MASS J: plane left out: ${reason}`,
        `2MASS H: plane left out: ${reason}`,
        `2MASS Ks: plane left out: ${reason}`,
      ]),
    ).toEqual([
      "5 exposures could not be used (no valid pixel or unknown noise)",
      "Older survey images left out (AllWISE W1, W2; 2MASS J, H, Ks): their brightness could not be matched to SPHEREx on field stars.",
    ]);
    expect(mergeLeftOut([`2MASS Ks: plane left out: ${reason}`])).toEqual([
      `2MASS Ks: plane left out: ${reason}`,
    ]);
    const manifest: Manifest = {
      ...(wise as LoadedField).manifest,
      warnings: [`AllWISE W1: plane left out: ${reason}`, `2MASS H: plane left out: ${reason}`],
    };
    expect(caveatSentences(manifest, null)).toEqual([
      "4 exposures could not be used.",
      "Older survey images left out (AllWISE W1; 2MASS H): their brightness could not be matched to SPHEREx on field stars.",
    ]);
  });

  it("says that a sampled field read a sample, not that the rest failed", () => {
    const manifest: Manifest = {
      ...(wise as LoadedField).manifest,
      exposures: {
        ...(wise as LoadedField).manifest.exposures,
        found: 2514,
        used: 577,
        sampled: true,
      },
      warnings: ["2 exposures could not be used (no valid pixel or unknown noise)"],
    };
    expect(caveatSentences(manifest, null)).toEqual([
      "2514 exposures cover this field; an even sample of at most 600 was read.",
      "2 exposures could not be used.",
    ]);
  });

  it("writes the caveats as sentences, visits by date", () => {
    const wiseCaveats = caveatSentences(
      (wise as LoadedField).manifest,
      sequenceOf((wise as LoadedField).synth, "cold"),
    );
    expect(wiseCaveats).toEqual([
      "4 exposures could not be used.",
      "2 of 4 visits are partial, marked in Frames.",
    ]);
    // Barnard's Star as pipeline 0.3.0 recorded it: the saturated core in Handoff-copy's form, the
    // core that overflowed but was measured keeping its "indicative only", visits by their dates.
    const barnardCaveats = caveatSentences(
      (barnard as LoadedField).manifest,
      sequenceOf((barnard as LoadedField).synth, "all"),
    );
    expect(barnardCaveats).toEqual([
      "2 exposures could not be used.",
      "Saturated core within 15″ of the centre in 240 of 360 exposures.",
      "Bright core within 15″ of the centre overflowed in 119 of 360 exposures: brightness there is indicative only.",
      "The visit of 30 Sep–1 Oct 2025 has only 9 exposures.",
      "The visit of 4–5 May 2026 has only 8 exposures.",
      "2 of 5 visits are partial, marked in Frames.",
    ]);
    expect(barnardCaveats.join(" ")).not.toMatch(/time bin|\d{4}-\d{2}-\d{2}|arcsec/i);
  });

  it("leaves a warning about an unknown time bin as it is", () => {
    expect(rewriteWarning("time bin 9 has only 3 exposures", [])).toBe(
      "Time bin 9 has only 3 exposures.",
    );
  });

  it("writes engine 0.3.0's saturated core in Handoff-copy's form", () => {
    // The engine's words on the live Epsilon Indi B build, 14 Nov 2026 (pipeline 0.3.0).
    expect(
      rewriteWarning(
        "saturated core within 15 arcsec of the centre in 3 of 461 exposures: those pixels have no value, so no brightness can be read there",
        [],
      ),
    ).toBe("Saturated core within 15″ of the centre in 3 of 461 exposures.");
    // Pipeline 0.2.0 wrote it so (the recorded fields until they were recorded again with 0.3.0).
    expect(
      rewriteWarning("saturated core within 15 arcsec of the centre in 359 of 360 exposures", []),
    ).toBe("Saturated core within 15″ of the centre in 359 of 360 exposures.");
    // The overflowing core is said in fewer words and keeps its "indicative only": it is what
    // the reader must know.
    expect(
      rewriteWarning(
        "bright core within 15 arcsec of the centre flagged as overflowing in 2 of 335 exposures, but measured: brightness there is indicative only",
        [],
      ),
    ).toBe(
      "Bright core within 15″ of the centre overflowed in 2 of 335 exposures: brightness there is indicative only.",
    );
  });

  it("writes engine 0.3.0's visits by ISO date as the design writes visits", () => {
    expect(rewriteWarning("the visit of 2025-09-30 to 2025-10-01 has only 9 exposures", [])).toBe(
      "The visit of 30 Sep–1 Oct 2025 has only 9 exposures.",
    );
    expect(rewriteWarning("the visit of 2026-05-04 has only 8 exposures", [])).toBe(
      "The visit of 4 May 2026 has only 8 exposures.",
    );
    // Not a date: left as it is.
    expect(rewriteWarning("the visit of 2025-13-40 has only 8 exposures", [])).toBe(
      "The visit of 2025-13-40 has only 8 exposures.",
    );
    // The warnings of the Barnard's Star field as engine 0.3.0 recorded it (the bundled copy,
    // 14 Nov 2026), and the caveats the reader gets.
    const manifest = (barnard as LoadedField).manifest;
    expect(manifest.warnings).toEqual([
      "2 exposures could not be used (no valid pixel or unknown noise)",
      "saturated core within 15 arcsec of the centre in 240 of 360 exposures: those pixels have no value, so no brightness can be read there",
      "bright core within 15 arcsec of the centre flagged as overflowing in 119 of 360 exposures, but measured: brightness there is indicative only",
      "the visit of 2025-09-30 to 2025-10-01 has only 9 exposures",
      "the visit of 2026-05-04 to 2026-05-05 has only 8 exposures",
    ]);
    expect(caveatSentences(manifest, null)).toEqual([
      "2 exposures could not be used.",
      "Saturated core within 15″ of the centre in 240 of 360 exposures.",
      "Bright core within 15″ of the centre overflowed in 119 of 360 exposures: brightness there is indicative only.",
      "The visit of 30 Sep–1 Oct 2025 has only 9 exposures.",
      "The visit of 4–5 May 2026 has only 8 exposures.",
    ]);
  });

  it("tells an older survey's failure without image ids or error codes", () => {
    expect(
      rewriteWarning(
        "AllWISE W1: 1 image(s) not read (3306m561_ac51: UpstreamError: gave up after 6 attempts: HTTP 503).",
        [],
      ),
    ).toBe("AllWISE W1: 1 image could not be read.");
    expect(
      rewriteWarning(
        "2MASS Ks: 2 image(s) not read (a (1): OSError: x; b: ValueError: bad (header)).",
        [],
      ),
    ).toBe("2MASS Ks: 2 images could not be read.");
    expect(
      rewriteWarning(
        "AllWISE: archive unavailable (UpstreamError: gave up after 6 attempts: HTTP 503); no AllWISE plane.",
        [],
      ),
    ).toBe("AllWISE: archive unavailable, so no AllWISE image.");
  });

  it("states provenance from the manifest", () => {
    const wiseManifest = (wise as LoadedField).manifest;
    const limits = sequenceLimits(sequenceOf((wise as LoadedField).synth, "cold"));
    const p = provenanceOf(wiseManifest, limits, []);
    expect(p.used).toBe("254 of 258");
    expect(p.release).toBe("SPHEREx Spectral Images, DR1");
    expect(p.dois.map((d) => d.doi)).toEqual(["10.26131/IRSA678"]);
    // Both recorded fields were recorded again with pipeline 0.3.0 (older-survey planes added).
    expect(p.pipeline).toBe("0.3.0");
    // The design's viewer measured the same scale on the same data.
    expect(p.stretch).toBe("−0.0180 to 0.440 MJy/sr");
    expect(p.warnings).toEqual(["None"]);
    const b = provenanceOf((barnard as LoadedField).manifest, null, ["x."]);
    expect(b.used).toBe("348 of 364");
    expect(b.release).toBe("SPHEREx Spectral Images, DR1 and QR3");
    expect(b.dois.map((d) => d.release)).toEqual(["DR1", "QR3"]);
    expect(b.pipeline).toBe("0.3.0");
    expect(b.stretch).toBeNull();
  });

  it("keeps one scale for every frame and moves only its top with Contrast", () => {
    const limits = sequenceLimits(sequenceOf((wise as LoadedField).synth, "cold"));
    if (!limits) throw new Error("no limits");
    expect(displayLimits(limits, 5)).toEqual(limits);
    const more = displayLimits(limits, 7);
    expect(more?.vmin).toBe(limits.vmin);
    expect(more?.vmax).toBeLessThan(limits.vmax);
    expect(displayLimits(limits, 0)?.vmax).toBeGreaterThan(limits.vmax);
  });

  it("reads the sky and the brightness at the ring", () => {
    const r = resolve(wiseState());
    if (!r) throw new Error("no field");
    const centre = readoutAt(r, CENTRE);
    expect(centre.ra).toBe("133.75980°");
    expect(centre.dec).toBe("−7.24220°");
    expect(centre.value).toMatch(/^−?\d.* MJy\/sr$/);
    const side = resolve(run(wiseState(), { type: "setView", view: "side" }));
    if (!side) throw new Error("no field");
    expect(readoutAt(side, CENTRE).value).toMatch(/^A .+ {3}B .+ {3}MJy\/sr$/);
    const diff = resolve(run(wiseState(), { type: "setView", view: "difference" }));
    if (!diff) throw new Error("no field");
    expect(readoutAt(diff, CENTRE).value).toMatch(/σ$/);
  });
});

describe.skipIf(!haveFixtures)("deriveView", () => {
  const derive = (state: ViewState, env: Partial<Env> = {}, flags = {}): Derived =>
    deriveView(state, { ...ENV, ...env }, withFeatures(flags));

  it("says what is missing before any position is chosen", () => {
    const v = derive(INITIAL_STATE);
    expect(v.image.state).toBe("none");
    expect(v.image.aria).toBe("Sky image. No frame is on screen.");
    expect(v.frameLabel).toMatchObject({ kind: "state", one: { when: "No frames here" } });
    expect(v.targetsInRail).toBe(true);
    expect(v.views.every((option) => option.disabled)).toBe(true);
    expect(v.viewNote).toBe("The other views open once a frame is on screen.");
    expect(v.display.note).toBe("Display controls are off until a frame is on screen.");
    expect(v.search.message).toBe("Try 133.7599 -7.2418.");
    expect(v.playback.why).toBe("No frame is on screen, so there is nothing to blink yet.");
    expect(v.chip).toBeNull();
    expect(v.title).toEqual({ title: "No position yet", line: "Type a position or a name below." });
    expect(v.ringBar.show).toBe(false);
  });

  it("shows a recorded field with its words and numbers", () => {
    const v = derive(opened(wise as LoadedField));
    expect(v.image.state).toBe("image");
    expect(v.chip).toBe("recorded");
    expect(v.search.message).toBe("Showing the recorded field for WISE 0855.");
    expect(v.playback.counter).toBe("Frame 4 of 4");
    expect(v.frameLabel.kind).toBe("one");
    expect(v.frameLabel.showPixels).toBe(false);
    expect(v.legend.position).toBe(true);
    expect(v.views.map((option) => option.id)).toEqual(["blink", "side", "difference", "then"]);
    expect(v.bands.map((option) => option.id)).toContain("rgb");
    expect(v.bands).toHaveLength(9);
    const without = derive(
      opened(wise as LoadedField),
      {},
      { thenAndNow: false, threeColour: false },
    );
    expect(without.views.map((option) => option.id)).toEqual(["blink", "side", "difference"]);
    expect(without.bands.map((option) => option.id)).not.toContain("rgb");
    expect(without.bands).toHaveLength(8);
    expect(v.rule.band).toBe("cold");
    expect(v.title).toEqual({ title: "WISE 0855", line: "RA 133.7598°  Dec −7.2422°" });
    expect(v.image.aria).toBe(
      "Sky image, 21 Apr to 14 May 2026, 3.96 to 5.00 micrometres. Arrow keys move the readout by one pixel. Enter moves the ring there.",
    );
    expect(v.field?.labels).toHaveLength(4);
  });

  it("greys every size but 6′ while only the recorded copy can be shown", () => {
    const down = derive(opened(wise as LoadedField), { engine: "down" });
    expect(down.fovs.filter((f) => !f.disabled).map((f) => f.id)).toEqual([6]);
    expect(down.fovNote).toBe("Only 6′ is recorded. Other sizes open when the archive responds.");
    const up = derive(opened(wise as LoadedField), { engine: "up" });
    expect(up.fovs.every((f) => !f.disabled)).toBe(true);
    expect(up.fovNote).toBeNull();
  });

  it("opens all five targets without name lookup, and says why one cannot open", () => {
    // The three without a recorded field open a build at their position: no names needed.
    const off = derive(INITIAL_STATE, { engine: "up" }, { nameSearch: false });
    expect(off.targets.every((t) => t.available)).toBe(true);
    const unknown = derive(INITIAL_STATE, { engine: "unknown" }, { nameSearch: false });
    expect(unknown.targets.every((t) => t.available)).toBe(true);
    // They need the engine.
    const down = derive(INITIAL_STATE, { engine: "down" }, { nameSearch: true });
    expect(down.targets.filter((t) => !t.available).map((t) => t.id)).toEqual([
      "epsindi",
      "rwaur",
      "rdra",
    ]);
    expect(down.targets[3].unavailable).toBe(
      "Not available right now: the archive is not responding.",
    );
    expect(derive(opened(wise as LoadedField)).targets[0].current).toBe(true);
  });

  it("puts each target without a recorded field where it is at the frames' epoch", () => {
    const position = (id: string) => {
      const target = TARGETS.find((t) => t.id === id);
      return target ? targetPosition(target) : null;
    };
    // Epsilon Indi B: astropy 7 (apply_space_motion) puts Gaia DR3 6412596012146801152 at
    // 331.0966534 −56.8006627 in 2026.0 (overlays/sky.test.ts); the contract's 4 decimals.
    expect(position("epsindi")).toEqual({ ra: 331.0967, dec: -56.8007 });
    // RW Aurigae and R Draconis move under 1.5″ in 26 years: within a pixel of SIMBAD's J2000.
    const rw = position("rwaur");
    const rd = position("rdra");
    expect(rw?.ra).toBeCloseTo(76.9566, 4);
    expect(rw?.dec).toBeCloseTo(30.4013, 4);
    expect(rd?.ra).toBeCloseTo(248.1672, 4);
    expect(rd?.dec).toBeCloseTo(66.755, 4);
    expect(position("wise0855")).toBeNull();
  });

  it("opens a target row as a build at its position, marked as that target", () => {
    const target = TARGETS.find((t) => t.id === "epsindi");
    const at = target ? targetPosition(target) : null;
    expect(at).not.toBeNull();
    const asked = run(INITIAL_STATE, {
      type: "go",
      place: placeAt(at?.ra ?? 0, at?.dec ?? 0, 6, "Epsilon Indi B"),
      target: "epsindi",
      text: "Epsilon Indi B",
    });
    expect(asked.request).toMatchObject({
      place: { kind: "position", ra: 331.0967, dec: -56.8007, name: "Epsilon Indi B" },
      target: "epsindi",
    });
    const v = derive(asked, { engine: "up" });
    expect(v.targets.find((t) => t.id === "epsindi")).toMatchObject({
      loading: true,
      caption: "Building this image…",
    });
  });

  it("writes each greyed view's reason in one line of the view rail", () => {
    // A field with no older-survey image greys Then and now.
    const bare = withoutOlderSurveys(wise as LoadedField);
    const sequence = sequenceOf(bare.synth, "cold");
    const note = viewBlocked("then", sequence, bare.manifest);
    expect(note).toBe("Then and now is greyed: no older survey image here.");
    // 362px of text-caption hold about 55 characters.
    expect(note?.length ?? 0).toBeLessThanOrEqual(52);
    expect(viewBlocked("side", sequence.slice(0, 1), bare.manifest)?.length).toBeLessThanOrEqual(
      52,
    );
    // The recorded fields hold older-survey images (pipeline 0.3.0): never greyed there.
    for (const field of [wise, barnard] as LoadedField[]) {
      for (const band of BAND_IDS) {
        expect(viewBlocked("then", sequenceOf(field.synth, band), field.manifest)).toBeNull();
      }
    }
  });

  it("follows reduced motion", () => {
    const v = derive(opened(wise as LoadedField), { reducedMotion: true, layout: "wide" });
    expect(v.playback.reduced).toBe(true);
    expect(v.playback.reducedNote).toBe(
      "Reduced motion is on, so frames change only when you step or hold.",
    );
    expect(v.playback.shortcuts).toBe(false);
    expect(derive(opened(wise as LoadedField), { layout: "wide" }).playback.shortcuts).toBe(true);
  });

  it("shows the build in steps, with the counts the engine gave", () => {
    const asked = run(INITIAL_STATE, {
      type: "go",
      place: { kind: "position", ra: 10, dec: 20, name: null },
    });
    const building = run(asked, {
      type: "loadProgress",
      requestId: 1,
      progress: { stage: "fetch", done: 120, total: 258 },
    });
    const v = derive(building);
    expect(v.image.state).toBe("building");
    expect(v.image.build?.steps.map((s) => [s.label, s.value, s.state])).toEqual([
      ["Finding exposures", null, "done"],
      ["Reading exposures", "120 of 258", "doing"],
      ["Stacking", null, "todo"],
    ]);
    expect(v.loadingLine).toBe("Reading 120 of 258");
    expect(v.frameLabel.one).toMatchObject({
      when: "Building this image",
      range: bandRange("all"),
      count: "258 exposures",
    });
    expect(v.playback.why).toBe("Frames can be flipped once the first one is built.");
    expect(v.search.message).toBe("Read as RA 10.0000°, Dec +20.0000°.");
  });

  it("counts down while the engine is busy", () => {
    const asked = run(INITIAL_STATE, {
      type: "go",
      place: { kind: "position", ra: 1, dec: 2, name: null },
    });
    const busy = run(asked, { type: "loadBusy", requestId: 1, retryAt: 20_000 });
    expect(derive(busy, { now: 0 }).image.busy).toEqual({ secondsLeft: 20, canRetry: false });
    expect(derive(busy, { now: 20_000 }).image.busy).toEqual({ secondsLeft: 0, canRetry: true });
    expect(derive(busy).frameLabel.one.when).toBe("Waiting to build");
  });

  it("turns search off while a recorded field stands in for the archive", () => {
    const asked = run(INITIAL_STATE, {
      type: "go",
      place: { kind: "position", ra: 200, dec: 10, name: null },
    });
    const standIn = run(asked, {
      type: "loaded",
      requestId: 1,
      field: wise as LoadedField,
      fallback: true,
    });
    const v = derive(standIn);
    expect(v.notices.archive).toBe(true);
    expect(v.search).toMatchObject({
      disabled: true,
      message: "Search is off while the recorded field is shown.",
    });
    expect(v.chip).toBe("recorded");
    expect(v.title.title).toBe("WISE 0855");
  });

  it("marks 6′ while the recorded copy stands in, whatever size was asked for", () => {
    const asked = run(INITIAL_STATE, {
      type: "go",
      place: { kind: "position", ra: 200, dec: 10, name: null },
      fov: 8,
    });
    const standIn = run(asked, {
      type: "loaded",
      requestId: 1,
      field: wise as LoadedField,
      fallback: true,
    });
    const v = derive(standIn, { engine: "down" });
    expect(v.fovs.filter((f) => f.checked).map((f) => f.id)).toEqual([6]);
    expect(v.fovs.filter((f) => !f.disabled).map((f) => f.id)).toEqual([6]);
  });

  it("shows the moved-object banner only when it is built", () => {
    const state = {
      ...opened(wise as LoadedField),
      mover: { hint: synthetic_hint, from: { ra: 1, dec: 2 }, jumped: false },
    };
    expect(derive(state, {}, { movedBanner: false }).notices.mover).toBeNull();
    expect(derive(state, {}, { movedBanner: true }).notices.mover).toEqual({
      sentence: synthetic_hint.sentence,
      canJump: true,
    });
  });

  it("dates the newest-image chip only when an engine told it", () => {
    expect(derive(INITIAL_STATE).timeline.newest).toBeNull();
    expect(derive(INITIAL_STATE, { newest: "2026-10-05" }).timeline.newest).toBe("5 Oct 2026");
  });

  it("keeps the difference and limits stable between renders, for the blocks' memos", () => {
    const state = run(opened(wise as LoadedField), { type: "setView", view: "difference" });
    const one = derive(state);
    const two = derive(run(state, { type: "setRing", ring: { dx: 3, dy: 3 } }));
    expect(one.field?.difference).not.toBeNull();
    expect(two.field?.difference).toBe(one.field?.difference);
    expect(two.field?.displayLimits).toBe(one.field?.displayLimits);
    expect(two.field?.labels).toBe(one.field?.labels);
  });

  it("lists the legend's No data whenever a frame of the sequence has hatched pixels", () => {
    const v = derive(opened(barnard as LoadedField));
    const sequence = v.field?.sequence as SeqFrame[];
    const any = sequence.some((f) => f.frame.data.some((value) => Number.isNaN(value)));
    expect(v.legend.noData).toBe(any);
  });
});
