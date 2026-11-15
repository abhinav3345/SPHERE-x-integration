/**
 * What is drawn over the image, in screen pixels (Markers in bundle.js: marker, track, spotlight,
 * overlayMarkup; Handoff-components: pixel cursor, spotlight zoom). Pure functions: each returns
 * an SVG path or a point on the plate. Markers keep their size in screen pixels at every scale.
 */
import { type PlateCrop, pixelToPlate } from "../../player/screen";

/** The system's marker shapes, centred on (0, 0), screen pixels. */
export const MARKER_PATHS = {
  /** The position ring. */
  position: "M-9 0a9 9 0 1 0 18 0a9 9 0 1 0 -18 0",
  /** Gaia DR3: an open cross. */
  gaia: "M0 -12V-5M0 5V12M-12 0H-5M5 0H12",
  /** CatWISE: a diamond. */
  catwise: "M0 -9L9 0L0 9L-9 0Z",
  /** Where the catalogue says the object was: a square, dashed by its class. */
  was: "M-11 -11H11V11H-11Z",
} as const;

export type MarkerKind = keyof typeof MARKER_PATHS;

/** The spotlight dims everything outside a circle of this many image pixels around the ring. */
export const SPOT_RADIUS_IMAGE_PX = 12;

/** Half a screen pixel: where overlayMarkup rounds marker centres, so strokes stay crisp. */
const toHalf = (value: number) => Math.round(value * 2) / 2;

export interface PlatePoint {
  x: number;
  y: number;
}

/** Centre of a marker for image position (x, y) on this plate, rounded to half a pixel. */
export function markerPoint(crop: PlateCrop, x: number, y: number): PlatePoint {
  const at = pixelToPlate(crop, { x, y });
  return { x: toHalf(at.x), y: toHalf(at.y) };
}

/** True when a point lies on the plate (the plate clips what reaches past its edge). */
export function onPlate(crop: PlateCrop, point: PlatePoint): boolean {
  const side = crop.size * crop.scale;
  return point.x >= 0 && point.y >= 0 && point.x <= side && point.y <= side;
}

/** A full circle as one path, starting at its left. */
export function circlePath(cx: number, cy: number, r: number): string {
  return `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;
}

/** The pixel cursor: the outline of one image pixel (4 px square at 4×, 12 px in the spotlight). */
export function cursorPath(crop: PlateCrop, x: number, y: number): string {
  const k = crop.scale;
  const left = (x - crop.x0) * k;
  const top = (y - crop.y0) * k;
  return `M${left} ${top}h${k}v${k}h${-k}Z`;
}

/**
 * The spotlight: `dim` covers the plate except a circle of SPOT_RADIUS_IMAGE_PX image pixels
 * around the ring (fill-rule evenodd), `ring` is that circle's 1 px edge.
 */
export function spotlightPaths(
  crop: PlateCrop,
  ringX: number,
  ringY: number,
): { dim: string; ring: string } {
  const centre = pixelToPlate(crop, { x: ringX, y: ringY });
  const side = crop.size * crop.scale;
  const ring = circlePath(centre.x, centre.y, SPOT_RADIUS_IMAGE_PX * crop.scale);
  return { dim: `M0 0H${side}V${side}H0Z${ring}Z`, ring };
}

/**
 * A predicted track: a hairline through the positions in time order, with a short cross tick at
 * each visit (bundle.js track). Empty with fewer than two positions.
 */
export function trackPath(points: readonly PlatePoint[]): string {
  if (points.length < 2) return "";
  let d = `M${points.map((p) => `${p.x} ${p.y}`).join("L")}`;
  const last = points[points.length - 1];
  const dx = last.x - points[0].x;
  const dy = last.y - points[0].y;
  const length = Math.hypot(dx, dy) || 1;
  const nx = (-dy / length) * 4;
  const ny = (dx / length) * 4;
  for (const p of points) d += `M${p.x - nx} ${p.y - ny}L${p.x + nx} ${p.y + ny}`;
  return d;
}
