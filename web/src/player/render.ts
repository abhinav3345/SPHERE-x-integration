/**
 * Turns frames (MJy/sr) into pixels for the canvas.
 *
 * A blink only tells the truth if every frame is drawn with the same scale, so the limits are
 * computed ONCE for the whole sequence and reused for each frame:
 *
 *   sigma_ref = median noise of the frames in the sequence
 *   vmin      = -2 sigma_ref
 *   vmax      = max(99.5th percentile of all their pixels, 10 sigma_ref)
 *   softening = 3 sigma_ref     (asinh: linear in the noise, logarithmic for bright sources)
 *
 * NaN means no data. It is drawn as a muted hatch that is not on either colour scale, never as
 * zero and never as black.
 *
 * Contrast acts through the limits (the comparator's displayLimits narrows vmax), so it reaches
 * every frame drawn with them. Invert reverses the ramp for every frame alike and never touches the
 * hatch. Three-colour frames stretch each channel on its own limits, shared by the sequence.
 */

/** Scale shared by every frame of a sequence. All values in MJy/sr. */
export interface Limits {
  /** Reference noise of the sequence. */
  sigmaRef: number;
  /** Brightness drawn as the darkest level (or as full blue in a difference). */
  vmin: number;
  /** Brightness drawn as the brightest level. */
  vmax: number;
  /** asinh softening: below it the stretch is close to linear. */
  soften: number;
}

/** What the limits are computed from: pixels and their noise. */
export interface Scalable {
  data: Float32Array;
  sigma: number;
}

export type Rgb = readonly [number, number, number];
type Rgba = Uint8ClampedArray<ArrayBuffer>;

/** How a frame is drawn besides its limits. */
export interface PaintOptions {
  /** The ramp reversed: white at vmin, black at vmax. The no-data hatch is never inverted. */
  invert?: boolean;
}

/** A pixel with no value: NaN or an infinity. Drawn hatched by every painter here. */
export const isNoData = (value: number): boolean => !Number.isFinite(value);

/** No data: a dark plum hatch, off the grey ramp and off both arms of the difference map. */
export const NO_DATA_BASE: Rgb = [44, 32, 48];
export const NO_DATA_STRIPE: Rgb = [84, 62, 90];
/** One stripe every this many pixels along the diagonal. */
const NO_DATA_PERIOD = 4;

/** Difference map: neutral grey for no change, orange where brighter, blue where fainter. */
export const DIVERGING_ZERO: Rgb = [38, 38, 36];
export const DIVERGING_POSITIVE: Rgb = [255, 158, 44];
export const DIVERGING_NEGATIVE: Rgb = [96, 170, 255];

/** The same hatch as a CSS background, for legends. */
export const NO_DATA_CSS = `repeating-linear-gradient(135deg, rgb(${NO_DATA_STRIPE.join(" ")}) 0 2px, rgb(${NO_DATA_BASE.join(" ")}) 2px 8px)`;

/**
 * Percentile of ascending values with linear interpolation between ranks (numpy's default).
 * @param q percent, 0..100
 */
export function percentile(sorted: ArrayLike<number>, q: number): number {
  if (sorted.length === 0) return Number.NaN;
  const rank = (Math.min(100, Math.max(0, q)) / 100) * (sorted.length - 1);
  const below = Math.floor(rank);
  const above = Math.ceil(rank);
  return sorted[below] + (sorted[above] - sorted[below]) * (rank - below);
}

/** Every finite pixel of every frame, ascending; `map` is applied first when given. */
function pooledPixels(frames: readonly Scalable[], map?: (value: number) => number): Float32Array {
  const total = frames.reduce((sum, frame) => sum + frame.data.length, 0);
  const pooled = new Float32Array(total);
  let count = 0;
  for (const frame of frames) {
    for (let p = 0; p < frame.data.length; p++) {
      const value = frame.data[p];
      if (Number.isFinite(value)) pooled[count++] = map ? map(value) : value;
    }
  }
  return pooled.subarray(0, count).sort();
}

/** Median of the frames' usable noise values, or NaN when none is usable. */
function medianSigma(frames: readonly Scalable[]): number {
  const sigmas = frames
    .map((frame) => frame.sigma)
    .filter((sigma) => Number.isFinite(sigma) && sigma > 0)
    .sort((a, b) => a - b);
  return percentile(sigmas, 50);
}

/** 1.4826 x the median absolute deviation: a noise estimate from the pixels themselves. */
function robustSigma(sorted: Float32Array): number {
  const median = percentile(sorted, 50);
  const deviations = sorted.map((value) => Math.abs(value - median)).sort();
  return 1.4826 * percentile(deviations, 50);
}

/** A positive reference noise: the manifest's, else the pixels' own, else 1 MJy/sr. */
function referenceSigma(frames: readonly Scalable[], fallback: () => number): number {
  const fromFrames = medianSigma(frames);
  if (fromFrames > 0) return fromFrames;
  const fromPixels = fallback();
  return fromPixels > 0 ? fromPixels : 1;
}

/**
 * The one scale for a blink sequence, or null when no frame has a finite pixel.
 * Pass every frame that will be blinked, so that they all share these limits.
 */
export function pooledLimits(frames: readonly Scalable[]): Limits | null {
  const pixels = pooledPixels(frames);
  if (pixels.length === 0) return null;
  const sigmaRef = referenceSigma(frames, () => robustSigma(pixels));
  return {
    sigmaRef,
    vmin: -2 * sigmaRef,
    vmax: Math.max(percentile(pixels, 99.5), 10 * sigmaRef),
    soften: 3 * sigmaRef,
  };
}

/**
 * The one scale for a sequence of difference frames: symmetric about zero, with
 * vmax = max(99.5th percentile of |pixel|, 10 sigma_ref) and vmin = -vmax.
 */
export function differenceLimits(frames: readonly Scalable[]): Limits | null {
  const magnitudes = pooledPixels(frames, Math.abs);
  if (magnitudes.length === 0) return null;
  // For values scattered about zero, 1.4826 x median(|value|) is the robust noise.
  const sigmaRef = referenceSigma(frames, () => 1.4826 * percentile(magnitudes, 50));
  const vmax = Math.max(percentile(magnitudes, 99.5), 10 * sigmaRef);
  return { sigmaRef, vmin: -vmax, vmax, soften: 3 * sigmaRef };
}

/** Position of a brightness on the asinh scale: 0 at vmin, 1 at vmax, clipped to 0..1. */
export function stretch(value: number, limits: Limits): number {
  const low = Math.asinh(limits.vmin / limits.soften);
  const high = Math.asinh(limits.vmax / limits.soften);
  const t = (Math.asinh(value / limits.soften) - low) / (high - low);
  return Math.min(1, Math.max(0, t));
}

/** Signed position on the symmetric asinh scale: -1 at -vmax, 0 at zero, 1 at vmax. */
export function stretchSigned(value: number, limits: Limits): number {
  const t = Math.asinh(value / limits.soften) / Math.asinh(limits.vmax / limits.soften);
  return Math.min(1, Math.max(-1, t));
}

/** Colour of the difference map at t in -1..1: blue, through neutral grey at 0, to orange. */
export function divergingColour(t: number): [number, number, number] {
  const pole = t < 0 ? DIVERGING_NEGATIVE : DIVERGING_POSITIVE;
  const amount = Math.min(1, Math.abs(t));
  return [
    Math.round(DIVERGING_ZERO[0] + (pole[0] - DIVERGING_ZERO[0]) * amount),
    Math.round(DIVERGING_ZERO[1] + (pole[1] - DIVERGING_ZERO[1]) * amount),
    Math.round(DIVERGING_ZERO[2] + (pole[2] - DIVERGING_ZERO[2]) * amount),
  ];
}

function paintNoData(rgba: Rgba, pixel: number, nx: number): void {
  const column = pixel % nx;
  const row = (pixel - column) / nx;
  const colour = (column + row) % NO_DATA_PERIOD === 0 ? NO_DATA_STRIPE : NO_DATA_BASE;
  rgba.set(colour, pixel * 4);
  rgba[pixel * 4 + 3] = 255;
}

/**
 * RGBA bytes of a frame on the grey scale: black at vmin, white at vmax, hatch where NaN.
 * With `invert` the ramp is reversed (white at vmin); the hatch stays as it is.
 * @param nx width of the frame in pixels (rows are data.length / nx)
 */
export function paintGrey(
  data: Float32Array,
  nx: number,
  limits: Limits | null,
  options: PaintOptions = {},
): Rgba {
  const invert = options.invert === true;
  const rgba = new Uint8ClampedArray(data.length * 4);
  for (let p = 0; p < data.length; p++) {
    const value = data[p];
    if (limits === null || !Number.isFinite(value)) {
      paintNoData(rgba, p, nx);
      continue;
    }
    const stretched = Math.round(255 * stretch(value, limits));
    const level = invert ? 255 - stretched : stretched;
    rgba[p * 4] = level;
    rgba[p * 4 + 1] = level;
    rgba[p * 4 + 2] = level;
    rgba[p * 4 + 3] = 255;
  }
  return rgba;
}

/** One scale per channel of a three-colour sequence, each shared by every frame. */
export interface RgbLimits {
  r: Limits | null;
  g: Limits | null;
  b: Limits | null;
}

/**
 * RGBA bytes of a three-colour frame: red, green and blue each on the asinh scale of its own
 * channel's limits. A pixel that lacks a value in ANY channel, or whose channel has no limits, is
 * hatched: a missing channel is never drawn as zero. With `invert` every channel is reversed.
 */
export function paintRgb(
  r: Float32Array,
  g: Float32Array,
  b: Float32Array,
  nx: number,
  limits: RgbLimits,
  options: PaintOptions = {},
): Rgba {
  if (g.length !== r.length || b.length !== r.length) {
    throw new RangeError("the three channels are on different grids");
  }
  const invert = options.invert === true;
  const rgba = new Uint8ClampedArray(r.length * 4);
  const level = (value: number, channel: Limits) => {
    const stretched = Math.round(255 * stretch(value, channel));
    return invert ? 255 - stretched : stretched;
  };
  for (let p = 0; p < r.length; p++) {
    const red = r[p];
    const green = g[p];
    const blue = b[p];
    if (
      limits.r === null ||
      limits.g === null ||
      limits.b === null ||
      !Number.isFinite(red) ||
      !Number.isFinite(green) ||
      !Number.isFinite(blue)
    ) {
      paintNoData(rgba, p, nx);
      continue;
    }
    rgba[p * 4] = level(red, limits.r);
    rgba[p * 4 + 1] = level(green, limits.g);
    rgba[p * 4 + 2] = level(blue, limits.b);
    rgba[p * 4 + 3] = 255;
  }
  return rgba;
}

/**
 * The difference scale in units of noise (the design system's diff-* tokens): five steps on each
 * side of a dark neutral. `earlier[0]` is the 1σ step of "brighter earlier", `earlier[4]` 5σ.
 */
export interface SigmaRamp {
  earlier: readonly Rgb[];
  zero: Rgb;
  later: readonly Rgb[];
}

/**
 * Colour of a difference of `s` noise units (later minus earlier): linear between the whole
 * steps of the ramp, clipped at ±5σ (bundle.js diffColor). Negative is brighter earlier.
 */
export function sigmaColour(s: number, ramp: SigmaRamp): [number, number, number] {
  const clipped = Math.max(-5, Math.min(5, s));
  const side = clipped < 0 ? ramp.earlier : ramp.later;
  const magnitude = Math.abs(clipped);
  const low = Math.floor(magnitude);
  const high = Math.min(5, low + 1);
  const f = magnitude - low;
  const c0 = low === 0 ? ramp.zero : side[low - 1];
  const c1 = high === 0 ? ramp.zero : side[high - 1];
  return [
    Math.round(c0[0] + (c1[0] - c0[0]) * f),
    Math.round(c0[1] + (c1[1] - c0[1]) * f),
    Math.round(c0[2] + (c1[2] - c0[2]) * f),
  ];
}

/**
 * RGBA bytes of a difference (later minus earlier, MJy/sr) on the σ scale: each pixel is
 * value / sigma noise units. Hatch where a pixel has no value, and everywhere when the noise is
 * unknown (the difference cannot then be put in units of noise).
 */
export function paintSigma(data: Float32Array, nx: number, sigma: number, ramp: SigmaRamp): Rgba {
  const usable = Number.isFinite(sigma) && sigma > 0;
  const rgba = new Uint8ClampedArray(data.length * 4);
  for (let p = 0; p < data.length; p++) {
    const value = data[p];
    if (!usable || !Number.isFinite(value)) {
      paintNoData(rgba, p, nx);
      continue;
    }
    rgba.set(sigmaColour(value / sigma, ramp), p * 4);
    rgba[p * 4 + 3] = 255;
  }
  return rgba;
}

/** RGBA bytes of a difference frame on the blue/orange scale, hatch where NaN. */
export function paintDiverging(data: Float32Array, nx: number, limits: Limits | null): Rgba {
  const rgba = new Uint8ClampedArray(data.length * 4);
  for (let p = 0; p < data.length; p++) {
    const value = data[p];
    if (limits === null || !Number.isFinite(value)) {
      paintNoData(rgba, p, nx);
      continue;
    }
    rgba.set(divergingColour(stretchSigned(value, limits)), p * 4);
    rgba[p * 4 + 3] = 255;
  }
  return rgba;
}

/** A frame as an ImageData at data resolution (nx by ny), grey scale. */
export function renderGrey(
  data: Float32Array,
  nx: number,
  ny: number,
  limits: Limits | null,
  options: PaintOptions = {},
): ImageData {
  return new ImageData(paintGrey(data, nx, limits, options), nx, ny);
}

/** A difference frame as an ImageData at data resolution (nx by ny), blue/orange scale. */
export function renderDiverging(
  data: Float32Array,
  nx: number,
  ny: number,
  limits: Limits | null,
): ImageData {
  return new ImageData(paintDiverging(data, nx, limits), nx, ny);
}
