/**
 * Positions on the sky and straight-line proper motion: the one front-end implementation.
 *
 * A star with proper motion moves along a straight line in space; seen from here that is the
 * normalised vector p0 + v·(t − t0), where p0 is the unit vector at the catalogue epoch and v the
 * proper motion in the tangent plane there. This matches astropy's `apply_space_motion` without
 * distance or radial velocity (as used by api/tombaugh/tools/make_fixture.py) to well under a
 * milliarcsecond over decades. Parallax is not applied: positions are barycentric directions.
 *
 * Units: degrees (ICRS) for positions, mas/yr for proper motion (pmra already times cos dec),
 * Julian years for epochs, arcseconds for separations.
 */

import type { Compass, SkyPosition } from "./types";

/** The epoch the frames call "now" (Contract v1.0 `epoch_ref`). */
export const EPOCH_NOW = 2026.0;

export const ARCSEC_PER_RAD = (180 * 3600) / Math.PI;
const DEG = Math.PI / 180;
const MAS_TO_RAD = 1 / (ARCSEC_PER_RAD * 1000);

/** A catalogue position at an epoch with its proper motion. */
export interface Astrometry extends SkyPosition {
  /** Julian year of `ra` and `dec`. */
  epoch: number;
  /** mas/yr, already times cos(dec). */
  pmra: number;
  /** mas/yr. */
  pmdec: number;
}

type Vec3 = readonly [number, number, number];

function unitVector(p: SkyPosition): Vec3 {
  const a = p.ra * DEG;
  const d = p.dec * DEG;
  return [Math.cos(d) * Math.cos(a), Math.cos(d) * Math.sin(a), Math.sin(d)];
}

function toSky(v: Vec3): SkyPosition {
  const [x, y, z] = v;
  const ra = (Math.atan2(y, x) / DEG + 360) % 360;
  return { ra, dec: Math.atan2(z, Math.hypot(x, y)) / DEG };
}

/** Unit vectors pointing east and north at a position. */
function eastNorth(p: SkyPosition): { east: Vec3; north: Vec3 } {
  const a = p.ra * DEG;
  const d = p.dec * DEG;
  return {
    east: [-Math.sin(a), Math.cos(a), 0],
    north: [-Math.sin(d) * Math.cos(a), -Math.sin(d) * Math.sin(a), Math.cos(d)],
  };
}

const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const add = (a: Vec3, b: Vec3, k = 1): Vec3 => [a[0] + k * b[0], a[1] + k * b[1], a[2] + k * b[2]];
const cross = (a: Vec3, b: Vec3): Vec3 => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];

/** Angle between two direction vectors (any length), radians. Stable for tiny angles. */
function angleBetween(a: Vec3, b: Vec3): number {
  const c = cross(a, b);
  return Math.atan2(Math.hypot(c[0], c[1], c[2]), dot(a, b));
}

/** Start vector and tangent-plane velocity (radians per year) of a track. */
function track(a: Astrometry): { p0: Vec3; v: Vec3 } {
  const { east, north } = eastNorth(a);
  const v = add(
    [east[0] * a.pmra, east[1] * a.pmra, east[2] * a.pmra],
    [north[0] * a.pmdec, north[1] * a.pmdec, north[2] * a.pmdec],
  );
  return { p0: unitVector(a), v: [v[0] * MAS_TO_RAD, v[1] * MAS_TO_RAD, v[2] * MAS_TO_RAD] };
}

/** Where a star is at `epoch` (Julian year), moved by proper motion alone. */
export function propagate(a: Astrometry, epoch: number): SkyPosition {
  const { p0, v } = track(a);
  return toSky(add(p0, v, epoch - a.epoch));
}

/** Angular distance between two positions, arcseconds. */
export function separationArcsec(a: SkyPosition, b: SkyPosition): number {
  return angleBetween(unitVector(a), unitVector(b)) * ARCSEC_PER_RAD;
}

/** Position angle of `to` seen from `from`, degrees east of north, 0 to 360. */
export function positionAngleDeg(from: SkyPosition, to: SkyPosition): number {
  const { east, north } = eastNorth(from);
  const d = add(unitVector(to), unitVector(from), -1);
  return (((Math.atan2(dot(d, east), dot(d, north)) / DEG) % 360) + 360) % 360;
}

const COMPASS: readonly Compass[] = [
  "north",
  "north-east",
  "east",
  "south-east",
  "south",
  "south-west",
  "west",
  "north-west",
];

/** The nearest of the eight compass points to a position angle (degrees east of north). */
export function compassPoint(positionAngle: number): Compass {
  const k = Math.round((((positionAngle % 360) + 360) % 360) / 45) % 8;
  return COMPASS[k] as Compass;
}

export interface Approach {
  /** Julian year of the closest approach, inside the searched span. */
  epoch: number;
  /** Distance at that moment, arcseconds. */
  distanceArcsec: number;
}

/**
 * The moment between `from` and `to` (Julian years) when a star's track came nearest to `target`.
 * The nearest point is found in the tangent plane at the catalogue position (exact for a straight
 * line there; the projection errs by about the square of the angle, nothing at arcminutes) and
 * clamped to the span; the distance is then measured on the sphere.
 */
export function closestApproach(
  a: Astrometry,
  target: SkyPosition,
  from: number,
  to: number,
): Approach {
  const { p0, v } = track(a);
  const q = unitVector(target);
  const along = dot(q, p0);
  const vv = dot(v, v);
  let dt = 0;
  if (vv > 0 && along > 0) {
    // Gnomonic projection of the target onto the plane touching the sphere at p0.
    const qt = add([q[0] / along, q[1] / along, q[2] / along], p0, -1);
    dt = dot(qt, v) / vv;
  }
  const epoch = Math.min(to, Math.max(from, a.epoch + dt));
  const at = add(p0, v, epoch - a.epoch);
  return { epoch, distanceArcsec: angleBetween(at, q) * ARCSEC_PER_RAD };
}

const MS_PER_JULIAN_YEAR = 365.25 * 86_400_000;
/** J2000.0 is 2000 January 1, 12:00 TT; the minute between TT and UTC does not matter here. */
const J2000_MS = Date.UTC(2000, 0, 1, 12);

/** The calendar year (UTC) that contains a Julian-year epoch: 2010.45 is in 2010. */
export function calendarYear(julianYear: number): number {
  return new Date(J2000_MS + (julianYear - 2000) * MS_PER_JULIAN_YEAR).getUTCFullYear();
}
