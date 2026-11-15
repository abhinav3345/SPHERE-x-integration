import { describe, expect, it } from "vitest";
import { CONTRACT_VERSION, type Manifest, type Plane } from "../contract";
import { contractWaveBins, DEFAULT_WEIGHTING, PRESETS, PRESETS_FILE } from "./presets";
import { differenceFrame, FieldSynth, presetWaveBins, selectWaveBins } from "./synth";

const range = (from: number, to: number) =>
  Array.from({ length: to - from + 1 }, (_, i) => from + i);

// ---------------------------------------------------------------------------------------------
// Tiny synthetic field: a 2 x 2 grid, three time bins, a handful of planes. Arithmetic only.
// ---------------------------------------------------------------------------------------------

const NAN = Number.NaN;

interface SyntheticPlane {
  time_bin: number | null;
  wave_bin: number | null;
  sigma: number;
  n_exposures: number;
  pixels: [number, number, number, number];
  kind?: "sci" | "legacy";
}

const synthetic_planes: SyntheticPlane[] = [
  { time_bin: 0, wave_bin: 20, sigma: 0.1, n_exposures: 5, pixels: [1, 2, NAN, 4] },
  { time_bin: 0, wave_bin: 21, sigma: 0.2, n_exposures: 4, pixels: [3, NAN, NAN, 8] },
  { time_bin: 1, wave_bin: 20, sigma: 0.1, n_exposures: 3, pixels: [2, 2, 2, 2] },
  { time_bin: 2, wave_bin: 20, sigma: 0.1, n_exposures: 6, pixels: [0, 1, 2, 3] },
  { time_bin: 2, wave_bin: 21, sigma: 0.3, n_exposures: 6, pixels: [1, 1, 1, 1] },
  // No usable noise estimate: must be left out of every frame.
  { time_bin: 2, wave_bin: 22, sigma: 0, n_exposures: 9, pixels: [50, 50, 50, 50] },
  // A legacy survey image: never mixed into SPHEREx frames.
  {
    time_bin: null,
    wave_bin: null,
    sigma: 0.1,
    n_exposures: 1,
    pixels: [9, 9, 9, 9],
    kind: "legacy",
  },
];

function synthetic_field(planes: SyntheticPlane[] = synthetic_planes) {
  const waveBins = contractWaveBins();
  const manifestPlanes: Plane[] = planes.map((plane, index) => {
    const bin = plane.wave_bin === null ? null : waveBins[plane.wave_bin];
    const year = 2025 + (plane.time_bin ?? 0);
    const day = ((plane.wave_bin ?? 0) % 4) + 1; // bin 20 -> day 1, bin 21 -> day 2
    return {
      index,
      kind: plane.kind ?? "sci",
      mission: plane.kind === "legacy" ? "AllWISE" : "SPHEREx",
      time_bin: plane.time_bin,
      wave_bin: plane.wave_bin,
      band: plane.kind === "legacy" ? "W2" : null,
      lam_min: bin?.lam_min ?? 4.0,
      lam_max: bin?.lam_max ?? 5.3,
      lam_eff: bin ? (bin.lam_min + bin.lam_max) / 2 : 4.6,
      n_exposures: plane.n_exposures,
      sigma: plane.sigma,
      mjd_mid: 60980 + 180 * (plane.time_bin ?? 0),
      date_start: `${year}-01-0${day}`,
      date_end: `${year}-01-1${day}`,
      offset: index * 4 * 2,
    };
  });
  const manifest: Manifest = {
    contract: "1.0",
    status: "ready",
    key: "synthetic",
    request: { ra: 10, dec: 20, fov_arcmin: 3 },
    centre: { ra: 10, dec: 20 },
    epoch_ref: 2026.0,
    grid: {
      nx: 2,
      ny: 2,
      cx: 0.5,
      cy: 0.5,
      pixscale_arcsec: 3.075,
      projection: "TAN",
      row0: "north",
      col0: "east",
    },
    time_binning: { gap_days: 20, max_span_days: 60, sub_span_days: 30 },
    time_bins: [0, 1, 2].map((id) => ({
      id,
      mjd_start: 60970 + 180 * id,
      mjd_end: 60990 + 180 * id,
      mjd_mid: 60980 + 180 * id,
      date_start: `202${5 + id}-01-01`,
      date_end: `202${5 + id}-01-20`,
      n_exposures: 10,
      detectors: [6],
    })),
    wave_bins: waveBins,
    planes: manifestPlanes,
    frames: {
      url: "",
      dtype: "float16",
      byteorder: "little",
      nbytes: planes.length * 8,
      sha256: "",
    },
    exposures: {
      found: 0,
      used: 0,
      sampled: false,
      collections: {},
      newest_mjd: 0,
      newest_date: "",
    },
    provenance: { pipeline_version: "test", built_at: "", data_dois: [], notes: [] },
    warnings: [],
  };
  const synthetic_values = new Float32Array(planes.flatMap((plane) => plane.pixels));
  return { manifest, synthetic_values, synth: new FieldSynth(manifest, synthetic_values) };
}

/** Compares float32 pixels with expectations, NaN included. */
function expectPixels(actual: Float32Array, expected: number[]) {
  expect(actual).toHaveLength(expected.length);
  expected.forEach((value, i) => {
    if (Number.isNaN(value)) expect(actual[i]).toBeNaN();
    else expect(actual[i]).toBeCloseTo(value, 6);
  });
}

// ---------------------------------------------------------------------------------------------

describe("presets.json", () => {
  it("is the contract version this code is written for", () => {
    expect(PRESETS_FILE.contract).toBe(CONTRACT_VERSION);
    expect(DEFAULT_WEIGHTING).toBe("uniform");
  });

  it("defines 24 wave bins, four per detector, blue to red", () => {
    const bins = contractWaveBins();
    expect(bins.map((bin) => bin.id)).toEqual(range(0, 23));
    expect(bins.map((bin) => bin.detector)).toEqual(
      range(0, 23).map((id) => Math.floor(id / 4) + 1),
    );
    // The two bins the contract writes out in full (section 5).
    expect(bins[0].lam_min).toBeCloseTo(0.744, 10);
    expect(bins[0].lam_max).toBeCloseTo(0.837, 10);
    expect(bins[20].lam_min).toBeCloseTo(4.412, 10);
    expect(bins[20].lam_max).toBeCloseTo(4.5595, 10);
    expect(bins[23].lam_max).toBe(5.002);
  });
});

describe("presetWaveBins", () => {
  it("selects by detector list", () => {
    expect(presetWaveBins("d1")).toEqual({ kind: "mono", bins: [0, 1, 2, 3] });
    expect(presetWaveBins("d4")).toEqual({ kind: "mono", bins: [12, 13, 14, 15] });
    expect(presetWaveBins("d6")).toEqual({ kind: "mono", bins: [20, 21, 22, 23] });
  });

  it("selects by wavelength range using bin centres", () => {
    expect(presetWaveBins("all")).toEqual({ kind: "mono", bins: range(0, 23) });
    // Detector 5 spans 3.809-4.420 um in steps of 0.15275: its first bin is centred on
    // 3.885 um, below the 4.0 um edge, so "cold" starts at bin 17.
    expect(presetWaveBins("cold")).toEqual({ kind: "mono", bins: range(17, 23) });
  });

  it("gives three lists for the rgb preset", () => {
    expect(presetWaveBins("rgb")).toEqual({
      kind: "rgb",
      r: range(16, 23),
      g: range(8, 15),
      b: range(0, 7),
    });
  });

  it("selects something for every preset in the file", () => {
    for (const preset of PRESETS) {
      const selection = presetWaveBins(preset.id);
      const lists =
        selection.kind === "mono" ? [selection.bins] : [selection.r, selection.g, selection.b];
      for (const list of lists) expect(list.length).toBeGreaterThan(0);
    }
  });

  it("rejects an id the file does not define", () => {
    expect(() => presetWaveBins("ultraviolet")).toThrow(RangeError);
  });

  it("requires both criteria when a selector has a detector list and a range", () => {
    const bins = contractWaveBins();
    expect(selectWaveBins({ detectors: [5, 6], lam_min: 4.0, lam_max: 4.42 }, bins)).toEqual([
      17, 18, 19,
    ]);
    expect(selectWaveBins({}, bins)).toEqual([]);
  });
});

describe("FieldSynth.frameFor", () => {
  it("averages planes with equal weights, skipping pixels without data", () => {
    const frame = synthetic_field().synth.frameFor(0, "d6", "uniform");
    // pixel 0: (1 + 3) / 2; pixel 1: only bin 20 is finite; pixel 2: none; pixel 3: (4 + 8) / 2
    expectPixels(frame.data, [2, 2, NAN, 6]);
    // sqrt(0.1^2 + 0.2^2) / 2
    expect(frame.sigma).toBeCloseTo(0.1118034, 7);
    expect(frame.nExposures).toBe(9);
    expect(frame.waveBins).toEqual([20, 21]);
    expect(frame.lamMin).toBeCloseTo(4.412, 10);
    expect(frame.lamMax).toBeCloseTo(4.707, 10);
    expect(frame.timeBin).toBe(0);
    expect(frame.partial).toBe(false);
    expect(frame.thin).toBe(false);
  });

  it("weights by inverse variance on request", () => {
    const frame = synthetic_field().synth.frameFor(0, "d6", "ivar");
    // w = 1 / sigma^2 = 100 and 25. pixel 0: (100*1 + 25*3) / 125; pixel 3: (100*4 + 25*8) / 125
    expectPixels(frame.data, [1.4, 2, NAN, 4.8]);
    // sqrt(100^2 * 0.01 + 25^2 * 0.04) / 125 = 1 / sqrt(125)
    expect(frame.sigma).toBeCloseTo(0.0894427, 7);
  });

  it("uses uniform weights by default, as presets.json says", () => {
    const { synth } = synthetic_field();
    expectPixels(synth.frameFor(0, "d6").data, [2, 2, NAN, 6]);
  });

  it("flags a frame as partial when a wave bin seen at other times is missing", () => {
    const frame = synthetic_field().synth.frameFor(1, "d6");
    expectPixels(frame.data, [2, 2, 2, 2]);
    expect(frame.waveBins).toEqual([20]);
    expect(frame.partial).toBe(true);
    expect(frame.sigma).toBeCloseTo(0.1, 12);
  });

  it("flags a frame as thin below 8 exposures", () => {
    const { synth } = synthetic_field();
    expect(synth.frameFor(1, "d6").nExposures).toBe(3);
    expect(synth.frameFor(1, "d6").thin).toBe(true);
    expect(synth.frameFor(0, "d6").nExposures).toBe(9);
    expect(synth.frameFor(0, "d6").thin).toBe(false);
  });

  it("leaves out planes without a usable noise estimate, and legacy planes", () => {
    const frame = synthetic_field().synth.frameFor(2, "d6");
    // Bins 20 and 21 only: the sigma = 0 plane (all 50s) and the legacy plane are ignored.
    expectPixels(frame.data, [0.5, 1, 1.5, 2]);
    expect(frame.waveBins).toEqual([20, 21]);
    expect(frame.nExposures).toBe(12);
    expect(frame.partial).toBe(false);
  });

  it("reports the dates of the contributing planes", () => {
    const frame = synthetic_field().synth.frameFor(0, "d6");
    expect(frame.dateStart).toBe("2025-01-01");
    expect(frame.dateEnd).toBe("2025-01-12");
  });

  it("gives an all-NaN frame where the preset has no plane", () => {
    const frame = synthetic_field().synth.frameFor(0, "d1");
    expectPixels(frame.data, [NAN, NAN, NAN, NAN]);
    expect(frame.sigma).toBeNaN();
    expect(frame.lamMin).toBeNaN();
    expect(frame.nExposures).toBe(0);
    expect(frame.waveBins).toEqual([]);
    expect(frame.dateStart).toBeNull();
    expect(frame.thin).toBe(true);
    expect(frame.partial).toBe(false); // no time bin has these wave bins either
  });

  it("builds one frame per time bin for a sequence", () => {
    const frames = synthetic_field().synth.sequenceFor("cold");
    expect(frames.map((frame) => frame.timeBin)).toEqual([0, 1, 2]);
    expect(frames.map((frame) => frame.partial)).toEqual([false, true, false]);
  });

  it("splits the rgb preset into three channel frames", () => {
    const { synth } = synthetic_field();
    const rgb = synth.rgbFrameFor(0, "rgb");
    expectPixels(rgb.r.data, [2, 2, NAN, 6]); // detectors 5 and 6
    expectPixels(rgb.g.data, [NAN, NAN, NAN, NAN]);
    expect(() => synth.frameFor(0, "rgb")).toThrow(TypeError);
    expect(() => synth.rgbFrameFor(0, "d6")).toThrow(TypeError);
  });

  it("rejects unknown time bins and planes outside the file", () => {
    const { synth, manifest, synthetic_values } = synthetic_field();
    expect(() => synth.frameFor(7, "d6")).toThrow(RangeError);
    expect(() => new FieldSynth(manifest, synthetic_values.subarray(0, 20))).toThrow(RangeError);
  });

  it("does not modify the decoded planes", () => {
    const { synth, synthetic_values } = synthetic_field();
    const before = Array.from(synthetic_values);
    synth.sequenceFor("all", "ivar");
    expect(Array.from(synthetic_values)).toEqual(before);
  });
});

describe("differenceFrame", () => {
  it("subtracts pixel by pixel and adds the noise in quadrature", () => {
    const { synth } = synthetic_field();
    const first = synth.frameFor(0, "d6");
    const last = synth.frameFor(2, "d6");
    const difference = differenceFrame(last, first);
    expect(difference).not.toBeNull();
    // [0.5, 1, 1.5, 2] - [2, 2, NaN, 6]
    expectPixels(difference?.data ?? new Float32Array(), [-1.5, -1, NAN, -4]);
    // sigma_last = sqrt(0.01 + 0.09) / 2, sigma_first = sqrt(0.01 + 0.04) / 2
    expect(difference?.sigma).toBeCloseTo(Math.sqrt(0.025 + 0.0125), 7);
    expect(difference?.timeBins).toEqual([2, 0]);
  });

  it("refuses partial or thin frames", () => {
    const { synth } = synthetic_field();
    const full = synth.frameFor(0, "d6");
    const partialAndThin = synth.frameFor(1, "d6");
    expect(differenceFrame(partialAndThin, full)).toBeNull();
    expect(differenceFrame(full, partialAndThin)).toBeNull();
  });

  it("refuses frames built from different wave bins", () => {
    const planes: SyntheticPlane[] = [
      { time_bin: 0, wave_bin: 20, sigma: 0.1, n_exposures: 9, pixels: [1, 1, 1, 1] },
      { time_bin: 0, wave_bin: 16, sigma: 0.1, n_exposures: 9, pixels: [2, 2, 2, 2] },
      { time_bin: 2, wave_bin: 20, sigma: 0.1, n_exposures: 9, pixels: [3, 3, 3, 3] },
      { time_bin: 2, wave_bin: 16, sigma: 0.1, n_exposures: 9, pixels: [4, 4, 4, 4] },
    ];
    const { synth } = synthetic_field(planes);
    const d6 = synth.frameFor(0, "d6");
    const d5 = synth.frameFor(2, "d5");
    expect(d6.partial || d6.thin || d5.partial || d5.thin).toBe(false);
    expect(differenceFrame(d6, d5)).toBeNull();
    expectPixels(
      differenceFrame(synth.frameFor(2, "d6"), d6)?.data ?? new Float32Array(),
      [2, 2, 2, 2],
    );
  });
});

describe("FieldSynth.stackFor (Then and now's SPHEREx side)", () => {
  it("combines every SPHEREx plane of the preset over every visit, never a legacy plane", () => {
    const stack = synthetic_field().synth.stackFor("d6", "uniform");
    // Usable planes of bins 20 and 21 at time bins 0, 1, 2; the legacy plane (all 9) is left out.
    expectPixels(stack.data, [7 / 5, 6 / 4, 5 / 3, 18 / 5]);
    expect(stack.sigma).toBeCloseTo(Math.sqrt(0.01 + 0.04 + 0.01 + 0.01 + 0.09) / 5, 9);
    expect(stack.nExposures).toBe(5 + 4 + 3 + 6 + 6);
    expect(stack.timeBins).toEqual([0, 1, 2]);
    expect(stack.waveBins).toEqual([20, 21]);
    expect(stack.dateStart).toBe("2025-01-01");
    expect(stack.dateEnd).toBe("2027-01-12");
  });

  it("has no data, and says so, when nothing lies in the preset", () => {
    const stack = synthetic_field().synth.stackFor("d1");
    expect(stack.nExposures).toBe(0);
    expect(stack.timeBins).toEqual([]);
    expect(stack.dateStart).toBeNull();
    expectPixels(stack.data, [NAN, NAN, NAN, NAN]);
    expect(() => synthetic_field().synth.stackFor("rgb")).toThrow(TypeError);
  });
});

describe("FieldSynth.legacyPlanes", () => {
  it("exposes the older survey's image apart from every SPHEREx frame", () => {
    const { synth } = synthetic_field();
    const legacy = synth.legacyPlanes();
    expect(legacy.map((plane) => [plane.mission, plane.band])).toEqual([["AllWISE", "W2"]]);
    expectPixels(synth.planeData(legacy[0]), [9, 9, 9, 9]);
    // The legacy plane's 9s reach no frame of any preset.
    for (const preset of ["all", "cold", "d6"]) {
      for (const frame of synth.sequenceFor(preset)) {
        expect(Array.from(frame.data).some((value) => value === 9)).toBe(false);
      }
    }
  });

  it("lists them in the order of presets.json legacy_pairs", () => {
    const { manifest, synthetic_values } = synthetic_field();
    const planes = manifest.planes.map((plane) =>
      plane.kind === "legacy" ? { ...plane, band: "Ks", mission: "2MASS" } : plane,
    );
    const w1 = { ...manifest.planes[6], band: "W1", index: 7, offset: 6 * 8 };
    const synth = new FieldSynth({ ...manifest, planes: [...planes, w1] }, synthetic_values);
    expect(synth.legacyPlanes().map((plane) => plane.band)).toEqual(["W1", "Ks"]);
  });

  it("gives the wave bins of a preset on the field's own bins", () => {
    const { synth } = synthetic_field();
    expect(synth.presetBins("d6")).toEqual({ kind: "mono", bins: [20, 21, 22, 23] });
    const rgb = synth.presetBins("rgb");
    expect(rgb.kind === "rgb" && rgb.r).toEqual([16, 17, 18, 19, 20, 21, 22, 23]);
  });
});
