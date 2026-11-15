/**
 * The four extras, checked on the recorded REAL fields in public/fixtures. Engine answers that
 * the fields do not carry (overlays, spectra) are small stand-ins named synthetic_*: their sky
 * positions are the fixtures' own Gaia DR3 stars, their fluxes are arithmetic only.
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type {
  Manifest,
  OverlaysResponse,
  Plane,
  SpectrumPoint,
  SpectrumResponse,
} from "../../contract";
import { decodeFloat16 } from "../../player/float16";
import { gridOf } from "../../player/grid";
import { contractWaveBins, LEGACY_PAIRS, PRESETS_FILE } from "../../player/presets";
import { pooledLimits } from "../../player/render";
import { FieldSynth } from "../../player/synth";
import { type Derived, deriveView, type Env } from "../derive";
import { withFeatures } from "../features";
import {
  type Action,
  BAND_IDS,
  BANDS,
  type BandId,
  frameLabels,
  INITIAL_STATE,
  type LoadedField,
  type RecordedId,
  reduce,
  sequenceLimits,
  sequenceOf,
  type ViewState,
} from "../model";
import { chartGeometry, fluxRange, niceStep, outsideNote, seriesFor, tickLabel } from "./chart";
import {
  catalogueMarkers,
  julianYear,
  MARKERS_NO_ENGINE,
  monthSpan,
  NEIGHBOUR_ARCSEC,
  NO_OLDER_IMAGE,
  RGB_RANGES,
  SPECTRUM_NO_ENGINE,
  spectrumAt,
  staleWithoutTrack,
  thenAndNowOf,
  threeColourFrames,
} from "./derive";
import {
  INDICATIVE,
  incompleteSentence,
  NO_SPECTRUM,
  neighbourSentence,
  SATURATED,
  spectrumCsv,
  spectrumModel,
  spectrumVM,
} from "./spectrum";

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

/** The bytes of an array of pixels: equal bytes are equal pixels, no-data (NaN) included. */
const bytesOf = (data: Float32Array) => Buffer.from(data.buffer, data.byteOffset, data.byteLength);
const samePixels = (a: Float32Array, b: Float32Array) => bytesOf(a).equals(bytesOf(b));

const run = (state: ViewState, ...actions: Action[]) => actions.reduce(reduce, state);

function opened(field: LoadedField, extra: Partial<ViewState> = {}): ViewState {
  const asked = run(
    { ...INITIAL_STATE, ...extra },
    { type: "go", place: { kind: "recorded", target: field.recorded ?? "wise0855" } },
  );
  return run(asked, { type: "loaded", requestId: asked.request?.id ?? -1, field, fallback: false });
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

const derive = (state: ViewState, env: Partial<Env> = {}, flags = {}): Derived =>
  deriveView(state, { ...ENV, ...env }, withFeatures(flags));

// ---------------------------------------------------------------------------------------------

describe("three-colour", () => {
  it("labels the channels with the design's words, which match presets.json", () => {
    const rgb = PRESETS_FILE.presets.find((preset) => preset.id === "rgb");
    if (rgb?.kind !== "rgb") throw new Error("no rgb preset");
    const span = (detectors: number[] | undefined) => {
      const ds = PRESETS_FILE.detectors.filter((d) => detectors?.includes(d.det));
      return [Math.min(...ds.map((d) => d.lam_min)), Math.max(...ds.map((d) => d.lam_max))];
    };
    const [r0, r1] = span(rgb.r.detectors);
    const [g0, g1] = span(rgb.g.detectors);
    const [b0, b1] = span(rgb.b.detectors);
    expect(RGB_RANGES.r).toBe(`${r0.toFixed(1)} to ${r1.toFixed(1)} µm`);
    expect(RGB_RANGES.g).toBe(`${g0.toFixed(1)} to ${g1.toFixed(1)} µm`);
    expect(RGB_RANGES.b).toBe(`${b0.toFixed(2)} to ${b1.toFixed(2)} µm`);
  });

  it.skipIf(!haveFixtures)("gives every visit its three channels on one scale each", () => {
    const synth = (wise as LoadedField).synth;
    const frames = threeColourFrames(synth);
    expect(frames).toHaveLength(4);
    expect(threeColourFrames(synth)).toBe(frames);
    for (const pick of ["r", "g", "b"] as const) {
      const withData = frames.filter((f) => f[pick].limits !== null).map((f) => f[pick].limits);
      expect(withData.length).toBeGreaterThan(0);
      expect(new Set(withData).size).toBe(1); // pooled over the whole sequence
    }
  });

  it.skipIf(!haveFixtures)(
    "states each visit's real mix: whole range, all exposures, partial when a channel lacks bins",
    () => {
      for (const field of [wise, barnard] as LoadedField[]) {
        const rgb = sequenceOf(field.synth, "rgb");
        const all = sequenceOf(field.synth, "all");
        // The three channels together are the detectors D1 to D6: the same facts as All.
        expect(rgb.map((f) => f.frame.nExposures)).toEqual(all.map((f) => f.frame.nExposures));
        expect(rgb.map((f) => f.partial)).toEqual(all.map((f) => f.partial));
        const labels = frameLabels(rgb, field.manifest);
        expect(labels.map((l) => l.range)).toEqual(
          frameLabels(all, field.manifest).map((l) => l.range),
        );
      }
      const rgb = sequenceOf((wise as LoadedField).synth, "rgb");
      expect(rgb.map((f) => f.partial)).toEqual([true, false, true, false]);
    },
  );

  it.skipIf(!haveFixtures)("fills vm.extras.threeColour only in the three-colour band", () => {
    const state = opened(wise as LoadedField);
    expect(derive(state).extras.threeColour.frames).toBeNull();
    const v = derive(run(state, { type: "setBand", band: "rgb" }));
    expect(v.legend.rgb).toBe(true);
    expect(v.extras.threeColour.frames).toHaveLength(v.field?.sequence.length ?? -1);
    expect(v.extras.threeColour.ranges).toEqual(RGB_RANGES);
  });
});

// ---------------------------------------------------------------------------------------------

describe("Then and now", () => {
  it.skipIf(!haveFixtures)("says so when a field has no older survey image", () => {
    const bare = withoutOlderSurveys(wise as LoadedField);
    const then = thenAndNowOf(bare.synth, "cold");
    expect(then).toEqual({ status: "none", note: NO_OLDER_IMAGE, older: null, sphx: null });
    const v = derive(opened(bare));
    expect(v.views.find((o) => o.id === "then")?.disabled).toBe(true);
    expect(v.extras.thenAndNow.status).toBe("none");
    // A link that names the view opens Blink on such a field.
    expect(derive(run(opened(bare), { type: "setView", view: "then" })).field?.view).toBe("blink");
  });

  // The older-survey planes of the recorded fields (pipeline 0.3.0), as their manifests state them.
  const OLDER = {
    wise0855: {
      W1: ["2010-05-03", "2010-11-13", "WISE W1, 2010", "May to Nov 2010"],
      W2: ["2010-05-03", "2010-11-13", "WISE W2, 2010", "May to Nov 2010"],
      J: ["1998-12-28", "1998-12-28", "2MASS J, 1998", "Dec 1998"],
      H: ["1998-12-28", "1998-12-28", "2MASS H, 1998", "Dec 1998"],
      Ks: ["1998-12-28", "1998-12-28", "2MASS Ks, 1998", "Dec 1998"],
    },
    barnard: {
      W1: ["2010-03-18", "2010-09-19", "WISE W1, 2010", "Mar to Sep 2010"],
      W2: ["2010-03-18", "2010-09-19", "WISE W2, 2010", "Mar to Sep 2010"],
      J: ["2000-05-28", "2000-05-28", "2MASS J, 2000", "May 2000"],
      H: ["2000-05-28", "2000-05-28", "2MASS H, 2000", "May 2000"],
      Ks: ["2000-05-28", "2000-05-28", "2MASS Ks, 2000", "May 2000"],
    },
  } as const;
  type OlderBand = keyof (typeof OLDER)["wise0855"];

  /**
   * presets.json legacy_pairs: W1 with D4, W2 with Cold objects, J and H with D2 (J comes first),
   * Ks with D3. A band with no older image of its own is shown the field's first, WISE W1, with D4.
   */
  const PAIRED: Record<BandId, { older: OlderBand; preset: BandId; own: boolean }> = {
    d1: { older: "W1", preset: "d4", own: false },
    d2: { older: "J", preset: "d2", own: true },
    d3: { older: "Ks", preset: "d3", own: true },
    d4: { older: "W1", preset: "d4", own: true },
    d5: { older: "W1", preset: "d4", own: false },
    d6: { older: "W1", preset: "d4", own: false },
    all: { older: "W1", preset: "d4", own: false },
    cold: { older: "W2", preset: "cold", own: true },
    rgb: { older: "W1", preset: "d4", own: false },
  };

  /** The SPHEREx stacks the pairings show: range, exposures over every visit, months. */
  const STACKS: Record<RecordedId, Partial<Record<BandId, [string, string, string]>>> = {
    wise0855: {
      d2: ["SPHEREx 1.10 to 1.65 µm", "47 exposures", "May 2025 to May 2026"],
      d3: ["SPHEREx 1.64 to 2.42 µm", "45 exposures", "May 2025 to May 2026"],
      d4: ["SPHEREx 2.42 to 3.82 µm", "36 exposures", "May 2025 to May 2026"],
      cold: ["SPHEREx 3.96 to 5.00 µm", "84 exposures", "May 2025 to May 2026"],
    },
    barnard: {
      d2: ["SPHEREx 1.10 to 1.65 µm", "59 exposures", "Aug 2025 to Sep 2026"],
      d3: ["SPHEREx 1.64 to 2.42 µm", "59 exposures", "Aug 2025 to Aug 2026"],
      d4: ["SPHEREx 2.42 to 3.82 µm", "59 exposures", "Aug 2025 to Sep 2026"],
      cold: ["SPHEREx 3.96 to 5.00 µm", "103 exposures", "Aug 2025 to Sep 2026"],
    },
  };

  it.skipIf(!haveFixtures)("holds five older-survey images on each recorded field", () => {
    expect(LEGACY_PAIRS.map((pair) => [pair.band, pair.spherex_preset])).toEqual([
      ["W1", "d4"],
      ["W2", "cold"],
      ["J", "d2"],
      ["H", "d2"],
      ["Ks", "d3"],
    ]);
    for (const field of [wise, barnard] as LoadedField[]) {
      const older = field.synth.legacyPlanes();
      const recorded = OLDER[field.recorded as RecordedId];
      expect(older.map((plane) => [plane.mission, plane.band])).toEqual([
        ["AllWISE", "W1"],
        ["AllWISE", "W2"],
        ["2MASS", "J"],
        ["2MASS", "H"],
        ["2MASS", "Ks"],
      ]);
      for (const plane of older) {
        const [start, end] = recorded[plane.band as OlderBand];
        expect([plane.date_start, plane.date_end, plane.scaled]).toEqual([
          start,
          end,
          "field_stars",
        ]);
      }
    }
  });

  it.skipIf(!haveFixtures)(
    "is offered and ready on both recorded fields, from the engine and from the bundled copy",
    () => {
      for (const field of [wise, barnard] as LoadedField[]) {
        for (const [source, engine] of [
          ["api", "up"],
          ["bundled", "down"],
        ] as const) {
          const state = opened({ ...field, source });
          const before = derive(state, { engine });
          expect(before.views.find((o) => o.id === "then")?.disabled).toBe(false);
          const v = derive(run(state, { type: "setView", view: "then" }), { engine });
          expect(v.field?.view).toBe("then");
          expect(v.extras.thenAndNow.status).toBe("ready");
          expect(v.frameLabel.kind).toBe("two");
          expect(v.readout.value).toBe("");
          const then = v.extras.thenAndNow;
          expect(v.image.pairAria).toEqual({
            a: `Image from another survey: ${then.older?.title}`,
            b: `SPHEREx frame, ${then.sphx?.title.replace(/^SPHEREx /, "")}, ${then.sphx?.dates}`,
          });
        }
      }
    },
  );

  it.skipIf(!haveFixtures)(
    "pairs each band with its older image as presets.json says, titled and dated from the manifest",
    () => {
      for (const field of [wise, barnard] as LoadedField[]) {
        const id = field.recorded as RecordedId;
        for (const band of BAND_IDS) {
          const paired = PAIRED[band];
          const [, , title, dates] = OLDER[id][paired.older];
          const then = thenAndNowOf(field.synth, band);
          expect(then.status).toBe("ready");
          expect(then.older).toMatchObject({ title, dates });
          expect([then.sphx?.title, then.sphx?.exposures, then.sphx?.dates]).toEqual(
            STACKS[id][paired.preset],
          );
          expect(then.note).toBe(
            paired.own
              ? null
              : `No older survey image matches ${BANDS[band].spoken}. Then and now pairs WISE W1 with D4.`,
          );
        }
      }
    },
  );

  it.skipIf(!haveFixtures)(
    "shows the older image as recorded beside one SPHEREx stack of the paired band, each on its own scale",
    () => {
      for (const field of [wise, barnard] as LoadedField[]) {
        for (const band of ["cold", "all", "d2", "d3"] as const) {
          const { older: olderBand, preset } = PAIRED[band];
          const plane = field.synth.legacyPlanes().find((p) => p.band === olderBand);
          if (!plane) throw new Error(`no ${olderBand} plane`);
          const then = thenAndNowOf(field.synth, band);
          if (!then.older || !then.sphx) throw new Error("Then and now is not ready");
          const olderData = field.synth.planeData(plane);
          const stack = field.synth.stackFor(preset);
          expect(samePixels(then.older.data, olderData)).toBe(true);
          expect(then.older.limits).toEqual(
            pooledLimits([{ data: olderData, sigma: plane.sigma }]),
          );
          expect(samePixels(then.sphx.data, stack.data)).toBe(true);
          expect(then.sphx.limits).toEqual(pooledLimits([stack]));
          // Never one scale for both, and never the blink sequence's scale.
          expect(then.older.limits).not.toEqual(then.sphx.limits);
          expect(then.older.limits).not.toEqual(sequenceLimits(sequenceOf(field.synth, band)));
          // Every visit in the stack: its exposures are the band's over the whole sequence.
          const exposures = sequenceOf(field.synth, preset).reduce(
            (sum, f) => sum + f.frame.nExposures,
            0,
          );
          expect(then.sphx.exposures).toBe(`${exposures} exposures`);
        }
      }
    },
  );

  it.skipIf(!haveFixtures)(
    "never lets an older image into a SPHEREx frame, stack, scale, three-colour frame or difference",
    () => {
      for (const field of [wise, barnard] as LoadedField[]) {
        const bare = withoutOlderSurveys(field);
        expect(bare.manifest.planes.length).toBe(field.manifest.planes.length - 5);
        for (const band of BAND_IDS) {
          const withOlder = sequenceOf(field.synth, band);
          const without = sequenceOf(bare.synth, band);
          expect(withOlder.map((f) => [f.frame.nExposures, f.frame.waveBins, f.partial])).toEqual(
            without.map((f) => [f.frame.nExposures, f.frame.waveBins, f.partial]),
          );
          withOlder.forEach((f, i) => {
            expect(samePixels(f.frame.data, without[i].frame.data)).toBe(true);
            expect(f.frame.sigma).toBe(without[i].frame.sigma);
          });
          expect(sequenceLimits(withOlder)).toEqual(sequenceLimits(without));
          if (band !== "rgb") {
            expect(
              samePixels(field.synth.stackFor(band).data, bare.synth.stackFor(band).data),
            ).toBe(true);
          }
        }
        const rgb = threeColourFrames(field.synth);
        const rgbBare = threeColourFrames(bare.synth);
        rgb.forEach((frame, i) => {
          for (const pick of ["r", "g", "b"] as const) {
            expect(samePixels(frame[pick].data, rgbBare[i][pick].data)).toBe(true);
            expect(frame[pick].limits).toEqual(rgbBare[i][pick].limits);
          }
        });
        const difference = (f: LoadedField) =>
          derive(run(opened(f), { type: "setView", view: "difference" })).field?.difference;
        const a = difference(field);
        const b = difference(bare);
        if (!a || !b) throw new Error("no difference");
        expect(samePixels(a.data, b.data)).toBe(true);
        expect(a.sigma).toBe(b.sigma);
      }
    },
  );

  /** A 2 x 2 field: two visits in D6 and one AllWISE W2 plane. Arithmetic only. */
  function synthetic_then(band: string) {
    const bins = contractWaveBins();
    const plane = (index: number, extra: Partial<Plane>): Plane => ({
      index,
      kind: "sci",
      mission: "SPHEREx",
      time_bin: 0,
      wave_bin: 20,
      band: null,
      lam_min: bins[20].lam_min,
      lam_max: bins[20].lam_max,
      lam_eff: 4.5,
      n_exposures: 10,
      sigma: 0.1,
      mjd_mid: 60800,
      date_start: "2025-05-05",
      date_end: "2025-05-06",
      offset: index * 8,
      ...extra,
    });
    const planes = [
      plane(0, {}),
      plane(1, { time_bin: 1, date_start: "2025-11-07", date_end: "2025-11-14" }),
      plane(2, {
        kind: "legacy",
        mission: "AllWISE",
        time_bin: null,
        wave_bin: null,
        band,
        lam_min: 4.0,
        lam_max: 5.3,
        date_start: "2010-05-01",
        date_end: "2010-11-20",
        scaled: "field_stars",
      }),
    ];
    const manifest = {
      ...(wise as LoadedField).manifest,
      grid: { ...(wise as LoadedField).manifest.grid, nx: 2, ny: 2, cx: 0.5, cy: 0.5 },
      time_bins: [0, 1].map((id) => ({
        ...(wise as LoadedField).manifest.time_bins[id],
        id,
      })),
      wave_bins: bins,
      planes,
    } as Manifest;
    const synthetic_values = new Float32Array([1, 1, 1, 1, 3, 3, 3, 3, 50, 60, 70, 80]);
    return new FieldSynth(manifest, synthetic_values);
  }

  it.skipIf(!haveFixtures)(
    "pairs the older image with one SPHEREx stack of its band, each on its own scale",
    () => {
      const synth = synthetic_then("W2");
      const then = thenAndNowOf(synth, "cold");
      expect(then.status).toBe("ready");
      expect(then.note).toBeNull();
      expect(then.older?.title).toBe("WISE W2, 2010");
      expect(then.older?.dates).toBe("May to Nov 2010");
      expect(Array.from(then.older?.data ?? [])).toEqual([50, 60, 70, 80]);
      // Both visits in one stack; the older image's 50 to 80 never reach it.
      expect(Array.from(then.sphx?.data ?? [])).toEqual([2, 2, 2, 2]);
      expect(then.sphx?.exposures).toBe("20 exposures");
      expect(then.sphx?.dates).toBe("May to Nov 2025");
      expect(then.older?.limits).not.toBe(then.sphx?.limits);
      // A band with no older image of its own: the pairing shown is named.
      const other = thenAndNowOf(synth, "d1");
      expect(other.note).toBe(
        "No older survey image matches D1. Then and now pairs WISE W2 with Cold objects.",
      );
    },
  );

  it("writes the real span of the observations", () => {
    expect(monthSpan("2010-01-07", "2011-02-01")).toBe("Jan 2010 to Feb 2011");
    expect(monthSpan("2010-05-01", "2010-05-30")).toBe("May 2010");
  });
});

// ---------------------------------------------------------------------------------------------

describe.skipIf(!haveFixtures)("catalogue markers", () => {
  const field = () => wise as LoadedField;
  const stars = () => field().manifest.fixture_stars ?? [];
  /** The overlays answer for the WISE 0855 field, with the fixture's own three Gaia DR3 stars. */
  const synthetic_overlays = (): OverlaysResponse => ({
    contract: "1.0",
    status: "ok",
    gaia: stars().map((star) => ({
      source_id: star.source_id,
      ra: star.ra,
      dec: star.dec,
      epoch: 2016.0,
      pmra: null,
      pmdec: null,
      parallax: null,
      g: null,
    })),
    catwise: [
      {
        // On the image, 20 pixels (61.5″) from the centre: not a neighbour of the ring there.
        id: "synthetic-far",
        ra: 133.7598,
        dec: -7.2422 + (20 * 3.075) / 3600,
        epoch: 2015.4,
        pmra: null,
        pmdec: null,
        w1: null,
        w2: null,
      },
      {
        // Far outside the 6′ field: never drawn.
        id: "synthetic-outside",
        ra: 133.9,
        dec: -7.2422,
        epoch: 2015.4,
        pmra: null,
        pmdec: null,
        w1: null,
        w2: null,
      },
      {
        // A track per time bin, moving 3 pixels west in all.
        id: "synthetic-mover",
        ra: 133.7598,
        dec: -7.2422,
        epoch: 2015.4,
        pmra: -8000,
        pmdec: 0,
        w1: null,
        w2: null,
        track: field().manifest.time_bins.map((bin, i) => ({
          time_bin: bin.id,
          ra: 133.7598 - (i * 3.075) / 3600 / Math.cos((7.2422 * Math.PI) / 180),
          dec: -7.2422,
        })),
      },
    ],
    upstreams: { gaia: "ok", catwise: "ok" },
  });
  const ready = (data = synthetic_overlays()) =>
    ({ phase: "ready", key: field().manifest.key, data }) as const;

  it("puts each catalogue star where the grid puts it, in every frame", () => {
    const sequence = sequenceOf(field().synth, "cold");
    const all = catalogueMarkers(
      synthetic_overlays(),
      sequence,
      gridOf(field().manifest),
      field().manifest,
    );
    expect(all.gaia).toHaveLength(3);
    all.gaia.forEach((marker, i) => {
      expect(marker.xy).toHaveLength(4);
      for (const xy of marker.xy) {
        expect(xy?.x).toBeCloseTo(stars()[i].x, 0);
        expect(Math.abs((xy?.x ?? 0) - stars()[i].x)).toBeLessThan(0.5);
        expect(Math.abs((xy?.y ?? 0) - stars()[i].y)).toBeLessThan(0.5);
      }
      expect(marker.fast).toBe(false);
    });
  });

  it("draws Gaia stars as the ring's neighbours, not every star of the field", () => {
    const v = derive(opened(field()), { overlays: ready() });
    expect(v.extras.markers.status).toBe("ready");
    const { cx, cy, pixscale_arcsec: pixscale } = field().manifest.grid;
    const radius = NEIGHBOUR_ARCSEC / pixscale;
    const near = stars().filter((s) => Math.hypot(s.x - cx, s.y - cy) <= radius);
    expect(v.extras.markers.gaia.map((m) => m.id)).toEqual(near.map((s) => s.source_id));
    // With the ring on a star, that star is drawn.
    const star = stars()[0];
    const ringed = run(opened(field()), {
      type: "setRing",
      ring: { dx: Math.round(star.x - cx), dy: Math.round(star.y - cy) },
    });
    const there = derive(ringed, { overlays: ready() });
    expect(there.extras.markers.gaia.map((m) => m.id)).toContain(star.source_id);
  });

  it("never draws a moving source without a track at its old catalogue position", () => {
    const manifest = field().manifest;
    const sequence = sequenceOf(field().synth, "cold");
    const synthetic_untracked = (pmra: number): OverlaysResponse => ({
      contract: "1.0",
      status: "ok",
      gaia: [],
      catwise: [
        {
          id: "synthetic-untracked",
          ra: 133.7598,
          dec: -7.2422,
          epoch: 2015.4,
          pmra,
          pmdec: 0,
          w1: null,
          w2: null,
        },
      ],
      upstreams: { gaia: "ok", catwise: "ok" },
    });
    const place = (pmra: number) =>
      catalogueMarkers(synthetic_untracked(pmra), sequence, gridOf(manifest), manifest).catwise;
    // 8″ a year for ten years is 26 pixels away from the catalogue position: not drawn there.
    expect(place(-8000)).toEqual([]);
    // 40 mas a year moves it 0.4″ in ten years, well within a pixel: drawn.
    expect(place(-40)).toHaveLength(1);
    expect(staleWithoutTrack({ pmra: -300, pmdec: 0 }, 2015.4, 2026.0, 3.075)).toBe(true);
    expect(staleWithoutTrack({ pmra: -250, pmdec: 0 }, 2015.4, 2026.0, 3.075)).toBe(false);
    expect(staleWithoutTrack({ pmra: null, pmdec: null }, 2015.4, 2026.0, 3.075)).toBe(false);
    expect(julianYear(51544.5)).toBe(2000);
  });

  it("follows a moving source along the engine's track, and drops sources off the image", () => {
    const v = derive(opened(field()), { overlays: ready() });
    // CatWISE neighbours: the mover always; the source 61.5″ north only with the ring within
    // NEIGHBOUR_ARCSEC (15″, under five pixels) of it.
    expect(v.extras.markers.catwise.map((m) => m.id)).toEqual(["synthetic-mover"]);
    const near = derive(run(opened(field()), { type: "setRing", ring: { dx: 0, dy: -17 } }), {
      overlays: ready(),
    });
    expect(near.extras.markers.catwise.map((m) => m.id)).toEqual([
      "synthetic-far",
      "synthetic-mover",
    ]);
    const notNear = derive(run(opened(field()), { type: "setRing", ring: { dx: 0, dy: -12 } }), {
      overlays: ready(),
    });
    expect(notNear.extras.markers.catwise.map((m) => m.id)).toEqual(["synthetic-mover"]);
    const mover = v.extras.markers.catwise[0];
    expect(mover.fast).toBe(true);
    expect(mover.label).toBe("8.0″/yr");
    const xs = mover.xy.map((p) => p?.x ?? Number.NaN);
    expect(xs[0]).toBeCloseTo(59, 1);
    expect(xs[3]).toBeCloseTo(62, 1);
  });

  it("is off with the Markers toggle, and says why when the catalogues cannot be had", () => {
    const off = derive(opened(field(), { markers: false }), { overlays: ready() });
    expect(off.extras.markers.status).toBe("off");
    expect(derive(opened(field())).extras.markers.status).toBe("loading");
    const failed = derive(opened(field()), {
      overlays: { phase: "failed", key: field().manifest.key, code: "not_found" },
    });
    expect(failed.extras.markers).toMatchObject({
      status: "unavailable",
      note: "Catalogue markers are not available for this field yet.",
      gaia: [],
    });
    const bundled = derive(opened({ ...field(), source: "bundled" }));
    expect(bundled.extras.markers.note).toBe(MARKERS_NO_ENGINE);
    const halfDown = derive(opened(field()), {
      overlays: ready({
        ...synthetic_overlays(),
        upstreams: { gaia: "ok", catwise: "unavailable" },
      }),
    });
    expect(halfDown.extras.markers.catwise).toEqual([]);
    expect(halfDown.extras.markers.note).toBe(
      "CatWISE could not be reached: only Gaia DR3 stars are marked.",
    );
  });

  it("is not drawn at all when the part is not built", () => {
    const v = derive(opened(field()), { overlays: ready() }, { catalogueMarkers: false });
    expect(v.extras.markers.gaia).toEqual([]);
  });
});

// ---------------------------------------------------------------------------------------------

describe.skipIf(!haveFixtures)("the spectrum", () => {
  const field = () => wise as LoadedField;
  const point = (time_bin: number, lam: number, quality: SpectrumPoint["quality"] = "good") => ({
    lam,
    dlam: 0.03,
    mjd: field().manifest.time_bins[time_bin]?.mjd_mid ?? 61300,
    det: 6,
    time_bin,
    flux_ujy: 100 + lam,
    err_ujy: 10,
    flags: 0,
    quality,
  });
  /** An answer shaped as section 7.1; its fluxes are arithmetic only. */
  const synthetic_spectrum = (extra: Partial<SpectrumResponse> = {}): SpectrumResponse => ({
    contract: "1.0",
    status: "ok",
    state: "ok",
    target: { ra: 133.7598, dec: -7.2422 },
    neighbours: [],
    method: {
      kind: "aperture",
      radius_px: 2,
      encircled_energy: 0.9,
      annulus_px: [5, 9],
      systematic_floor: 0.03,
    },
    time_span: { mjd_min: 60800, mjd_max: 61200 },
    points: [point(3, 4.5), point(1, 1.2, "flagged"), point(0, 2.2), point(1, 4.4)],
    binned: [
      { time_bin: 1, lam: 4.6, lam_min: 4.412, lam_max: 5.002, flux_ujy: 104, err_ujy: 4, n: 2 },
    ],
    ...extra,
  });

  it("names the visits by their dates, in time order, and keeps every point once", () => {
    const model = spectrumModel(synthetic_spectrum(), field().manifest);
    expect(model.visits.map((v) => v.label)).toEqual([
      "5–6 May 2025",
      "31 Oct–14 Nov 2025",
      "21 Apr–14 May 2026",
    ]);
    const vm = spectrumVM(model, "chart");
    expect(vm.points).toHaveLength(4);
    expect(vm.binned).toHaveLength(1);
    expect(vm.points.filter((p) => p.flagged)).toHaveLength(1);
    expect(vm.status).toBe("ready");
    const csv = spectrumCsv(model).trim().split("\n");
    expect(csv).toHaveLength(1 + 5);
    expect(csv[0]).toBe(
      "ra_deg,dec_deg,visit_start,visit_end,kind,wavelength_um,flux_ujy,error_ujy,quality,n_exposures",
    );
    expect(csv[1]).toBe(
      "133.759800,-7.242200,2025-05-05,2025-05-06,exposure,2.2000,102.200,10.000,good,1",
    );
  });

  it("speaks the contract's states in the design's words", () => {
    const m = field().manifest;
    const saturated = spectrumModel(
      synthetic_spectrum({ state: "saturated", points: [], binned: [] }),
      m,
    );
    expect(spectrumVM(saturated, "chart")).toMatchObject({
      status: "saturated",
      messages: [SATURATED],
    });
    expect(spectrumModel(synthetic_spectrum({ state: "indicative" }), m).messages).toEqual([
      INDICATIVE,
    ]);
    const contaminated = spectrumModel(
      synthetic_spectrum({
        state: "contaminated",
        neighbours: [
          { catalog: "catwise", id: "a", sep_arcsec: 11.2, fitted: true },
          { catalog: "catwise", id: "b", sep_arcsec: 7.46, fitted: false },
        ],
      }),
      m,
    );
    expect(contaminated.messages).toEqual([neighbourSentence(7.46)]);
    expect(neighbourSentence(7.46)).toBe("A neighbour 7.5″ away may contaminate this");
    const none = spectrumModel(synthetic_spectrum({ state: "no_data", points: [], binned: [] }), m);
    expect(spectrumVM(none, "chart")).toMatchObject({
      status: "unavailable",
      messages: [NO_SPECTRUM],
    });
  });

  it("draws at most five visits, the latest, and says so", () => {
    const many = [0, 1, 2, 3, 4, 5].map((id) => ({
      ...field().manifest.time_bins[0],
      id,
      mjd_mid: 60000 + id,
      date_start: `2025-0${id + 1}-01`,
      date_end: `2025-0${id + 1}-02`,
    }));
    const manifest = { ...field().manifest, time_bins: many };
    const model = spectrumModel(
      synthetic_spectrum({ points: many.map((bin) => point(bin.id, 1)), binned: [] }),
      manifest,
    );
    expect(model.visits.map((v) => v.timeBin)).toEqual([1, 2, 3, 4, 5]);
    expect(model.rows).toHaveLength(5);
    expect(model.messages).toEqual(["Showing the 5 latest of 6 visits."]);
  });

  it("says when the engine could not measure every exposure (X-Tombaugh-Incomplete)", () => {
    expect(incompleteSentence("12 of 258 exposures not measured; not cached")).toBe(
      "12 of 258 exposures not measured.",
    );
    expect(incompleteSentence(null)).toBeNull();
    const model = spectrumModel(
      { ...synthetic_spectrum(), incomplete: "12 of 258 exposures not measured; not cached" },
      field().manifest,
    );
    expect(model.messages).toContain("12 of 258 exposures not measured.");
    expect(spectrumModel(synthetic_spectrum(), field().manifest).messages).toEqual([]);
  });

  it("opens with the ring, from the engine only, and follows the ring", () => {
    const state = run(opened(field()), { type: "setSpectrum", open: true });
    expect(state.spectrum).toBe(true);
    const at = spectrumAt(field().manifest, gridOf(field().manifest), state.ring);
    expect(at).toEqual({ key: field().manifest.key, ra: 133.7598, dec: -7.2422 });
    expect(derive(state).extras.spectrum).toMatchObject({
      open: true,
      status: "loading",
      messages: ["Measuring…"],
    });
    const loading = derive(state, {
      spectrum: { phase: "loading", at, progress: { done: 120, total: 258 } },
    });
    expect(loading.extras.spectrum.messages).toEqual(["Measuring 120 of 258"]);
    const done = derive(state, { spectrum: { phase: "ready", at, data: synthetic_spectrum() } });
    expect(done.extras.spectrum.visits).toHaveLength(3);
    // The ring moved: the answer for the old position is not shown.
    const moved = run(state, { type: "setRing", ring: { dx: 5, dy: 0 } });
    expect(
      derive(moved, { spectrum: { phase: "ready", at, data: synthetic_spectrum() } }).extras
        .spectrum.status,
    ).toBe("loading");
    const bundled = derive(
      run(opened({ ...field(), source: "bundled" }), { type: "setSpectrum", open: true }),
    );
    expect(bundled.extras.spectrum).toMatchObject({
      status: "unavailable",
      messages: [SPECTRUM_NO_ENGINE],
    });
    // Closed, and never opened when the part is not built.
    expect(derive(opened(field())).extras.spectrum.status).toBe("closed");
    expect(derive(state, {}, { spectrum: false }).extras.spectrum.open).toBe(false);
  });
});

// ---------------------------------------------------------------------------------------------

describe("the spectrum chart (bundle.js spectrum, ported)", () => {
  it("steps its flux axis like a person would, with the true minus", () => {
    expect(niceStep(240)).toBe(50);
    expect(niceStep(9)).toBe(2.5);
    expect(tickLabel(-50, 50)).toBe("−50");
    expect(tickLabel(7.5, 2.5)).toBe("7.5");
  });

  it("gives the visits the series of the system: 1, 2, 4, 5 for four", () => {
    expect(seriesFor(4)).toEqual([1, 2, 4, 5]);
    expect(seriesFor(1)).toEqual([3]);
    expect(seriesFor(3)).toEqual([1, 3, 5]);
  });

  it("keeps zero, the unflagged points and the binned ones on the axis; clips the rest", () => {
    const g = chartGeometry(
      {
        visits: [{ label: "a" }, { label: "b" }],
        points: [
          { lam: 1, flux: -20, err: 5, visit: 0, flagged: false },
          { lam: 2, flux: -10, err: 5, visit: 0, flagged: false },
          { lam: 4.5, flux: 300, err: 40, visit: 1, flagged: true },
        ],
        binned: [],
      },
      328,
      190,
      [3.96, 5.0],
    );
    const values = g.yTicks.map((t) => t.label);
    expect(values).toContain("0");
    expect(values[0]).toBe("−20");
    // The one flagged 300 µJy exposure among good ones is clipped by the plot, not allowed to set
    // the axis; the chart counts it, and the panel says so.
    expect(values.at(-1)).toBe("0");
    expect(g.outside).toBe(1);
    expect(outsideNote(g.outside)).toBe(
      "1 point lies outside the chart; the table holds every value.",
    );
    expect(outsideNote(0)).toBeNull();
    expect(g.clip).toEqual({
      x: g.left,
      y: g.top,
      width: g.right - g.left,
      height: g.bottom - g.top,
    });
    expect(g.series.map((s) => s.series)).toEqual([1, 5]);
    expect(g.series[1].flag).not.toBe("");
    expect(g.series[0].pts).not.toBe("");
    expect(g.band?.width).toBeGreaterThan(0);
  });

  it("follows the flagged points when they are most of the spectrum (RW Aurigae's case)", () => {
    // 305 of 335 RW Aurigae exposures were flagged OVERFLOW; most of its flux is in them.
    const points = [
      { lam: 0.9, flux: 80_000, err: 900, visit: 0, flagged: false },
      { lam: 1.2, flux: 120_000, err: 900, visit: 0, flagged: false },
      { lam: 2.2, flux: 900_000, err: 9_000, visit: 0, flagged: true },
      { lam: 3.4, flux: 2_500_000, err: 30_000, visit: 0, flagged: true },
      { lam: 4.6, flux: 3_400_000, err: 40_000, visit: 0, flagged: true },
    ];
    expect(fluxRange(points, [])).toEqual([0, 3_400_000]);
    const g = chartGeometry({ visits: [{ label: "a" }], points, binned: [] }, 328, 190, null);
    expect(g.outside).toBe(0);
    expect(g.yTicks.at(-1)?.label).toBe("4000000");
  });

  it("keeps the rotated axis title clear of the widest tick label", () => {
    const g = chartGeometry(
      {
        visits: [{ label: "a" }],
        points: [{ lam: 1, flux: 250_000, err: 1, visit: 0, flagged: false }],
        binned: [],
      },
      328,
      190,
      null,
    );
    const widest = Math.max(...g.yTicks.map((t) => t.label.length));
    // The title's glyphs reach about 14 px from the edge; each label ends 6 px left of the plot.
    expect(g.left - 6 - 7.5 * widest).toBeGreaterThanOrEqual(16);
  });
});
