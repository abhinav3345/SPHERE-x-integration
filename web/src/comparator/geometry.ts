/**
 * Layout and image scale (docs/design/comparator/Handoff-behaviour and Handoff-images).
 *
 * The frame is a square whose size depends only on the layout, never on the image. The image
 * takes the largest whole number of DEVICE pixels per image pixel that fits the square, so a
 * 119 px field is 4× (476 px) at 1280, 5× (595 px) at 1440 and 3× (357 px) on a phone, and a
 * 197 px field (10′) is 2× (394 px) at 1280. Pure functions, no DOM.
 */
import { NATIVE_PIXEL_ARCSEC } from "../contract";

/** "phone" under 720 px wide; "rail" 720 to 1279; "three" from 1280; "wide" from 1440 × 900. */
export type Layout = "phone" | "rail" | "three" | "wide";

/** The media queries behind each layout, widest first. Used with matchMedia. */
export const LAYOUT_QUERIES = {
  wide: "(min-width: 1440px) and (min-height: 900px)",
  three: "(min-width: 1280px)",
  rail: "(min-width: 720px)",
} as const;

/** The layout for a window of this size, exactly as the breakpoints table of Handoff-behaviour. */
export function layoutFor(width: number, height: number): Layout {
  if (width >= 1440 && height >= 900) return "wide";
  if (width >= 1280) return "three";
  if (width >= 720) return "rail";
  return "phone";
}

/** The 6′ frame of the contract: 119 × 119 image pixels. */
export const DEFAULT_IMAGE_PX = 119;
/** The spotlight redraws this many image pixels around the ring (an odd number: the ring's pixel is the centre). */
export const SPOT_CROP_PX = 39;
/** ...at this many times the scale of the frame. */
export const SPOT_FACTOR = 3;
/** The scale bar is drawn this long on the sky at the layout's own scale. */
export const SCALE_BAR_ARCSEC = 60;
/** Arcsec per image pixel of every frame: half the native SPHEREx pixel. */
export const PIXSCALE_ARCSEC = NATIVE_PIXEL_ARCSEC / 2;

/** CSS px per image pixel of a 119 px frame in each layout: the scale the boards are drawn at. */
export const BASE_SCALE: Readonly<Record<Layout, number>> = {
  phone: 3,
  rail: 3,
  three: 4,
  wide: 5,
};

/** How one image sits in one square. */
export interface Fit {
  /** Side of the square (the frame), CSS px. */
  square: number;
  /** Image pixels drawn along one side: the field's nx, or the spotlight crop. */
  imagePx: number;
  /** Whole device pixels per image pixel. */
  devicePerPixel: number;
  /** CSS px per image pixel: devicePerPixel / dpr. Whole on a 1× screen. */
  scale: number;
  /** Side of the drawn image (the plate), CSS px: imagePx × scale. Centred in the square. */
  plate: number;
}

/** The largest whole device-pixel scale at which `imagePx` pixels fit in `square` CSS px. */
export function fitImage(square: number, imagePx: number, dpr: number): Fit {
  const density = dpr > 0 && Number.isFinite(dpr) ? dpr : 1;
  const devicePerPixel = Math.max(1, Math.floor((square * density) / imagePx));
  const scale = devicePerPixel / density;
  return { square, imagePx, devicePerPixel, scale, plate: imagePx * scale };
}

/**
 * The spotlight: the pixels around the ring at three times the frame's scale. The crop is
 * 39 × 39 for a 119 px frame and smaller when 39 would not fit the square (small fields of
 * view draw at a larger scale). Always odd, so the ring's pixel is the centre.
 */
export function fitSpotlight(base: Fit, dpr: number): Fit {
  const density = dpr > 0 && Number.isFinite(dpr) ? dpr : 1;
  const devicePerPixel = base.devicePerPixel * SPOT_FACTOR;
  const scale = devicePerPixel / density;
  let crop = Math.min(SPOT_CROP_PX, base.imagePx, Math.floor(base.square / scale));
  if (crop % 2 === 0) crop -= 1;
  crop = Math.max(1, crop);
  return { square: base.square, imagePx: crop, devicePerPixel, scale, plate: crop * scale };
}

/** Side of the frame square for one image, CSS px. Phone and rail: the measured column width. */
export function frameSquare(layout: Layout, columnWidth: number): number {
  if (layout === "three") return BASE_SCALE.three * DEFAULT_IMAGE_PX;
  if (layout === "wide") return BASE_SCALE.wide * DEFAULT_IMAGE_PX;
  return columnWidth > 0 ? columnWidth : BASE_SCALE.phone * DEFAULT_IMAGE_PX;
}

/**
 * Side of each square of a pair. At 1280 and 1440 the two squares sit side by side in a grid
 * 16 px wider than the column with a 16 px gap (Main.dc.html: `gap: 16px; margin: 0 -8px`), so
 * each is half the column: 238 px at 1280, 297.5 px at 1440. Below 1280 they stack, full width.
 */
export function pairSquare(layout: Layout, columnWidth: number): number {
  const one = frameSquare(layout, columnWidth);
  return layout === "three" || layout === "wide" ? one / 2 : one;
}

/** The scale bar: one drawn length per layout, and what that length is on the sky. */
export interface ScaleBar {
  /** Drawn length, CSS px, rounded to half a pixel (58.5, 78, 97.5). Fixed per layout. */
  lengthPx: number;
  /** What the bar measures on the sky at a given scale (CSS px per image pixel), arcsec. */
  arcsecAt(scale: number): number;
}

export function scaleBarFor(layout: Layout, pixscaleArcsec = PIXSCALE_ARCSEC): ScaleBar {
  const lengthPx = Math.round((SCALE_BAR_ARCSEC / pixscaleArcsec) * BASE_SCALE[layout] * 2) / 2;
  return {
    lengthPx,
    arcsecAt: (scale: number) => Math.round((lengthPx / scale) * pixscaleArcsec),
  };
}

/** Everything about image size and scale for one layout and one field. */
export interface Geometry {
  layout: Layout;
  /** Device pixels per CSS pixel. */
  dpr: number;
  /** The layout's scale for a 119 px frame: 3, 4 or 5. */
  baseScale: number;
  /** Image pixels along one side of the loaded field (59 to 197), 119 when none is loaded. */
  imagePx: number;
  /** One frame: Blink and Difference. */
  one: Fit;
  /** Each frame of a pair: Side by side. */
  two: Fit;
  /** The spotlight on one frame. */
  spot: Fit;
  /** The spotlight on each frame of a pair. */
  spotTwo: Fit;
  scaleBar: ScaleBar;
}

export function geometryFor(
  layout: Layout,
  columnWidth: number,
  dpr: number,
  imagePx: number = DEFAULT_IMAGE_PX,
  pixscaleArcsec: number = PIXSCALE_ARCSEC,
): Geometry {
  const one = fitImage(frameSquare(layout, columnWidth), imagePx, dpr);
  const two = fitImage(pairSquare(layout, columnWidth), imagePx, dpr);
  return {
    layout,
    dpr,
    baseScale: BASE_SCALE[layout],
    imagePx,
    one,
    two,
    spot: fitSpotlight(one, dpr),
    spotTwo: fitSpotlight(two, dpr),
    scaleBar: scaleBarFor(layout, pixscaleArcsec),
  };
}
