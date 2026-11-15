import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { gridOf, pixelToSky, type SkyGrid, skyToPixel, wrapDegrees } from "./grid";

interface VectorCase {
  ra: number;
  dec: number;
  x: number;
  y: number;
}

interface VectorGrid extends SkyGrid {
  name: string;
  nx: number;
  ny: number;
  cases: VectorCase[];
}

interface VectorFile {
  contract: string;
  tolerance_px: number;
  tolerance_arcsec: number;
  grids: VectorGrid[];
}

// The contract's own reference vectors (astropy), read from docs/ so there is a single copy.
const vectors: VectorFile = JSON.parse(
  readFileSync(new URL("../../../docs/contract/vectors/grid.json", import.meta.url), "utf8"),
);

const RAD = Math.PI / 180;

/** Angular separation of two sky positions in arcsec (haversine, stable for tiny angles). */
function separationArcsec(ra1: number, dec1: number, ra2: number, dec2: number): number {
  const sinDec = Math.sin(((dec2 - dec1) * RAD) / 2);
  const sinRa = Math.sin(((ra2 - ra1) * RAD) / 2);
  const h = sinDec * sinDec + Math.cos(dec1 * RAD) * Math.cos(dec2 * RAD) * sinRa * sinRa;
  return (2 * Math.asin(Math.min(1, Math.sqrt(h))) * 3600) / RAD;
}

describe("contract grid vectors", () => {
  it("covers every grid in the vector file", () => {
    expect(vectors.contract).toBe("1.0");
    expect(vectors.grids.map((grid) => grid.name)).toEqual([
      "wise0855",
      "barnard",
      "r_dra",
      "ra_wrap",
      "near_pole",
      "eps_indi_b",
    ]);
    expect(vectors.grids.every((grid) => grid.cases.length === 15)).toBe(true);
  });

  describe.each(vectors.grids)("grid $name", (grid) => {
    it.each(grid.cases)("sky ($ra, $dec) -> pixel ($x, $y)", (c) => {
      const pixel = skyToPixel(grid, c.ra, c.dec);
      expect(Math.abs(pixel.x - c.x)).toBeLessThanOrEqual(vectors.tolerance_px);
      expect(Math.abs(pixel.y - c.y)).toBeLessThanOrEqual(vectors.tolerance_px);
    });

    it.each(grid.cases)("pixel ($x, $y) -> sky ($ra, $dec)", (c) => {
      const sky = pixelToSky(grid, c.x, c.y);
      expect(separationArcsec(sky.ra, sky.dec, c.ra, c.dec)).toBeLessThanOrEqual(
        vectors.tolerance_arcsec,
      );
      expect(sky.ra).toBeGreaterThanOrEqual(0);
      expect(sky.ra).toBeLessThan(360);
    });

    it("maps the centre pixel to exactly the field centre", () => {
      expect(pixelToSky(grid, grid.cx, grid.cy)).toEqual({ ra: grid.ra0, dec: grid.dec0 });
      expect(skyToPixel(grid, grid.ra0, grid.dec0)).toEqual({ x: grid.cx, y: grid.cy });
    });

    it("has north up and east left", () => {
      const north = skyToPixel(grid, grid.ra0, grid.dec0 + 0.01);
      expect(north.y).toBeLessThan(grid.cy);
      expect(north.x).toBeCloseTo(grid.cx, 6);
      const east = skyToPixel(grid, grid.ra0 + 0.01 / Math.cos(grid.dec0 * RAD), grid.dec0);
      expect(east.x).toBeLessThan(grid.cx);
    });
  });
});

describe("gridOf", () => {
  it("takes the centre from the manifest and the rest from its grid", () => {
    const grid = gridOf({
      centre: { ra: 133.7599, dec: -7.2418 },
      grid: {
        nx: 119,
        ny: 119,
        cx: 59,
        cy: 59,
        pixscale_arcsec: 3.075,
        projection: "TAN",
        row0: "north",
        col0: "east",
      },
    });
    expect(grid).toEqual({ ra0: 133.7599, dec0: -7.2418, cx: 59, cy: 59, pixscale_arcsec: 3.075 });
  });
});

describe("wrapDegrees", () => {
  it("folds angles into [0, 360)", () => {
    expect(wrapDegrees(-0.25)).toBe(359.75);
    expect(wrapDegrees(360)).toBe(0);
    expect(wrapDegrees(725)).toBe(5);
    expect(wrapDegrees(12.5)).toBe(12.5);
  });
});
