import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DIVERGING_NEGATIVE,
  DIVERGING_POSITIVE,
  DIVERGING_ZERO,
  differenceLimits,
  divergingColour,
  isNoData,
  type Limits,
  NO_DATA_BASE,
  NO_DATA_STRIPE,
  paintDiverging,
  paintGrey,
  paintRgb,
  paintSigma,
  percentile,
  pooledLimits,
  renderDiverging,
  renderGrey,
  type SigmaRamp,
  sigmaColour,
  stretch,
  stretchSigned,
} from "./render";

const NAN = Number.NaN;
const synthetic_frame = (pixels: number[], sigma: number) => ({
  data: new Float32Array(pixels),
  sigma,
});

/** The four bytes of one pixel. */
const pixelAt = (rgba: Uint8ClampedArray, pixel: number) =>
  Array.from(rgba.subarray(pixel * 4, pixel * 4 + 4));

/** Relative luminance of an sRGB colour (WCAG definition). */
function luminance([r, g, b]: readonly number[]): number {
  const linear = (channel: number) => {
    const c = channel / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("percentile", () => {
  it("interpolates linearly between ranks", () => {
    const sorted = [1, 2, 3, 4, 5];
    expect(percentile(sorted, 0)).toBe(1);
    expect(percentile(sorted, 25)).toBe(2);
    expect(percentile(sorted, 50)).toBe(3);
    expect(percentile(sorted, 99.5)).toBeCloseTo(4.98, 12); // rank 3.98
    expect(percentile(sorted, 100)).toBe(5);
    expect(percentile([1, 2], 50)).toBe(1.5);
  });

  it("handles one value and none", () => {
    expect(percentile([7], 99.5)).toBe(7);
    expect(percentile([], 50)).toBeNaN();
  });
});

describe("pooledLimits", () => {
  it("pools every frame of the sequence into one set of limits", () => {
    const limits = pooledLimits([
      synthetic_frame([0, 1, 2, NAN], 0.5),
      synthetic_frame([3, 4, 100, NAN], 0.7),
      synthetic_frame([NAN, NAN, NAN, NAN], NAN), // a visit with no data in this band
    ]);
    // sigma_ref = median(0.5, 0.7); pooled pixels 0 1 2 3 4 100, rank 4.975 -> 4 + 96 * 0.975
    expect(limits?.sigmaRef).toBeCloseTo(0.6, 12);
    expect(limits?.vmin).toBeCloseTo(-1.2, 12);
    expect(limits?.soften).toBeCloseTo(1.8, 12);
    expect(limits?.vmax).toBeCloseTo(97.6, 4);
  });

  it("never sets the top below 10 sigma", () => {
    const limits = pooledLimits([synthetic_frame([-1, 0, 0.5, 1], 1)]);
    expect(limits).toEqual({ sigmaRef: 1, vmin: -2, vmax: 10, soften: 3 });
  });

  it("does not depend on the order of the frames", () => {
    const a = synthetic_frame([0, 5, 9, NAN], 0.2);
    const b = synthetic_frame([40, 1, NAN, 3], 0.4);
    const c = synthetic_frame([2, 2, 2, 60], 0.3);
    expect(pooledLimits([a, b, c])).toEqual(pooledLimits([c, a, b]));
  });

  it("returns null when no pixel is finite", () => {
    expect(pooledLimits([synthetic_frame([NAN, NAN], NAN)])).toBeNull();
    expect(pooledLimits([])).toBeNull();
  });

  it("estimates the noise from the pixels when the frames carry none", () => {
    // median 1, absolute deviations 0 1 1 2 2 -> MAD 1 -> 1.4826
    const limits = pooledLimits([synthetic_frame([-1, 0, 1, 2, 3], NAN)]);
    expect(limits?.sigmaRef).toBeCloseTo(1.4826, 6);
    expect(limits?.vmin).toBeCloseTo(-2.9652, 6);
  });

  it("ignores infinities", () => {
    const limits = pooledLimits([synthetic_frame([0, 1, Number.POSITIVE_INFINITY], 1)]);
    expect(limits?.vmax).toBe(10);
  });
});

describe("stretch", () => {
  const limits: Limits = { sigmaRef: 1, vmin: -2, vmax: 10, soften: 3 };

  it("maps vmin to 0 and vmax to 1 and clips outside", () => {
    expect(stretch(-2, limits)).toBe(0);
    expect(stretch(10, limits)).toBe(1);
    expect(stretch(-50, limits)).toBe(0);
    expect(stretch(1e6, limits)).toBe(1);
  });

  it("follows asinh in between", () => {
    // (asinh(0) - asinh(-2/3)) / (asinh(10/3) - asinh(-2/3)) = 0.625145 / 2.544042
    expect(stretch(0, limits)).toBeCloseTo(0.24573, 5);
  });

  it("is monotonic", () => {
    let previous = -1;
    for (let value = -2; value <= 10; value += 0.25) {
      const t = stretch(value, limits);
      expect(t).toBeGreaterThan(previous);
      previous = t;
    }
  });
});

describe("paintGrey", () => {
  const limits: Limits = { sigmaRef: 1, vmin: -2, vmax: 10, soften: 3 };

  it("draws black at vmin, white at vmax and grey in between", () => {
    const rgba = paintGrey(new Float32Array([-2, 10, 0, 0]), 2, limits);
    expect(rgba).toHaveLength(16);
    expect(pixelAt(rgba, 0)).toEqual([0, 0, 0, 255]);
    expect(pixelAt(rgba, 1)).toEqual([255, 255, 255, 255]);
    expect(pixelAt(rgba, 2)).toEqual([63, 63, 63, 255]); // round(255 * 0.24573)
  });

  it("draws NaN as the no-data hatch, never as zero and never as a grey", () => {
    // 4 x 2 pixels, all without data: stripes where (column + row) is a multiple of 4.
    const rgba = paintGrey(new Float32Array(8).fill(NAN), 4, limits);
    expect(pixelAt(rgba, 0)).toEqual([...NO_DATA_STRIPE, 255]);
    expect(pixelAt(rgba, 1)).toEqual([...NO_DATA_BASE, 255]);
    expect(pixelAt(rgba, 4)).toEqual([...NO_DATA_BASE, 255]); // column 0, row 1
    expect(pixelAt(rgba, 7)).toEqual([...NO_DATA_STRIPE, 255]); // column 3, row 1

    const zero = pixelAt(paintGrey(new Float32Array([0]), 1, limits), 0);
    for (const colour of [NO_DATA_BASE, NO_DATA_STRIPE]) {
      expect([...colour, 255]).not.toEqual(zero);
      expect(colour[0] === colour[1] && colour[1] === colour[2]).toBe(false);
    }
  });

  it("treats infinities as no data", () => {
    const rgba = paintGrey(new Float32Array([Number.POSITIVE_INFINITY]), 1, limits);
    expect(pixelAt(rgba, 0)).toEqual([...NO_DATA_STRIPE, 255]);
  });

  it("draws everything as no data when there are no limits", () => {
    const rgba = paintGrey(new Float32Array([NAN, NAN]), 2, null);
    expect(pixelAt(rgba, 0)).toEqual([...NO_DATA_STRIPE, 255]);
    expect(pixelAt(rgba, 1)).toEqual([...NO_DATA_BASE, 255]);
  });

  it("gives equal brightness the same grey in every frame of a sequence", () => {
    const first = synthetic_frame([0.3, 5, NAN, 1], 0.2);
    const second = synthetic_frame([80, 0.3, 2, NAN], 0.6);
    const shared = pooledLimits([first, second]);
    const a = paintGrey(first.data, 2, shared);
    const b = paintGrey(second.data, 2, shared);
    expect(pixelAt(a, 0)).toEqual(pixelAt(b, 1));
  });
});

describe("difference map", () => {
  it("has a neutral midpoint, an orange positive arm and a blue negative arm", () => {
    expect(divergingColour(0)).toEqual([...DIVERGING_ZERO]);
    expect(divergingColour(1)).toEqual([...DIVERGING_POSITIVE]);
    expect(divergingColour(-1)).toEqual([...DIVERGING_NEGATIVE]);
    expect(divergingColour(5)).toEqual([...DIVERGING_POSITIVE]);
    const [zr, zg, zb] = DIVERGING_ZERO;
    expect(Math.max(zr, zg, zb) - Math.min(zr, zg, zb)).toBeLessThanOrEqual(2); // grey, no hue
    expect(divergingColour(0.5)[0]).toBeGreaterThan(divergingColour(0.5)[2]); // orange: red > blue
    expect(divergingColour(-0.5)[2]).toBeGreaterThan(divergingColour(-0.5)[0]); // blue: blue > red
  });

  it("gets steadily lighter along both arms, to a similar lightness", () => {
    for (const sign of [1, -1]) {
      let previous = luminance(divergingColour(0));
      for (let step = 1; step <= 10; step++) {
        const current = luminance(divergingColour((sign * step) / 10));
        expect(current).toBeGreaterThan(previous);
        previous = current;
      }
    }
    const difference = luminance(DIVERGING_POSITIVE) - luminance(DIVERGING_NEGATIVE);
    expect(Math.abs(difference)).toBeLessThan(0.08);
  });

  it("uses symmetric limits pooled over the difference frames", () => {
    // |pixels| sorted 1 2 4, rank 1.99 -> 3.98, below the 10 sigma floor of 5
    expect(differenceLimits([synthetic_frame([-4, 1, 2, NAN], 0.5)])).toEqual({
      sigmaRef: 0.5,
      vmin: -5,
      vmax: 5,
      soften: 1.5,
    });
    const bright = differenceLimits([synthetic_frame([-40, 1, 2, NAN], 0.5)]);
    expect(bright?.vmax).toBeCloseTo(39.62, 4); // 2 + 38 * 0.99
    expect(bright?.vmin).toBeCloseTo(-39.62, 4);
    expect(differenceLimits([synthetic_frame([NAN], NAN)])).toBeNull();
  });

  it("stretches symmetrically about zero", () => {
    const limits: Limits = { sigmaRef: 0.5, vmin: -5, vmax: 5, soften: 1.5 };
    expect(stretchSigned(0, limits)).toBe(0);
    expect(stretchSigned(5, limits)).toBe(1);
    expect(stretchSigned(-5, limits)).toBe(-1);
    expect(stretchSigned(-99, limits)).toBe(-1);
    expect(stretchSigned(2, limits)).toBeCloseTo(-stretchSigned(-2, limits), 12);
  });

  it("paints zero neutral, the extremes in full colour and NaN as the hatch", () => {
    const limits: Limits = { sigmaRef: 0.5, vmin: -5, vmax: 5, soften: 1.5 };
    const rgba = paintDiverging(new Float32Array([0, 5, -5, NAN]), 2, limits);
    expect(pixelAt(rgba, 0)).toEqual([...DIVERGING_ZERO, 255]);
    expect(pixelAt(rgba, 1)).toEqual([...DIVERGING_POSITIVE, 255]);
    expect(pixelAt(rgba, 2)).toEqual([...DIVERGING_NEGATIVE, 255]);
    expect(pixelAt(rgba, 3)).toEqual([...NO_DATA_BASE, 255]); // column 1, row 1
  });
});

describe("invert", () => {
  const limits: Limits = { sigmaRef: 1, vmin: -2, vmax: 10, soften: 3 };

  it("reverses the ramp: white at vmin, black at vmax", () => {
    const rgba = paintGrey(new Float32Array([-2, 10, 0, 0]), 2, limits, { invert: true });
    expect(pixelAt(rgba, 0)).toEqual([255, 255, 255, 255]);
    expect(pixelAt(rgba, 1)).toEqual([0, 0, 0, 255]);
    expect(pixelAt(rgba, 2)).toEqual([192, 192, 192, 255]); // 255 - 63
  });

  it("never inverts the no-data hatch", () => {
    const pixels = new Float32Array([NAN, 3, NAN, NAN, 1, NAN, NAN, NAN]);
    const plain = paintGrey(pixels, 4, limits);
    const inverted = paintGrey(pixels, 4, limits, { invert: true });
    for (const p of [0, 2, 3, 5, 6, 7]) expect(pixelAt(inverted, p)).toEqual(pixelAt(plain, p));
    expect(pixelAt(inverted, 1)).not.toEqual(pixelAt(plain, 1));
  });

  it("acts on every frame of a sequence alike", () => {
    const first = synthetic_frame([0.3, 5, NAN, 1], 0.2);
    const second = synthetic_frame([80, 0.3, 2, NAN], 0.6);
    const shared = pooledLimits([first, second]);
    const a = paintGrey(first.data, 2, shared, { invert: true });
    const b = paintGrey(second.data, 2, shared, { invert: true });
    expect(pixelAt(a, 0)).toEqual(pixelAt(b, 1));
    expect(pixelAt(a, 0)[0]).toBe(255 - pixelAt(paintGrey(first.data, 2, shared), 0)[0]);
  });

  it("reaches the renderer", () => {
    class ImageDataStandIn {
      constructor(
        readonly data: Uint8ClampedArray,
        readonly width: number,
        readonly height: number,
      ) {}
    }
    vi.stubGlobal("ImageData", ImageDataStandIn);
    const pixels = new Float32Array([-2, 10]);
    const image = renderGrey(pixels, 2, 1, limits, { invert: true });
    expect(Array.from(image.data)).toEqual(
      Array.from(paintGrey(pixels, 2, limits, { invert: true })),
    );
  });
});

describe("three-colour", () => {
  // Each channel has its own scale; a level depends on its own channel only.
  const red: Limits = { sigmaRef: 1, vmin: -2, vmax: 10, soften: 3 };
  const green: Limits = { sigmaRef: 0.1, vmin: -0.2, vmax: 1, soften: 0.3 };
  const blue: Limits = { sigmaRef: 10, vmin: -20, vmax: 100, soften: 30 };
  const limits = { r: red, g: green, b: blue };

  it("stretches each channel with its own limits", () => {
    const rgba = paintRgb(
      new Float32Array([10, -2, 0]),
      new Float32Array([-0.2, 1, 0]),
      new Float32Array([100, -20, 0]),
      3,
      limits,
    );
    expect(pixelAt(rgba, 0)).toEqual([255, 0, 255, 255]);
    expect(pixelAt(rgba, 1)).toEqual([0, 255, 0, 255]);
    // zero sits at the same place on every channel's scale here (each is vmin = -2σ, soften 3σ)
    expect(pixelAt(rgba, 2)).toEqual([63, 63, 63, 255]);
  });

  it("hatches a pixel that lacks a value in any channel, never drawing it as zero", () => {
    const rgba = paintRgb(
      new Float32Array([NAN, 1, 1, 1]),
      new Float32Array([0.5, NAN, 0.5, 0.5]),
      new Float32Array([5, 5, Number.POSITIVE_INFINITY, 5]),
      2,
      limits,
    );
    expect(pixelAt(rgba, 0)).toEqual([...NO_DATA_STRIPE, 255]);
    expect(pixelAt(rgba, 1)).toEqual([...NO_DATA_BASE, 255]);
    expect(pixelAt(rgba, 2)).toEqual([...NO_DATA_BASE, 255]);
    expect(pixelAt(rgba, 3)[3]).toBe(255);
    expect(pixelAt(rgba, 3).slice(0, 3)).not.toEqual([...NO_DATA_BASE]);
  });

  it("hatches everything when a channel has no limits", () => {
    const rgba = paintRgb(new Float32Array([1]), new Float32Array([1]), new Float32Array([1]), 1, {
      ...limits,
      g: null,
    });
    expect(pixelAt(rgba, 0)).toEqual([...NO_DATA_STRIPE, 255]);
  });

  it("inverts every channel, never the hatch", () => {
    const r = new Float32Array([10, NAN]);
    const g = new Float32Array([-0.2, 0]);
    const b = new Float32Array([0, 0]);
    const plain = paintRgb(r, g, b, 2, limits);
    const inverted = paintRgb(r, g, b, 2, limits, { invert: true });
    expect(pixelAt(inverted, 0)).toEqual([0, 255, 255 - pixelAt(plain, 0)[2], 255]);
    expect(pixelAt(inverted, 1)).toEqual(pixelAt(plain, 1));
  });

  it("refuses channels on different grids", () => {
    expect(() =>
      paintRgb(new Float32Array(4), new Float32Array(4), new Float32Array(3), 2, limits),
    ).toThrow(RangeError);
  });
});

describe("difference in units of noise", () => {
  // A stand-in ramp with easy numbers; the comparator reads the real one from the diff-* tokens.
  const ramp: SigmaRamp = {
    zero: [10, 10, 10],
    earlier: [
      [20, 10, 10],
      [30, 10, 10],
      [40, 10, 10],
      [50, 10, 10],
      [60, 10, 10],
    ],
    later: [
      [10, 10, 20],
      [10, 10, 30],
      [10, 10, 40],
      [10, 10, 50],
      [10, 10, 60],
    ],
  };

  it("is neutral at zero, brighter earlier below it and brighter later above it", () => {
    expect(sigmaColour(0, ramp)).toEqual([10, 10, 10]);
    expect(sigmaColour(-1, ramp)).toEqual([20, 10, 10]);
    expect(sigmaColour(1, ramp)).toEqual([10, 10, 20]);
    expect(sigmaColour(-5, ramp)).toEqual([60, 10, 10]);
    expect(sigmaColour(5, ramp)).toEqual([10, 10, 60]);
  });

  it("interpolates between whole steps and clips at five sigma", () => {
    expect(sigmaColour(0.5, ramp)).toEqual([10, 10, 15]);
    expect(sigmaColour(-2.25, ramp)).toEqual([33, 10, 10]); // 30 + 10 * 0.25 = 32.5
    expect(sigmaColour(-40, ramp)).toEqual([60, 10, 10]);
    expect(sigmaColour(99, ramp)).toEqual([10, 10, 60]);
  });

  it("divides each pixel by the noise of the difference", () => {
    const rgba = paintSigma(new Float32Array([0, 0.2, -0.6, NAN]), 2, 0.2, ramp);
    expect(pixelAt(rgba, 0)).toEqual([10, 10, 10, 255]);
    expect(pixelAt(rgba, 1)).toEqual([10, 10, 20, 255]); // +1σ
    expect(pixelAt(rgba, 2)).toEqual([40, 10, 10, 255]); // −3σ
    expect(pixelAt(rgba, 3)).toEqual([...NO_DATA_BASE, 255]);
  });

  it("hatches everything when the noise is unknown", () => {
    for (const sigma of [NAN, 0, -1]) {
      const rgba = paintSigma(new Float32Array([0.1]), 1, sigma, ramp);
      expect(pixelAt(rgba, 0)).toEqual([...NO_DATA_STRIPE, 255]);
    }
  });

  it("calls NaN and infinities no data", () => {
    expect(isNoData(NAN)).toBe(true);
    expect(isNoData(Number.NEGATIVE_INFINITY)).toBe(true);
    expect(isNoData(0)).toBe(false);
  });
});

describe("renderGrey and renderDiverging", () => {
  it("wrap the painted bytes in an ImageData of the frame's size", () => {
    // Node has no ImageData; this stand-in records what the browser's constructor would get.
    class ImageDataStandIn {
      constructor(
        readonly data: Uint8ClampedArray,
        readonly width: number,
        readonly height: number,
      ) {}
    }
    vi.stubGlobal("ImageData", ImageDataStandIn);
    const limits: Limits = { sigmaRef: 1, vmin: -2, vmax: 10, soften: 3 };
    const pixels = new Float32Array([-2, 10, NAN, 0, 0, 0]);

    const grey = renderGrey(pixels, 3, 2, limits);
    expect(grey.width).toBe(3);
    expect(grey.height).toBe(2);
    expect(Array.from(grey.data)).toEqual(Array.from(paintGrey(pixels, 3, limits)));

    const diverging = renderDiverging(pixels, 3, 2, limits);
    expect(diverging.width).toBe(3);
    expect(Array.from(diverging.data)).toEqual(Array.from(paintDiverging(pixels, 3, limits)));
  });
});
