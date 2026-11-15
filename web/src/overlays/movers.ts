import { KNOWN_MOVERS } from "./known-movers";
import { moverSentence, unnamedStar } from "./messages";
import {
  type Astrometry,
  calendarYear,
  closestApproach,
  compassPoint,
  EPOCH_NOW,
  positionAngleDeg,
  propagate,
  separationArcsec,
} from "./sky";
import {
  GAIA_DR3_EPOCH,
  type GaiaStar,
  getJson,
  readStarsBody,
  STARS_SIZE_ARCMIN,
  STARS_TIMEOUT_MS,
  TEAM_API,
  type TeamApi,
} from "./team-api";
import type { MoverHint, Resolved, SearchOptions } from "./types";

/** Only stars moving at least this fast are considered, mas/yr. */
export const MIN_PROPER_MOTION_MAS_YR = 300;
/** The track must pass this close to the entered position ... */
export const WAS_HERE_ARCSEC = 10;
/** ... and the star must now be at least this far from it. */
export const HAS_LEFT_ARCSEC = 10;
/** The span searched for the closest approach, Julian years. */
export const SEARCH_FROM_EPOCH = 1990.0;
export const SEARCH_TO_EPOCH = EPOCH_NOW;
/**
 * A typed name is given to the star only when its track passes this close to the name's
 * catalogue position (parallax, ignored here, is under 0.8″ for every star). A fast star that
 * merely passed near a named galaxy keeps "A fast-moving star (Gaia DR3 …)".
 */
export const NAME_MATCH_ARCSEC = 3;

/**
 * The year of a closest approach. One within 0.01 yr (3.7 days) of a whole Julian year counts as
 * that year: catalogue positions are given at J2000.0 (noon on 1 January 2000), and the rounding
 * of a typed "269.45208 4.69336" moves Barnard's Star's approach to 1999.998, the evening before.
 */
export function yearOfApproach(epoch: number): number {
  const whole = Math.round(epoch);
  return calendarYear(Math.abs(epoch - whole) < 0.01 ? whole : epoch);
}

export interface Track {
  astrometry: Astrometry;
  /** A name of its own (known movers), or null. */
  ownName: string | null;
  /** "Gaia DR3 <id>" for catalogue stars. */
  catalogueName: string | null;
  source: string;
}

interface Candidate {
  hint: MoverHint;
  closestArcsec: number;
}

/** The hint for one track, or null when it was never at the position or is still there. */
function hintFor(track: Track, resolved: Resolved): Candidate | null {
  const entered = resolved.position;
  const approach = closestApproach(track.astrometry, entered, SEARCH_FROM_EPOCH, SEARCH_TO_EPOCH);
  if (!(approach.distanceArcsec <= WAS_HERE_ARCSEC)) return null;
  const now = propagate(track.astrometry, EPOCH_NOW);
  const offsetArcsec = separationArcsec(entered, now);
  if (!(offsetArcsec >= HAS_LEFT_ARCSEC)) return null;
  const direction = compassPoint(positionAngleDeg(entered, now));
  const wasHereYear = yearOfApproach(approach.epoch);
  const typedName =
    resolved.kind === "name" &&
    resolved.name !== null &&
    approach.distanceArcsec <= NAME_MATCH_ARCSEC
      ? resolved.name
      : null;
  const name = typedName ?? track.ownName ?? track.catalogueName ?? "";
  const subject = typedName ?? track.ownName ?? unnamedStar(name);
  return {
    closestArcsec: approach.distanceArcsec,
    hint: {
      name,
      wasHereYear,
      now,
      offsetArcsec,
      direction,
      source: track.source,
      sentence: moverSentence(subject, wasHereYear, offsetArcsec, direction),
    },
  };
}

/** The candidate whose track came nearest the entered position. */
function nearest(tracks: Track[], resolved: Resolved): MoverHint | null {
  let best: Candidate | null = null;
  for (const track of tracks) {
    const c = hintFor(track, resolved);
    if (c !== null && (best === null || c.closestArcsec < best.closestArcsec)) best = c;
  }
  return best?.hint ?? null;
}

const KNOWN_TRACKS: Track[] = KNOWN_MOVERS.map((m) => ({
  astrometry: m.astrometry,
  ownName: m.name,
  catalogueName: null,
  source: m.astrometrySource,
}));

/** Gaia DR3 stars fast enough to matter, as tracks. */
export function gaiaTracks(stars: GaiaStar[]): Track[] {
  const tracks: Track[] = [];
  for (const s of stars) {
    if (s.pmra === null || s.pmdec === null) continue;
    if (Math.hypot(s.pmra, s.pmdec) < MIN_PROPER_MOTION_MAS_YR) continue;
    tracks.push({
      astrometry: { ra: s.ra, dec: s.dec, epoch: GAIA_DR3_EPOCH, pmra: s.pmra, pmdec: s.pmdec },
      ownName: null,
      catalogueName: `Gaia DR3 ${s.id}`,
      source: `Gaia DR3 ${s.id}: position at epoch 2016.0 and proper motion`,
    });
  }
  return tracks;
}

/**
 * Looks for a fast-moving object that was at the resolved position once and has since left it.
 * Resolves to null when there is none, or when the catalogues cannot be reached (never rejects
 * for that: the hint is an extra, the search result stands without it).
 */
export async function findMover(
  resolved: Resolved,
  options: SearchOptions = {},
): Promise<MoverHint | null> {
  return findMoverWith(resolved, TEAM_API, options);
}

/**
 * `findMover` with the backend and its deadline given explicitly (tests, scripts). First the
 * known movers, then Gaia DR3 around the position. Never rejects, also not when aborted.
 */
export async function findMoverWith(
  resolved: Resolved,
  api: TeamApi,
  options: SearchOptions & { timeoutMs?: number } = {},
): Promise<MoverHint | null> {
  const { signal, timeoutMs = STARS_TIMEOUT_MS } = options;
  try {
    const { ra, dec } = resolved.position;
    if (!Number.isFinite(ra) || !Number.isFinite(dec)) return null;
    const known = nearest(KNOWN_TRACKS, resolved);
    if (known !== null || api.base === null) return known;
    const params = { ra: String(ra), dec: String(dec), size: String(STARS_SIZE_ARCMIN) };
    const answer = await getJson({ ...api, base: api.base }, "/stars", params, timeoutMs, signal);
    if (answer.status < 200 || answer.status >= 300) return null;
    const stars = readStarsBody(answer.body);
    return stars === null ? null : nearest(gaiaTracks(stars), resolved);
  } catch {
    return null;
  }
}
