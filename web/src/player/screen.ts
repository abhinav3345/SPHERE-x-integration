/**
 * Between the image as drawn on screen and plane pixel coordinates.
 *
 * "Screen" positions are CSS pixels measured from the top-left corner of the drawn image.
 * Plane pixel centres sit at integer coordinates, so pixel (0, 0) covers the first
 * 1/nx by 1/ny of the box and its centre is half a pixel in from the corner.
 */
import type { PixelPosition } from "./grid";

/** Size of the drawn image in CSS pixels. */
export interface BoxSize {
  width: number;
  height: number;
}

/** A point in CSS pixels from the top-left corner of the drawn image. */
export interface ScreenPosition {
  x: number;
  y: number;
}

/** A point on the drawn image to plane pixel coordinates. */
export function screenToPixel(
  box: BoxSize,
  nx: number,
  ny: number,
  screen: ScreenPosition,
): PixelPosition {
  return {
    x: (screen.x / box.width) * nx - 0.5,
    y: (screen.y / box.height) * ny - 0.5,
  };
}

/** Plane pixel coordinates to a point on the drawn image. */
export function pixelToScreen(
  box: BoxSize,
  nx: number,
  ny: number,
  pixel: PixelPosition,
): ScreenPosition {
  return {
    x: ((pixel.x + 0.5) / nx) * box.width,
    y: ((pixel.y + 0.5) / ny) * box.height,
  };
}

/**
 * What one plate shows: a square of `size` plane pixels whose top-left pixel is (x0, y0), drawn
 * at `scale` CSS pixels per plane pixel. The whole frame is x0 = y0 = 0, size = nx; the spotlight
 * is a crop centred on the ring, which may reach past the edge of the plane (that part is
 * surround, never sky).
 */
export interface PlateCrop {
  x0: number;
  y0: number;
  size: number;
  scale: number;
}

/** The odd-sized crop of `size` pixels centred on pixel (x, y). */
export function cropCentredOn(x: number, y: number, size: number, scale: number): PlateCrop {
  const half = Math.floor(size / 2);
  return { x0: Math.round(x) - half, y0: Math.round(y) - half, size, scale };
}

/** A plane position to a point on the plate, CSS pixels from its top-left corner. */
export function pixelToPlate(crop: PlateCrop, pixel: PixelPosition): ScreenPosition {
  return {
    x: (pixel.x - crop.x0 + 0.5) * crop.scale,
    y: (pixel.y - crop.y0 + 0.5) * crop.scale,
  };
}

/** A point on the plate to plane coordinates (pixel centres at integers). */
export function plateToPixel(crop: PlateCrop, screen: ScreenPosition): PixelPosition {
  return {
    x: screen.x / crop.scale + crop.x0 - 0.5,
    y: screen.y / crop.scale + crop.y0 - 0.5,
  };
}

/**
 * The plane pixel under a point of the plate (column and row), or null when the point is off the
 * plate or over a part of the crop beyond the edge of an nx × ny plane.
 */
export function pixelUnder(
  crop: PlateCrop,
  nx: number,
  ny: number,
  screen: ScreenPosition,
): PixelPosition | null {
  const side = crop.size * crop.scale;
  if (!(screen.x >= 0 && screen.y >= 0 && screen.x < side && screen.y < side)) return null;
  const x = crop.x0 + Math.floor(screen.x / crop.scale);
  const y = crop.y0 + Math.floor(screen.y / crop.scale);
  return x >= 0 && y >= 0 && x < nx && y < ny ? { x, y } : null;
}
