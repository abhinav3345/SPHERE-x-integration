/**
 * Recorded answers (extras/derive.ts, rules R1 to R5), checked on the two recorded REAL fields
 * with the REAL answers recorded beside them (public/fixtures/<name>/overlays.json and
 * spectrum.json, copied from cache/fixtures by scripts/sync-contract.mjs).
 *
 * The answers are recorded again from time to time (same format, same substance, a later time),
 * so every expected date, sentence and count below is derived from the envelope the test reads;
 * nothing pins a recording time. Stand-ins that are not real data are named synthetic_*.
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { FieldErrorCode, RecordedAnswer } from "../../api";
import type { Manifest, OverlaysResponse } from "../../contract";
import { decodeFloat16 } from "../../player/float16";
import { gridOf, pixelToSky, skyToPixel } from "../../player/grid";
import { FieldSynth } from "../../player/synth";
import { type Derived, deriveView, type Env } from "../derive";
import { withFeatures } from "../features";
import { shortDate } from "../format";
import {
  type Action,
  INITIAL_STATE,
  type LoadedField,
  placeAt,
  type RecordedId,
  reduce,
  sequenceOf,
  type ViewState,
} from "../model";
import { caveatList } from "../time/rail";
import {
  answersField,
  catalogueMarkers,
  MARKERS_NO_ENGINE,
  modelOf,
  type OverlaysLoad,
  type RecordedLoads,
  recordedNeeded,
  SPECTRUM_NO_ENGINE,
  type SpectrumLoad,
  spectrumAt,
  spectrumFailure,
  spectrumShown,
} from "./derive";
import { SATURATED, spectrumCsv, spectrumFileName, spectrumModel, spectrumVM } from "./spectrum";

const fixturesDir = fileURLToPath(new URL("../../../public/fixtures/", import.meta.url));

interface Recorded {
  /** The recorded field as the bundled copy loads it. */
  field: LoadedField;
  overlays: RecordedAnswer<"overlays">;
  spectrum: RecordedAnswer<"spectrum">;
}

function loadRecorded(name: RecordedId): Recorded | null {
  const dir = join(fixturesDir, name);
  const files = ["manifest.json", "frames.bin", "overlays.json", "spectrum.json"];
  if (!files.every((file) => existsSync(join(dir, file)))) return null;
  const json = (file: string) => JSON.parse(readFileSync(join(dir, file), "utf8"));
  const manifest: Manifest = json("manifest.json");
  const bytes = readFileSync(join(dir, "frames.bin"));
  const synth = new FieldSynth(manifest, decodeFloat16(new Uint8Array(bytes).buffer));
  return {
    field: { manifest, synth, source: "bundled", recorded: name },
    overlays: json("overlays.json"),
    spectrum: json("spectrum.json"),
  };
}

const wiseRecorded = loadRecorded("wise0855");
const barnardRecorded = loadRecorded("barnard");
const haveAnswers = wiseRecorded !== null && barnardRecorded !== null;

const run = (state: ViewState, ...actions: Action[]) => actions.reduce(reduce, state);

/**
 * The recorded field on screen, from the bundled copy or from the engine, with the spectrum panel
 * open (as `?spec=1` opens it) when `panel.spectrum`, in `panel.spectrumMode`.
 */
function opened(
  r: Recorded,
  source: "api" | "bundled",
  panel: Partial<Pick<ViewState, "spectrum" | "spectrumMode">> = {},
  ...actions: Action[]
): ViewState {
  const field: LoadedField = { ...r.field, source };
  const asked = run(INITIAL_STATE, {
    type: "go",
    place: { kind: "recorded", target: r.field.recorded ?? "wise0855" },
    spectrum: panel.spectrum ?? false,
  });
  const shown = run(asked, {
    type: "loaded",
    requestId: asked.request?.id ?? -1,
    field,
    fallback: false,
  });
  const mode: Action[] = panel.spectrumMode
    ? [{ type: "setSpectrumMode", mode: panel.spectrumMode }]
    : [];
  return run(shown, ...mode, ...actions);
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

const derive = (state: ViewState, env: Partial<Env> = {}): Derived =>
  deriveView(state, { ...ENV, ...env }, withFeatures({}));

/** Both recorded answers of a field, loaded (or `null`: no usable file). */
function loaded(
  r: Recorded,
  answers: {
    overlays?: RecordedAnswer<"overlays"> | null;
    spectrum?: RecordedAnswer<"spectrum"> | null;
  } = {},
): RecordedLoads {
  const field = r.field.recorded ?? "wise0855";
  const key = r.field.manifest.key;
  return {
    overlays: {
      phase: "done",
      field,
      key,
      answer: answers.overlays === undefined ? r.overlays : answers.overlays,
    },
    spectrum: {
      phase: "done",
      field,
      key,
      answer: answers.spectrum === undefined ? r.spectrum : answers.spectrum,
    },
  };
}

/** The page's date of a recording, derived from its envelope: "14 Nov 2026". */
const dateOf = (answer: RecordedAnswer) => shortDate(answer.recorded_at.slice(0, 10));
const markersSentence = (answer: RecordedAnswer) =>
  `Catalogue markers were recorded on ${dateOf(answer)}.`;
const spectrumChip = (answer: RecordedAnswer) => `Recorded ${dateOf(answer)}`;

/** The caveat list as the Caveats block builds it. */
const caveatsOf = (v: Derived) =>
  caveatList(v.notices.caveats, v.extras, { onScreen: v.field !== null, catalogueMarkers: true });

/** What the field and ring of a state give spectrumShown and recordedNeeded. */
function fieldOf(r: Recorded, source: "api" | "bundled") {
  const { manifest } = r.field;
  return { manifest, grid: gridOf(manifest), recorded: r.field.recorded, source };
}

const ENGINE_FAILURES: FieldErrorCode[] = [
  "unreachable",
  "timeout",
  "not_found",
  "busy",
  "upstream_unavailable",
  "internal",
];
const OTHER_FAILURES: Array<FieldErrorCode | "unexpected"> = [
  "bad_request",
  "bad_response",
  "unexpected",
];

describe.skipIf(!haveAnswers)("recorded answers on the recorded fields", () => {
  const wise = () => wiseRecorded as Recorded;
  const barnard = () => barnardRecorded as Recorded;
  const both = () => [wise(), barnard()];

  it("belong to their own field: name, key and pipeline as the manifest says", () => {
    for (const r of both()) {
      for (const answer of [r.overlays, r.spectrum]) {
        expect(answer.field).toBe(r.field.recorded);
        expect(answer.key).toBe(r.field.manifest.key);
        expect(answer.pipeline_version).toBe(r.field.manifest.provenance.pipeline_version);
        expect(dateOf(answer)).toMatch(/^\d{1,2} [A-Z][a-z]{2} \d{4}$/);
      }
      expect(r.spectrum.request).toEqual({
        ra: r.field.manifest.request.ra,
        dec: r.field.manifest.request.dec,
      });
    }
  });

  // ------------------------------------------------------------------------------- markers

  it("put the manifest's fixture stars within 0.5 px of their recorded pixels, in every frame", () => {
    for (const r of both()) {
      const { manifest, synth } = r.field;
      const stars = manifest.fixture_stars ?? [];
      expect(stars.length).toBeGreaterThan(0);
      const sequence = sequenceOf(synth, "all");
      const all = catalogueMarkers(r.overlays.response, sequence, gridOf(manifest), manifest);
      for (const star of stars) {
        const marker = all.gaia.find((m) => m.id === star.source_id);
        if (!marker) throw new Error(`${star.source_id} is not marked`);
        expect(marker.xy).toHaveLength(sequence.length);
        for (const xy of marker.xy) {
          if (!xy) throw new Error(`${star.source_id} is missing from a frame`);
          expect(Math.abs(xy.x - star.x)).toBeLessThan(0.5);
          expect(Math.abs(xy.y - star.y)).toBeLessThan(0.5);
        }
        // Through the view model, with the ring on the star (only the ring's neighbours are drawn).
        const { cx, cy } = manifest.grid;
        const ring = { dx: Math.round(star.x - cx), dy: Math.round(star.y - cy) };
        const v = derive(opened(r, "bundled", {}, { type: "setRing", ring }), {
          recorded: loaded(r),
        });
        const drawn = v.extras.markers.gaia.find((m) => m.id === star.source_id);
        if (!drawn) throw new Error(`${star.source_id} is not drawn with the ring on it`);
        for (const xy of drawn.xy) {
          expect(xy).not.toBeNull();
          expect(
            Math.hypot((xy?.x ?? Number.NaN) - star.x, (xy?.y ?? Number.NaN) - star.y),
          ).toBeLessThan(0.5);
        }
        expect(v.extras.markers.recorded).toBe(markersSentence(r.overlays));
      }
    }
  });

  it("follow WISE 0855 along its CatWISE track, near the centre at every visit", () => {
    const r = wise();
    const { manifest } = r.field;
    const grid = gridOf(manifest);
    const v = derive(opened(r, "bundled"), { recorded: loaded(r) });
    expect(v.extras.markers.status).toBe("ready");
    // The fastest tracked CatWISE source of the recording: WISE 0855 itself.
    const tracked = r.overlays.response.catwise.filter((s) => s.track && s.track.length > 0);
    const speed = (s: (typeof tracked)[number]) => Math.hypot(s.pmra ?? 0, s.pmdec ?? 0);
    const mover = [...tracked].sort((a, b) => speed(b) - speed(a))[0];
    const marker = v.extras.markers.catwise.find((m) => m.id === mover.id);
    if (!marker || !v.field) throw new Error("the tracked source is not drawn");
    expect(marker.fast).toBe(true);
    expect(marker.label).toBe(`${(speed(mover) / 1000).toFixed(1)}″/yr`);
    const { cx, cy } = manifest.grid;
    v.field.sequence.forEach((frame, i) => {
      const point = mover.track?.find((p) => p.time_bin === frame.timeBin.id);
      const xy = marker.xy[i];
      if (!point || !xy) throw new Error(`no position at visit ${frame.timeBin.id}`);
      const expected = skyToPixel(grid, point.ra, point.dec);
      expect(xy.x).toBeCloseTo(expected.x, 6);
      expect(xy.y).toBeCloseTo(expected.y, 6);
      // Within one native SPHEREx pixel (two image pixels) of the field centre.
      expect(Math.hypot(xy.x - cx, xy.y - cy)).toBeLessThan(2);
    });
    // It moves west (to the right on screen) from the first visit to the last.
    const xs = marker.xy.map((p) => p?.x ?? Number.NaN);
    expect(xs[xs.length - 1]).toBeGreaterThan(xs[0]);
  });

  it("say once, among the caveats, that the markers were recorded, with the date", () => {
    for (const r of both()) {
      const v = derive(opened(r, "bundled"), { recorded: loaded(r) });
      expect(v.extras.markers).toMatchObject({
        status: "ready",
        note: null,
        recorded: markersSentence(r.overlays),
      });
      const caveats = caveatsOf(v);
      expect(caveats.filter((c) => c === markersSentence(r.overlays))).toHaveLength(1);
      expect(caveats).not.toContain(MARKERS_NO_ENGINE);
      // The caveat names no other date and no other answer: it is the envelope's.
      expect(caveats.at(-1)).toBe(markersSentence(r.overlays));
    }
  });

  // ------------------------------------------------------------------------------ spectrum

  it("show WISE 0855's recorded spectrum, every point of it, labelled with its date", () => {
    const r = wise();
    const { manifest } = r.field;
    const v = derive(opened(r, "bundled", { spectrum: true }), { recorded: loaded(r) });
    const model = spectrumModel(r.spectrum.response, manifest);
    expect(v.extras.spectrum).toEqual({
      open: true,
      ...spectrumVM(model, "chart"),
      recorded: spectrumChip(r.spectrum),
    });
    expect(v.extras.spectrum.status).toBe("ready");
    expect(r.spectrum.response.state).not.toBe("saturated");
    // The envelope's points, all of them: one per exposure, and the binned ones.
    const finite = (p: { lam: number; flux_ujy: number; err_ujy: number }) =>
      [p.lam, p.flux_ujy, p.err_ujy].every(Number.isFinite);
    expect(v.extras.spectrum.points).toHaveLength(r.spectrum.response.points.filter(finite).length);
    expect(v.extras.spectrum.binned).toHaveLength(r.spectrum.response.binned.filter(finite).length);
    expect(v.extras.spectrum.points.length).toBeGreaterThan(0);
    expect(v.extras.spectrum.visits.map((visit) => visit.label)).toEqual(
      model.visits.map((visit) => visit.label),
    );
    // The table view shows the same answer.
    const table = derive(opened(r, "bundled", { spectrum: true, spectrumMode: "table" }), {
      recorded: loaded(r),
    });
    expect(table.extras.spectrum.points).toEqual(v.extras.spectrum.points);
    expect(table.extras.spectrum.recorded).toBe(spectrumChip(r.spectrum));
  });

  it("show Barnard's Star's recorded spectrum as saturated, labelled with its date", () => {
    const r = barnard();
    expect(r.spectrum.response.state).toBe("saturated");
    const v = derive(opened(r, "bundled", { spectrum: true }), { recorded: loaded(r) });
    expect(v.extras.spectrum).toMatchObject({
      open: true,
      status: "saturated",
      messages: [SATURATED],
      points: [],
      binned: [],
      recorded: spectrumChip(r.spectrum),
    });
  });

  it("hand over exactly the rows shown as CSV, in a file named as recorded", () => {
    for (const r of both()) {
      const field = fieldOf(r, "bundled");
      const shown = spectrumShown({
        field,
        ring: { dx: 0, dy: 0 },
        spectrum: { phase: "idle" },
        recorded: loaded(r).spectrum,
      });
      if (shown.kind !== "answer") throw new Error("the recorded spectrum is not shown");
      expect(shown.recorded).toBe(r.spectrum);
      const model = modelOf(shown.data, r.field.manifest);
      const v = derive(opened(r, "bundled", { spectrum: true }), { recorded: loaded(r) });
      const rows = v.extras.spectrum.points.length + v.extras.spectrum.binned.length;
      expect(model.rows).toHaveLength(rows);
      expect(spectrumCsv(model).trim().split("\n")).toHaveLength(1 + rows);
      expect(spectrumFileName(model, shown.recorded?.recorded_at ?? null)).toBe(
        `${spectrumFileName(model).replace(/\.csv$/, "")}-recorded-${r.spectrum.recorded_at.slice(0, 10)}.csv`,
      );
    }
  });

  // ---------------------------------------------------------------------------- rule R2

  it("R2: with the engine answering, live answers are shown and no recorded file is asked for", () => {
    for (const r of both()) {
      const { manifest } = r.field;
      const state = opened(r, "api", { spectrum: true });
      const at = spectrumAt(manifest, gridOf(manifest), state.ring);
      // Real engine answers, standing for the live ones: what the engine answered for this field.
      const overlays: OverlaysLoad = {
        phase: "ready",
        key: manifest.key,
        data: r.overlays.response,
      };
      const spectrum: SpectrumLoad = { phase: "ready", at, data: r.spectrum.response };
      expect(
        recordedNeeded(state, withFeatures({}), fieldOf(r, "api"), overlays, spectrum),
      ).toEqual({ overlays: false, spectrum: false });
      // Even with the recorded answers at hand, nothing recorded is shown or said.
      const v = derive(state, { overlays, spectrum, recorded: loaded(r) });
      expect(v.extras.markers.status).toBe("ready");
      expect(v.extras.markers.recorded).toBeUndefined();
      expect(v.extras.spectrum.recorded).toBeNull();
      expect(caveatsOf(v)).not.toContain(markersSentence(r.overlays));
      // While the engine is still answering, nothing is asked for either.
      const waiting = recordedNeeded(
        state,
        withFeatures({}),
        fieldOf(r, "api"),
        { phase: "loading", key: manifest.key },
        { phase: "loading", at, progress: null },
      );
      expect(waiting).toEqual({ overlays: false, spectrum: false });
      const measuring = derive(state, {
        overlays: { phase: "loading", key: manifest.key },
        spectrum: { phase: "loading", at, progress: null },
        recorded: loaded(r),
      });
      expect(measuring.extras.markers.status).toBe("loading");
      expect(measuring.extras.spectrum).toMatchObject({
        status: "loading",
        messages: ["Measuring…"],
        recorded: null,
      });
    }
  });

  it("R2: with the field bundled, both recorded answers are asked for, used and labelled", () => {
    for (const r of both()) {
      const state = opened(r, "bundled", { spectrum: true });
      const none: OverlaysLoad = { phase: "idle" };
      const idle: SpectrumLoad = { phase: "idle" };
      expect(recordedNeeded(state, withFeatures({}), fieldOf(r, "bundled"), none, idle)).toEqual({
        overlays: true,
        spectrum: true,
      });
      const v = derive(state, { recorded: loaded(r) });
      expect(v.extras.markers.recorded).toBe(markersSentence(r.overlays));
      expect(v.extras.spectrum.recorded).toBe(spectrumChip(r.spectrum));
      // Markers off, or the part not built: the overlays file is not asked for.
      const off = run(state, { type: "setMarkers", on: false });
      expect(
        recordedNeeded(off, withFeatures({}), fieldOf(r, "bundled"), none, idle).overlays,
      ).toBe(false);
      const unbuilt = withFeatures({ catalogueMarkers: false, spectrum: false });
      expect(recordedNeeded(state, unbuilt, fieldOf(r, "bundled"), none, idle)).toEqual({
        overlays: false,
        spectrum: false,
      });
      // A live build (not a recorded field) has no recorded answers.
      const live = { ...fieldOf(r, "bundled"), recorded: null };
      expect(recordedNeeded(state, withFeatures({}), live, none, idle)).toEqual({
        overlays: false,
        spectrum: false,
      });
    }
  });

  it("R2: when the engine's request fails, the recorded answer stands in, labelled", () => {
    const r = wise();
    const { manifest } = r.field;
    const state = opened(r, "api", { spectrum: true });
    const at = spectrumAt(manifest, gridOf(manifest), state.ring);
    for (const code of ENGINE_FAILURES) {
      const overlays: OverlaysLoad = { phase: "failed", key: manifest.key, code };
      const spectrum: SpectrumLoad = { phase: "failed", at, code };
      const field = fieldOf(r, "api");
      expect(recordedNeeded(state, withFeatures({}), field, overlays, spectrum)).toEqual({
        overlays: true,
        spectrum: true,
      });
      const v = derive(state, { overlays, spectrum, recorded: loaded(r) });
      expect(v.extras.markers).toMatchObject({
        status: "ready",
        recorded: markersSentence(r.overlays),
      });
      expect(v.extras.spectrum).toMatchObject({
        status: "ready",
        recorded: spectrumChip(r.spectrum),
      });
    }
    // A request the engine refused, or an answer that is not the contract's: no stand-in.
    for (const code of OTHER_FAILURES) {
      const overlays: OverlaysLoad = { phase: "failed", key: manifest.key, code };
      const spectrum: SpectrumLoad = { phase: "failed", at, code };
      expect(
        recordedNeeded(state, withFeatures({}), fieldOf(r, "api"), overlays, spectrum),
      ).toEqual({ overlays: false, spectrum: false });
      const v = derive(state, { overlays, spectrum, recorded: loaded(r) });
      expect(v.extras.markers).toMatchObject({ status: "unavailable" });
      expect(v.extras.markers.recorded).toBeUndefined();
      expect(v.extras.spectrum).toMatchObject({
        status: "unavailable",
        messages: [spectrumFailure(code)],
        recorded: null,
      });
    }
  });

  it("R2: a live overlays answer missing a catalogue gives way to the recorded one", () => {
    const r = wise();
    const { manifest } = r.field;
    const state = opened(r, "api");
    const synthetic_live = (upstreams: OverlaysResponse["upstreams"]): OverlaysLoad => ({
      phase: "ready",
      key: manifest.key,
      data: { ...r.overlays.response, upstreams },
    });
    const halfDown = synthetic_live({ gaia: "ok", catwise: "unavailable" });
    const allDown = synthetic_live({ gaia: "unavailable", catwise: "unavailable" });
    const stale = synthetic_live({ gaia: "stale", catwise: "ok" });
    const idle: SpectrumLoad = { phase: "idle" };
    const field = fieldOf(r, "api");
    for (const live of [halfDown, allDown]) {
      expect(recordedNeeded(state, withFeatures({}), field, live, idle).overlays).toBe(true);
      const v = derive(state, { overlays: live, recorded: loaded(r) });
      expect(v.extras.markers).toMatchObject({
        status: "ready",
        note: null,
        recorded: markersSentence(r.overlays),
      });
      expect(v.extras.markers.catwise.length).toBeGreaterThan(0);
    }
    // Every catalogue answered (stale counts): the live answer stays, nothing is asked for.
    expect(recordedNeeded(state, withFeatures({}), field, stale, idle).overlays).toBe(false);
    expect(derive(state, { overlays: stale, recorded: loaded(r) }).extras.markers.recorded).toBe(
      undefined,
    );
    // A recorded answer no better than the live one is not used.
    const synthetic_recorded: RecordedAnswer<"overlays"> = {
      ...r.overlays,
      response: { ...r.overlays.response, upstreams: { gaia: "ok", catwise: "unavailable" } },
    };
    const same = derive(state, {
      overlays: halfDown,
      recorded: loaded(r, { overlays: synthetic_recorded }),
    });
    expect(same.extras.markers).toMatchObject({
      status: "ready",
      note: "CatWISE could not be reached: only Gaia DR3 stars are marked.",
    });
    expect(same.extras.markers.recorded).toBeUndefined();
  });

  it("R2: a bundled field uses its recorded markers even while a live answer of its key is held", () => {
    // The field was first shown from the engine with both catalogues answered; the engine then
    // went away and the field was opened again from the bundled copy. The hook still holds that
    // live answer, but none can be had now: the recorded markers stand in, labelled.
    for (const r of both()) {
      const { manifest } = r.field;
      const held: OverlaysLoad = { phase: "ready", key: manifest.key, data: r.overlays.response };
      const state = opened(r, "bundled");
      const idle: SpectrumLoad = { phase: "idle" };
      const field = fieldOf(r, "bundled");
      expect(recordedNeeded(state, withFeatures({}), field, held, idle).overlays).toBe(true);
      const v = derive(state, { overlays: held, recorded: loaded(r) });
      expect(v.extras.markers).toMatchObject({
        status: "ready",
        note: null,
        recorded: markersSentence(r.overlays),
      });
      expect(caveatsOf(v)).toContain(markersSentence(r.overlays));
      expect(caveatsOf(v)).not.toContain(MARKERS_NO_ENGINE);
    }
  });

  it("R2: a recorded field shown instead of the place asked for uses no recorded answer", () => {
    for (const r of both()) {
      // RW Aurigae's position asked for with no engine: the recorded field is shown instead.
      const asked = run(INITIAL_STATE, {
        type: "go",
        place: placeAt(76.9566, 30.4013, 6, null),
        spectrum: true,
      });
      const standIn = run(asked, {
        type: "loaded",
        requestId: asked.request?.id ?? -1,
        field: r.field,
        fallback: true,
      });
      expect(answersField(standIn)).toBeNull();
      expect(answersField(opened(r, "bundled"))).toBe(r.field.recorded);
      const field = { ...fieldOf(r, "bundled"), recorded: answersField(standIn) };
      const none: OverlaysLoad = { phase: "idle" };
      const idle: SpectrumLoad = { phase: "idle" };
      expect(recordedNeeded(standIn, withFeatures({}), field, none, idle)).toEqual({
        overlays: false,
        spectrum: false,
      });
      // Even with both recorded answers at hand: the page says what it said before them.
      const v = derive(standIn, { recorded: loaded(r) });
      expect(v.extras.markers.recorded).toBeUndefined();
      expect(v.extras.markers).toMatchObject({ status: "unavailable", note: MARKERS_NO_ENGINE });
      expect(v.extras.spectrum).toMatchObject({
        status: "unavailable",
        messages: [SPECTRUM_NO_ENGINE],
        recorded: null,
      });
      expect(caveatsOf(v)).not.toContain(markersSentence(r.overlays));
    }
  });

  // ---------------------------------------------------------------------------- rule R3

  it("R1: a recorded spectrum whose request is not the manifest's is used nowhere", () => {
    const r = wise();
    const { manifest } = r.field;
    const { cx, cy } = manifest.grid;
    // A stand-in: the real envelope with its request moved 10 image pixels from the centre.
    const moved = pixelToSky(gridOf(manifest), cx + 10, cy);
    const synthetic_moved: RecordedAnswer<"spectrum"> = {
      ...r.spectrum,
      request: { ra: moved.ra, dec: moved.dec },
    };
    for (const ring of [
      { dx: 0, dy: 0 },
      { dx: 10, dy: 0 },
    ]) {
      const state = opened(r, "bundled", { spectrum: true }, { type: "setRing", ring });
      expect(state.ring).toEqual(ring);
      const v = derive(state, { recorded: loaded(r, { spectrum: synthetic_moved }) });
      expect(v.extras.spectrum).toMatchObject({
        status: "unavailable",
        messages: [SPECTRUM_NO_ENGINE],
        recorded: null,
      });
    }
  });

  it("R3: the recorded spectrum only on the pixel it was recorded for; back with the ring", () => {
    for (const r of both()) {
      const state = opened(r, "bundled", { spectrum: true });
      for (const ring of [
        { dx: 1, dy: 0 },
        { dx: 0, dy: -1 },
        { dx: -1, dy: 1 },
      ]) {
        const away = run(state, { type: "setRing", ring });
        const none: OverlaysLoad = { phase: "idle" };
        const idle: SpectrumLoad = { phase: "idle" };
        expect(recordedNeeded(away, withFeatures({}), fieldOf(r, "bundled"), none, idle)).toEqual({
          overlays: true,
          spectrum: false,
        });
        const v = derive(away, { recorded: loaded(r) });
        expect(v.extras.spectrum).toMatchObject({
          status: "unavailable",
          messages: [SPECTRUM_NO_ENGINE],
          points: [],
          recorded: null,
        });
        // The markers are the field's, not the ring's: still the recorded ones.
        expect(v.extras.markers.recorded).toBe(markersSentence(r.overlays));
        // Back on the recorded position (Recentre opens the recorded field again, ring centred).
        const back = run(away, { type: "setRing", ring: { dx: 0, dy: 0 } });
        expect(derive(back, { recorded: loaded(r) }).extras.spectrum.recorded).toBe(
          spectrumChip(r.spectrum),
        );
      }
    }
    // With the engine's request failed one pixel away: what the page says today for that failure.
    const r = wise();
    const { manifest } = r.field;
    const away = opened(r, "api", { spectrum: true }, { type: "setRing", ring: { dx: 1, dy: 0 } });
    const at = spectrumAt(manifest, gridOf(manifest), away.ring);
    const failed: SpectrumLoad = { phase: "failed", at, code: "unreachable" };
    const v = derive(away, { spectrum: failed, recorded: loaded(r) });
    expect(v.extras.spectrum).toMatchObject({
      status: "unavailable",
      messages: [spectrumFailure("unreachable")],
      recorded: null,
    });
  });

  // ---------------------------------------------------------------------------- rule R5

  it("R5: no file, or an envelope of another field, leaves the page as it is today", () => {
    for (const r of both()) {
      const other = r === wise() ? barnard() : wise();
      const state = opened(r, "bundled", { spectrum: true });
      const today = derive(state);
      const missing = derive(state, {
        recorded: loaded(r, { overlays: null, spectrum: null }),
      });
      const foreign = derive(state, {
        recorded: loaded(r, { overlays: other.overlays, spectrum: other.spectrum }),
      });
      for (const v of [missing, foreign]) {
        expect(v.extras.markers).toEqual(today.extras.markers);
        expect(v.extras.spectrum).toEqual(today.extras.spectrum);
        expect(caveatsOf(v)).toEqual(caveatsOf(today));
      }
      expect(today.extras.markers.note).toBe(MARKERS_NO_ENGINE);
      expect(today.extras.spectrum.messages).toEqual([SPECTRUM_NO_ENGINE]);
    }
  });

  it("say nothing while a recorded file is on its way: no marker, no sentence", () => {
    const r = wise();
    const { manifest } = r.field;
    const state = opened(r, "bundled", { spectrum: true });
    const coming: RecordedLoads = {
      overlays: { phase: "loading", field: "wise0855", key: manifest.key },
      spectrum: { phase: "loading", field: "wise0855", key: manifest.key },
    };
    const v = derive(state, { recorded: coming });
    expect(v.extras.markers).toMatchObject({ status: "loading", note: null, gaia: [] });
    expect(v.extras.spectrum).toMatchObject({ status: "loading", messages: [], recorded: null });
    expect(caveatsOf(v)).toEqual(caveatsOf(derive(state)).filter((c) => c !== MARKERS_NO_ENGINE));
  });
});
