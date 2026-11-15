/**
 * Sky grid of a field: a north-up gnomonic (TAN) projection centred on the field centre.
 *
 * This is the only projection code in the front end. It implements Contract v1.0 section 2
 * formula for formula (the Python twin is api/tombaugh/grid.py) and is tested against
 * docs/contract/vectors/grid.json, which astropy generated independently.
 *
 * Pixel convention: row 0 is the northern edge, column 0 the eastern edge, and pixel centres
 * sit at integer coordinates. So x grows to the west (right on screen) and y to the south
 * (down on screen), exactly as a canvas draws.
 */
import type { Manifest } from "../contract";

/** Arcseconds per radian, as written in the contract. */
const ARCSEC_PER_RADIAN = 206264.806;
const RADIANS_PER_DEGREE = Math.PI / 180;

/** What the projection needs (the table of section 2). */
export interface SkyGrid {
  /** Right ascension of the field centre, ICRS degrees. */
  ra0: number;
  /** Declination of the field centre, ICRS degrees. */
  dec0: number;
  /** Column of the pixel centred on (ra0, dec0). */
  cx: number;
  /** Row of the pixel centred on (ra0, dec0). */
  cy: number;
  /** Arcsec per pixel. */
  pixscale_arcsec: number;
}

/** Plane pixel coordinates: x is the column (grows west), y the row (grows south). */
export interface PixelPosition {
  x: number;
  y: number;
}

/** ICRS position in decimal degrees. */
export interface SkyPosition {
  ra: number;
  dec: number;
}

/** The projection grid of a manifest: its `grid` object plus its `centre`. */
export function gridOf(manifest: Pick<Manifest, "centre" | "grid">): SkyGrid {
  return {
    ra0: manifest.centre.ra,
    dec0: manifest.centre.dec,
    cx: manifest.grid.cx,
    cy: manifest.grid.cy,
    pixscale_arcsec: manifest.grid.pixscale_arcsec,
  };
}

/**
 * Sky position (degrees) to plane pixel coordinates.
 * Only meaningful within 90 degrees of the field centre, like any gnomonic projection.
 */
export function skyToPixel(grid: SkyGrid, ra: number, dec: number): PixelPosition {
  const k = ARCSEC_PER_RADIAN / grid.pixscale_arcsec;
  const dec0 = grid.dec0 * RADIANS_PER_DEGREE;
  const delta = dec * RADIANS_PER_DEGREE;
  const dAlpha = (ra - grid.ra0) * RADIANS_PER_DEGREE;

  const d = Math.sin(dec0) * Math.sin(delta) + Math.cos(dec0) * Math.cos(delta) * Math.cos(dAlpha);
  const xi = (Math.cos(delta) * Math.sin(dAlpha)) / d; // east positive
  const eta =
    (Math.cos(dec0) * Math.sin(delta) - Math.sin(dec0) * Math.cos(delta) * Math.cos(dAlpha)) / d; // north positive
  return { x: grid.cx - k * xi, y: grid.cy - k * eta };
}

/** Plane pixel coordinates to sky position (degrees, right ascension in [0, 360)). */
export function pixelToSky(grid: SkyGrid, x: number, y: number): SkyPosition {
  const k = ARCSEC_PER_RADIAN / grid.pixscale_arcsec;
  const dec0 = grid.dec0 * RADIANS_PER_DEGREE;
  const xi = (grid.cx - x) / k;
  const eta = (grid.cy - y) / k;

  const rho = Math.sqrt(xi * xi + eta * eta);
  if (rho === 0) return { ra: wrapDegrees(grid.ra0), dec: grid.dec0 }; // the centre itself
  const c = Math.atan(rho);
  const delta = Math.asin(
    Math.cos(c) * Math.sin(dec0) + (eta * Math.sin(c) * Math.cos(dec0)) / rho,
  );
  const dAlpha = Math.atan2(
    xi * Math.sin(c),
    rho * Math.cos(dec0) * Math.cos(c) - eta * Math.sin(dec0) * Math.sin(c),
  );
  return {
    ra: wrapDegrees(grid.ra0 + dAlpha / RADIANS_PER_DEGREE),
    dec: delta / RADIANS_PER_DEGREE,
  };
}

/** Folds an angle in degrees into [0, 360). */
export function wrapDegrees(angle: number): number {
  const wrapped = angle % 360;
  return wrapped < 0 ? wrapped + 360 : wrapped;
}
