/**
 * Golden checks on the recorded REAL fields (Contract v1.0 section 8).
 *
 * scripts/sync-contract.mjs copies cache/fixtures/<name>/ to public/fixtures/<name>/ before the
 * tests run. Every fixture found there is checked; nothing here invents data. While no fixture
 * has been produced yet, a single test says so by name.
 */
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { checkFrames } from "../api";
import type { Manifest } from "../contract";
import { decodeFloat16 } from "./float16";
import { gridOf, skyToPixel } from "./grid";
import { contractWaveBins } from "./presets";
import { FieldSynth, type Frame, presetWaveBins } from "./synth";

const fixturesDir = fileURLToPath(new URL("../../public/fixtures/", import.meta.url));

/** A pixel of a frame: column, row, brightness in MJy/sr and distance in px from a search point. */
interface Peak {
  x: number;
  y: number;
  value: number;
  distance: number;
}

/** The brightest finite pixel whose centre lies within `radius` px of (x0, y0), or null. */
function brightestWithin(
  data: Float32Array,
  nx: number,
  x0: number,
  y0: number,
  radius: number,
): Peak | null {
  const ny = data.length / nx;
  let best: Peak | null = null;
  for (let y = Math.max(0, Math.ceil(y0 - radius)); y <= Math.min(ny - 1, y0 + radius); y++) {
    for (let x = Math.max(0, Math.ceil(x0 - radius)); x <= Math.min(nx - 1, x0 + radius); x++) {
      const distance = Math.hypot(x - x0, y - y0);
      const value = data[y * nx + x];
      if (distance > radius || !Number.isFinite(value)) continue;
      if (best === null || value > best.value) best = { x, y, value, distance };
    }
  }
  return best;
}

/** True when no pixel of the 3 x 3 block around (x, y) is brighter than (x, y) itself. */
function isLocalMaximum(data: Float32Array, nx: number, x: number, y: number): boolean {
  const ny = data.length / nx;
  for (let row = Math.max(0, y - 1); row <= Math.min(ny - 1, y + 1); row++) {
    for (let column = Math.max(0, x - 1); column <= Math.min(nx - 1, x + 1); column++) {
      if (data[row * nx + column] > data[y * nx + x]) return false;
    }
  }
  return true;
}

/** Brightness-weighted mean row of the pixels within `radius` px of (x0, y0); row 0 is north. */
function centroidRow(data: Float32Array, nx: number, x0: number, y0: number, radius: number) {
  const ny = data.length / nx;
  let weight = 0;
  let weightedRow = 0;
  for (let y = 0; y < ny; y++) {
    for (let x = 0; x < nx; x++) {
      const value = data[y * nx + x];
      if (Math.hypot(x - x0, y - y0) > radius || !(value > 0)) continue;
      weight += value;
      weightedRow += value * y;
    }
  }
  return weightedRow / weight;
}

/** A copy of a square frame with each pixel taken from `source(x, y)` of the original. */
function rearranged(
  data: Float32Array,
  n: number,
  source: (x: number, y: number) => [number, number],
): Float32Array {
  const out = new Float32Array(data.length);
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      const [fromX, fromY] = source(x, y);
      out[y * n + x] = data[fromY * n + fromX];
    }
  }
  return out;
}

/** A frame with every selected wave bin and enough exposures: what the contract calls a full visit. */
const isFull = (frame: Frame) => frame.waveBins.length > 0 && !frame.partial && !frame.thin;

/** The full frame with the most exposures. */
function bestCovered(frames: readonly Frame[]): Frame {
  const full = frames.filter(isFull).sort((a, b) => b.nExposures - a.nExposures);
  if (full.length === 0) throw new Error("no full visit in this sequence");
  return full[0];
}

function loadFixture(name: string) {
  const manifest: Manifest = JSON.parse(
    readFileSync(join(fixturesDir, name, "manifest.json"), "utf8"),
  );
  const bytes = readFileSync(join(fixturesDir, name, "frames.bin"));
  const synth = new FieldSynth(manifest, decodeFloat16(new Uint8Array(bytes).buffer));
  return { manifest, synth };
}

const names = existsSync(fixturesDir)
  ? readdirSync(fixturesDir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .filter((name) => existsSync(join(fixturesDir, name, "manifest.json")))
      .sort()
  : [];

describe("recorded fixtures", () => {
  if (names.length === 0) {
    it("none has been produced yet: these checks start once cache/fixtures holds a field", () => {
      expect(names).toEqual([]);
    });
  }

  describe.each(names)("%s", (name) => {
    const manifest: Manifest = JSON.parse(
      readFileSync(join(fixturesDir, name, "manifest.json"), "utf8"),
    );
    const bytes = readFileSync(join(fixturesDir, name, "frames.bin"));
    const buffer = new Uint8Array(bytes).buffer;
    const { nx, ny } = manifest.grid;

    it("has a frame file of the length its manifest states", () => {
      expect(manifest.frames).not.toBeNull();
      expect(bytes.byteLength).toBe(manifest.frames?.nbytes);
      expect(bytes.byteLength).toBe(manifest.planes.length * ny * nx * 2);
      expect(() => checkFrames(manifest, buffer)).not.toThrow();
    });

    it("has a frame file matching its manifest's sha256", () => {
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(manifest.frames?.sha256);
    });

    it("decodes to one plane per manifest entry, at the stated offsets", () => {
      const values = decodeFloat16(buffer);
      expect(values).toHaveLength(manifest.planes.length * ny * nx);
      manifest.planes.forEach((plane, index) => {
        expect(plane.index).toBe(index);
        expect(plane.offset).toBe(index * ny * nx * 2);
      });
      expect(values.some((value) => Number.isFinite(value))).toBe(true);
    });

    it("uses the contract's grid and wave bins", () => {
      const { grid } = manifest;
      expect(grid.pixscale_arcsec).toBe(3.075);
      expect(nx).toBe(ny);
      expect(nx % 2).toBe(1);
      expect(grid.cx).toBe((nx - 1) / 2);
      expect(grid.cy).toBe((ny - 1) / 2);
      expect([grid.projection, grid.row0, grid.col0]).toEqual(["TAN", "north", "east"]);
      const expected = contractWaveBins();
      expect(manifest.wave_bins).toHaveLength(expected.length);
      manifest.wave_bins.forEach((bin, i) => {
        expect(bin.id).toBe(expected[i].id);
        expect(bin.detector).toBe(expected[i].detector);
        expect(bin.lam_min).toBeCloseTo(expected[i].lam_min, 6);
        expect(bin.lam_max).toBeCloseTo(expected[i].lam_max, 6);
      });
    });

    it("places every fixture star within 0.5 px of its recorded pixel", () => {
      const stars = manifest.fixture_stars ?? [];
      expect(stars.length).toBeGreaterThan(0);
      for (const star of stars) {
        const pixel = skyToPixel(gridOf(manifest), star.ra, star.dec);
        expect(Math.hypot(pixel.x - star.x, pixel.y - star.y)).toBeLessThan(0.5);
      }
    });

    it("forms one frame per time bin, with data", () => {
      const synth = new FieldSynth(manifest, decodeFloat16(buffer));
      const frames = synth.sequenceFor("all");
      expect(frames).toHaveLength(manifest.time_bins.length);
      expect(frames.some((frame) => frame.waveBins.length > 0)).toBe(true);
    });

    it.each(["all", "cold"])("forms real frames for the preset %s", (presetId) => {
      const synth = new FieldSynth(manifest, decodeFloat16(buffer));
      const selection = presetWaveBins(presetId, manifest.wave_bins);
      const selected = selection.kind === "mono" ? selection.bins : [];
      const frames = synth.sequenceFor(presetId);
      expect(frames).toHaveLength(manifest.time_bins.length);
      expect(frames.filter(isFull).length).toBeGreaterThanOrEqual(2);
      frames.forEach((frame, i) => {
        const bin = manifest.time_bins[i];
        expect(frame.timeBin).toBe(bin.id);
        expect(frame.data).toHaveLength(ny * nx);
        expect(selected).toEqual(expect.arrayContaining(frame.waveBins));
        expect(frame.nExposures).toBeLessThanOrEqual(bin.n_exposures);
        if (frame.waveBins.length === 0) {
          // No plane of this visit lies in the preset: the frame is all "no data".
          expect(frame.data.every((value) => Number.isNaN(value))).toBe(true);
          return;
        }
        expect(frame.sigma).toBeGreaterThan(0);
        expect(frame.nExposures).toBeGreaterThan(0);
        expect(frame.lamMin).toBeLessThan(frame.lamMax);
        expect(frame.dateStart && frame.dateStart >= bin.date_start).toBe(true);
        expect(frame.dateEnd && frame.dateEnd <= bin.date_end).toBe(true);
        // Real sky: most pixels have data, and they are not one flat value.
        const finite = frame.data.filter((value) => Number.isFinite(value));
        expect(finite.length).toBeGreaterThan(0.9 * ny * nx);
        const brightest = finite.reduce((a, b) => Math.max(a, b), Number.NEGATIVE_INFINITY);
        const faintest = finite.reduce((a, b) => Math.min(a, b), Number.POSITIVE_INFINITY);
        expect(brightest - faintest).toBeGreaterThan(10 * frame.sigma);
      });
    });

    it("counts every exposure of a visit in the all-band frame", () => {
      const synth = new FieldSynth(manifest, decodeFloat16(buffer));
      const frames = synth.sequenceFor("all");
      frames.forEach((frame, i) => {
        expect(frame.nExposures).toBe(manifest.time_bins[i].n_exposures);
      });
    });

    // The fixture stars' recorded pixels are true by construction; this is the check that the
    // decoded picture itself is the right way round (row 0 north, column 0 east).
    describe("orientation of the decoded picture", () => {
      const SEARCH_PX = 3;
      const TOLERANCE_PX = 1.5;
      const synth = new FieldSynth(manifest, decodeFloat16(buffer));
      const frame = bestCovered(synth.sequenceFor("all"));
      const stars = manifest.fixture_stars ?? [];

      /** How many fixture stars are the brightest thing near their predicted pixel. */
      const starsFound = (data: Float32Array) =>
        stars.filter((star) => {
          const peak = brightestWithin(data, nx, star.x, star.y, SEARCH_PX);
          return peak !== null && peak.distance <= TOLERANCE_PX && peak.value > 20 * frame.sigma;
        }).length;

      it("shows every fixture star as the brightest pixel where the grid puts it", () => {
        expect(stars.length).toBeGreaterThanOrEqual(3);
        expect(starsFound(frame.data)).toBe(stars.length);
      });

      it.each([
        ["mirrored east-west", (x: number, y: number): [number, number] => [nx - 1 - x, y]],
        ["mirrored north-south", (x: number, y: number): [number, number] => [x, ny - 1 - y]],
        ["transposed", (x: number, y: number): [number, number] => [y, x]],
      ])("does not when the picture is %s", (_name, source) => {
        expect(starsFound(rearranged(frame.data, nx, source))).toBeLessThan(stars.length);
      });
    });
  });

  // Contract v1.0 section 8: WISE 0855's "cold" frame has a source within 2 px of the centre
  // in the full visits.
  describe.skipIf(!names.includes("wise0855"))("wise0855 through the cold preset", () => {
    const CENTRE_TOLERANCE_PX = 2;
    const SEARCH_PX = 3;
    const MIN_SIGNAL_TO_NOISE = 5;

    it("has a significant peak within 2 px of the field centre in every full visit", () => {
      const { manifest, synth } = loadFixture("wise0855");
      const { nx, cx, cy } = manifest.grid;
      const full = synth.sequenceFor("cold").filter(isFull);
      expect(full.length).toBeGreaterThanOrEqual(2);
      for (const frame of full) {
        const peak = brightestWithin(frame.data, nx, cx, cy, SEARCH_PX);
        if (peak === null) throw new Error(`time bin ${frame.timeBin}: no data at the centre`);
        expect(isLocalMaximum(frame.data, nx, peak.x, peak.y)).toBe(true);
        expect(peak.distance).toBeLessThanOrEqual(CENTRE_TOLERANCE_PX);
        expect(peak.value / frame.sigma).toBeGreaterThan(MIN_SIGNAL_TO_NOISE);
      }
    });

    it("needs the preset: through all bands the brightest pixel there is the neighbour", () => {
      // The same search on the all-band frames lands on the catalogued neighbour, more than
      // 2 px from the centre. So the check above passes only if "cold" really selects 4-5 µm.
      const { manifest, synth } = loadFixture("wise0855");
      const { nx, cx, cy } = manifest.grid;
      const full = synth.sequenceFor("all").filter(isFull);
      expect(full.length).toBeGreaterThanOrEqual(2);
      for (const frame of full) {
        const peak = brightestWithin(frame.data, nx, cx, cy, SEARCH_PX);
        expect(peak?.distance).toBeGreaterThan(CENTRE_TOLERANCE_PX);
      }
    });
  });

  // Contract v1.0 section 8: Barnard's centroid moves north between the first and last time bins.
  describe.skipIf(!names.includes("barnard"))("barnard", () => {
    it("moves north (towards row 0) between the first and the last full visit", () => {
      const { manifest, synth } = loadFixture("barnard");
      const { nx, cx, cy } = manifest.grid;
      const full = synth.sequenceFor("cold").filter(isFull);
      expect(full.length).toBeGreaterThanOrEqual(2);
      const first = centroidRow(full[0].data, nx, cx, cy, 12);
      const last = centroidRow(full[full.length - 1].data, nx, cx, cy, 12);
      // About 10.3 arcsec per year at 3.075 arcsec per pixel, over one year of visits.
      expect(first - last).toBeGreaterThan(2);
      expect(first - last).toBeLessThan(5);
    });
  });
});
