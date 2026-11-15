import { describe, expect, it } from "vitest";
import type { Rgb } from "../../player/render";
import { parseCssColour } from "./colour";
import { hatchStripe, onStripe, paintPlate } from "./device";

// Two easy greys for the hatch; the page reads the real ones from nodata-a and nodata-b.
const hatch: { a: Rgb; b: Rgb } = { a: [1, 1, 1], b: [2, 2, 2] };

/** A synthetic 2 × 2 image: four distinct colours, pixel 3 without data. */
function synthetic_image() {
  const rgba = new Uint8ClampedArray([10, 0, 0, 255, 20, 0, 0, 255, 30, 0, 0, 255, 0, 0, 0, 255]);
  const noData = new Uint8Array([0, 0, 0, 1]);
  return { rgba, noData };
}

const at = (bytes: Uint8ClampedArray, side: number, x: number, y: number) =>
  Array.from(bytes.subarray((y * side + x) * 4, (y * side + x) * 4 + 4));

describe("the hatch", () => {
  it("is a third of a displayed pixel wide, never under one device pixel", () => {
    expect(hatchStripe(1)).toBe(1);
    expect(hatchStripe(3)).toBe(1);
    expect(hatchStripe(4)).toBe(1);
    expect(hatchStripe(6)).toBe(2);
    expect(hatchStripe(12)).toBe(4);
    expect(hatchStripe(15)).toBe(5);
  });

  it("runs at 45 degrees and is anchored to the image origin", () => {
    // stripe 2, period 4: (X + Y) mod 4 in 0..1 is the stripe
    expect([0, 1, 2, 3, 4, 5].map((x) => onStripe(x, 0, 2))).toEqual([
      true,
      true,
      false,
      false,
      true,
      true,
    ]);
    expect(onStripe(3, 1, 2)).toBe(true); // the same diagonal as (0, 0)… (X + Y = 4)
    expect(onStripe(-1, 0, 2)).toBe(false); // before the origin, the pattern continues
    expect(onStripe(-3, -1, 2)).toBe(true);
  });
});

describe("paintPlate", () => {
  it("copies every image pixel into k × k device pixels, never mixing neighbours", () => {
    const { rgba } = synthetic_image();
    const bytes = paintPlate(rgba, null, 2, 2, 3, { x0: 0, y0: 0, size: 2 }, hatch);
    expect(bytes).toHaveLength(6 * 6 * 4);
    for (let y = 0; y < 6; y++) {
      for (let x = 0; x < 6; x++) {
        const source = Math.floor(y / 3) * 2 + Math.floor(x / 3);
        expect(at(bytes, 6, x, y)).toEqual(Array.from(rgba.subarray(source * 4, source * 4 + 4)));
      }
    }
  });

  it("hatches no-data pixels in the two greys only, opaque", () => {
    const { rgba, noData } = synthetic_image();
    const k = 6;
    const bytes = paintPlate(rgba, noData, 2, 2, k, { x0: 0, y0: 0, size: 2 }, hatch);
    const seen = new Set<string>();
    for (let y = k; y < 2 * k; y++) {
      for (let x = k; x < 2 * k; x++) {
        const pixel = at(bytes, 2 * k, x, y);
        seen.add(pixel.join(","));
        expect(pixel).toEqual(onStripe(x, y, hatchStripe(k)) ? [1, 1, 1, 255] : [2, 2, 2, 255]);
      }
    }
    // Every no-data pixel holds both greys.
    expect(seen).toEqual(new Set(["1,1,1,255", "2,2,2,255"]));
    // Its neighbours are untouched.
    expect(at(bytes, 2 * k, 0, 0)).toEqual([10, 0, 0, 255]);
  });

  it("keeps the hatch on the image's grid in a crop", () => {
    const { rgba, noData } = synthetic_image();
    const k = 3;
    const whole = paintPlate(rgba, noData, 2, 2, k, { x0: 0, y0: 0, size: 2 }, hatch);
    const crop = paintPlate(rgba, noData, 2, 2, k, { x0: 1, y0: 1, size: 1 }, hatch);
    for (let y = 0; y < k; y++) {
      for (let x = 0; x < k; x++) {
        expect(at(crop, k, x, y)).toEqual(at(whole, 2 * k, x + k, y + k));
      }
    }
  });

  it("leaves the part of a crop beyond the image transparent: surround, never sky", () => {
    const { rgba } = synthetic_image();
    const bytes = paintPlate(rgba, null, 2, 2, 2, { x0: -1, y0: 1, size: 3 }, hatch);
    expect(bytes).toHaveLength(6 * 6 * 4);
    expect(at(bytes, 6, 0, 0)).toEqual([0, 0, 0, 0]); // column −1
    expect(at(bytes, 6, 2, 0)).toEqual([30, 0, 0, 255]); // pixel (0, 1)
    expect(at(bytes, 6, 4, 1)).toEqual([0, 0, 0, 255]); // pixel (1, 1)
    expect(at(bytes, 6, 2, 2)).toEqual([0, 0, 0, 0]); // row 2 is past the bottom
  });

  it("refuses a scale that is not a whole number of device pixels", () => {
    const { rgba } = synthetic_image();
    expect(() => paintPlate(rgba, null, 2, 2, 2.5, { x0: 0, y0: 0, size: 2 }, hatch)).toThrow(
      RangeError,
    );
  });
});

describe("parseCssColour", () => {
  it("reads the forms getComputedStyle returns for the tokens", () => {
    expect(parseCssColour("#2b2b2b")).toEqual([43, 43, 43]);
    expect(parseCssColour(" #A3A3A3 ")).toEqual([163, 163, 163]);
    expect(parseCssColour("#fff")).toEqual([255, 255, 255]);
    expect(parseCssColour("rgb(34, 34, 34)")).toEqual([34, 34, 34]);
    expect(parseCssColour("rgba(0, 0, 0, 0.62)")).toEqual([0, 0, 0]);
    expect(parseCssColour("rgb(1 2 3)")).toEqual([1, 2, 3]);
  });

  it("returns null for anything else", () => {
    expect(parseCssColour("")).toBeNull();
    expect(parseCssColour("red")).toBeNull();
    expect(parseCssColour("#12345")).toBeNull();
    expect(parseCssColour("rgb(300, 0, 0)")).toBeNull();
  });
});
