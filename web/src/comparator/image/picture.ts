/**
 * What one square paints, and how: a grey frame, a three-colour frame, a difference in units of
 * noise. Each is turned into colours by render.ts (one implementation of the stretch) and into a
 * mask of the pixels to hatch, with the same rule for "no data" as the painters.
 */
import {
  isNoData,
  type Limits,
  paintGrey,
  paintRgb,
  paintSigma,
  type RgbLimits,
  type SigmaRamp,
} from "../../player/render";

export type Picture =
  /** A frame (or another survey's image) on the grey ramp, with the sequence's own limits. */
  | { kind: "grey"; data: Float32Array; limits: Limits | null; invert: boolean }
  /** Three channels, each on its own limits shared by the sequence. */
  | {
      kind: "rgb";
      r: Float32Array;
      g: Float32Array;
      b: Float32Array;
      limits: RgbLimits;
      invert: boolean;
    }
  /** Later minus earlier (MJy/sr) and its noise: drawn on the diff-* scale in units of σ. */
  | { kind: "sigma"; data: Float32Array; sigma: number };

export interface Painted {
  /** nx × ny × 4 colours; hatched pixels carry placeholder colours the plate paints over. */
  rgba: Uint8ClampedArray;
  /** 1 where the pixel is hatched. */
  noData: Uint8Array;
  /** At least one pixel is hatched. */
  any: boolean;
}

/** 1 where a picture has no data, by the painters' own rule. */
export function noDataOf(picture: Picture): Uint8Array {
  if (picture.kind === "grey") {
    const mask = new Uint8Array(picture.data.length);
    for (let p = 0; p < mask.length; p++) {
      mask[p] = picture.limits === null || isNoData(picture.data[p]) ? 1 : 0;
    }
    return mask;
  }
  if (picture.kind === "rgb") {
    const { r, g, b, limits } = picture;
    const missing = limits.r === null || limits.g === null || limits.b === null;
    const mask = new Uint8Array(r.length);
    for (let p = 0; p < mask.length; p++) {
      mask[p] = missing || isNoData(r[p]) || isNoData(g[p]) || isNoData(b[p]) ? 1 : 0;
    }
    return mask;
  }
  const usable = Number.isFinite(picture.sigma) && picture.sigma > 0;
  const mask = new Uint8Array(picture.data.length);
  for (let p = 0; p < mask.length; p++) mask[p] = !usable || isNoData(picture.data[p]) ? 1 : 0;
  return mask;
}

/** True when any pixel of the picture is hatched. */
export function hasNoData(picture: Picture): boolean {
  return noDataOf(picture).includes(1);
}

/** Colours and hatch mask of a picture, nx pixels wide. */
export function paintPicture(picture: Picture, nx: number, ramp: SigmaRamp): Painted {
  let rgba: Uint8ClampedArray;
  if (picture.kind === "grey") {
    rgba = paintGrey(picture.data, nx, picture.limits, { invert: picture.invert });
  } else if (picture.kind === "rgb") {
    rgba = paintRgb(picture.r, picture.g, picture.b, nx, picture.limits, {
      invert: picture.invert,
    });
  } else {
    rgba = paintSigma(picture.data, nx, picture.sigma, ramp);
  }
  const noData = noDataOf(picture);
  return { rgba, noData, any: noData.includes(1) };
}
