import { describe, expect, it } from "vitest";
import {
  circlePath,
  cursorPath,
  MARKER_PATHS,
  markerPoint,
  onPlate,
  SPOT_RADIUS_IMAGE_PX,
  spotlightPaths,
  trackPath,
} from "./overlay";

const whole = { x0: 0, y0: 0, size: 119, scale: 4 };
const spot = { x0: 40, y0: 40, size: 39, scale: 12 };

describe("marks on the plate", () => {
  it("puts a mark on the centre of its pixel, to half a screen pixel", () => {
    expect(markerPoint(whole, 59, 59)).toEqual({ x: 238, y: 238 });
    expect(markerPoint(whole, 18, 62)).toEqual({ x: 74, y: 250 });
    expect(markerPoint(whole, 18.3, 62.1)).toEqual({ x: 75, y: 250.5 });
    // The ring is the middle of the spotlight's plate.
    expect(markerPoint(spot, 59, 59)).toEqual({ x: 234, y: 234 });
  });

  it("knows what lies on the plate", () => {
    expect(onPlate(whole, { x: 0, y: 476 })).toBe(true);
    expect(onPlate(whole, { x: -0.5, y: 10 })).toBe(false);
    expect(onPlate(spot, { x: 469, y: 10 })).toBe(false);
  });

  it("keeps the system's marker shapes", () => {
    expect(MARKER_PATHS.position).toBe(circlePath(0, 0, 9));
    expect(MARKER_PATHS.was).toBe("M-11 -11H11V11H-11Z");
    expect(MARKER_PATHS.gaia).toBe("M0 -12V-5M0 5V12M-12 0H-5M5 0H12");
    expect(MARKER_PATHS.catwise).toBe("M0 -9L9 0L0 9L-9 0Z");
  });
});

describe("the pixel cursor", () => {
  it("outlines one image pixel: 4 px square at 4×, 12 px in the spotlight", () => {
    expect(cursorPath(whole, 59, 59)).toBe("M236 236h4v4h-4Z");
    expect(cursorPath(spot, 59, 59)).toBe("M228 228h12v12h-12Z");
  });
});

describe("the spotlight", () => {
  it("dims the plate outside a circle of 12 image pixels around the ring", () => {
    expect(SPOT_RADIUS_IMAGE_PX).toBe(12);
    const { dim, ring } = spotlightPaths(spot, 59, 59);
    expect(ring).toBe(circlePath(234, 234, 144));
    expect(dim).toBe(`M0 0H468V468H0Z${ring}Z`);
  });

  it("follows the scale: two frames at 6×", () => {
    const { ring } = spotlightPaths({ x0: 40, y0: 40, size: 39, scale: 6 }, 59, 59);
    expect(ring).toBe(circlePath(117, 117, 72));
  });
});

describe("a predicted track", () => {
  it("is a hairline through the positions with a cross tick at each", () => {
    const d = trackPath([
      { x: 0, y: 0 },
      { x: 10, y: 0 },
    ]);
    expect(d).toBe("M0 0L10 0M0 -4L0 4M10 -4L10 4");
  });

  it("needs two positions", () => {
    expect(trackPath([{ x: 1, y: 1 }])).toBe("");
    expect(trackPath([])).toBe("");
  });
});
