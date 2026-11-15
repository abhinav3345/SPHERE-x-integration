/**
 * The image on a plate, at device resolution (ImageFrame card; bundle.js displayScale, paintFrame
 * and hatchPattern, ported). Pure functions, no DOM: the canvas only receives the bytes.
 *
 * - Every image pixel is k × k DEVICE pixels, k a whole number (geometry.ts fitImage gives k).
 *   Nothing is smoothed or interpolated: a pixel is copied, never resampled.
 * - A no-data pixel is hatched at 45° in the two nodata tokens, the stripe a third of a displayed
 *   image pixel (never under one device pixel), anchored to the image origin so the pattern does
 *   not move when the frame changes, in the spotlight or out of it.
 * - A crop (the spotlight) may reach past the edge of the image: those device pixels stay
 *   transparent, so the frame's surround shows. Never sky.
 */
import type { Rgb } from "../../player/render";

/** The two greys of the hatch: `a` the stripe (nodata-a), `b` the ground (nodata-b). */
export interface Hatch {
  a: Rgb;
  b: Rgb;
}

/** The part of the image a plate shows, in image pixels: top-left pixel (x0, y0), size × size. */
export interface Crop {
  x0: number;
  y0: number;
  size: number;
}

/** Stripe width in device pixels: a third of a displayed image pixel, at least one. */
export function hatchStripe(devicePerPixel: number): number {
  return Math.max(1, Math.round(devicePerPixel / 3));
}

/** True where the hatch draws its stripe, at device pixel (X, Y) counted from the image origin. */
export function onStripe(X: number, Y: number, stripe: number): boolean {
  const period = 2 * stripe;
  return (((X + Y) % period) + period) % period < stripe;
}

/**
 * RGBA bytes of a plate, (crop.size × k) device pixels square.
 * @param rgba   colours of the image pixels, nx × ny × 4 (render.ts painters)
 * @param noData 1 where a pixel is hatched, nx × ny; null when none is
 * @param k      whole device pixels per image pixel
 */
export function paintPlate(
  rgba: Uint8ClampedArray,
  noData: Uint8Array | null,
  nx: number,
  ny: number,
  k: number,
  crop: Crop,
  hatch: Hatch,
): Uint8ClampedArray<ArrayBuffer> {
  if (!Number.isInteger(k) || k < 1) throw new RangeError(`k must be a whole number, not ${k}`);
  const side = crop.size * k;
  const rowBytes = side * 4;
  const out = new Uint8ClampedArray(side * rowBytes);
  const stripe = hatchStripe(k);

  for (let j = 0; j < crop.size; j++) {
    const row = crop.y0 + j;
    if (row < 0 || row >= ny) continue; // past the edge: transparent
    const first = j * k * rowBytes;

    // One device row of this image row, then k − 1 exact copies of it.
    for (let i = 0; i < crop.size; i++) {
      const column = crop.x0 + i;
      if (column < 0 || column >= nx) continue;
      const p = (row * nx + column) * 4;
      let o = first + i * k * 4;
      for (let d = 0; d < k; d++, o += 4) {
        out[o] = rgba[p];
        out[o + 1] = rgba[p + 1];
        out[o + 2] = rgba[p + 2];
        out[o + 3] = rgba[p + 3];
      }
    }
    for (let d = 1; d < k; d++) out.copyWithin(first + d * rowBytes, first, first + rowBytes);

    if (!noData) continue;
    for (let i = 0; i < crop.size; i++) {
      const column = crop.x0 + i;
      if (column < 0 || column >= nx || noData[row * nx + column] !== 1) continue;
      for (let dy = 0; dy < k; dy++) {
        const Y = row * k + dy;
        let o = first + dy * rowBytes + i * k * 4;
        for (let dx = 0; dx < k; dx++, o += 4) {
          const colour = onStripe(column * k + dx, Y, stripe) ? hatch.a : hatch.b;
          out[o] = colour[0];
          out[o + 1] = colour[1];
          out[o + 2] = colour[2];
          out[o + 3] = 255;
        }
      }
    }
  }
  return out;
}
