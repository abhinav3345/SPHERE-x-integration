/**
 * Search: what an entry means, and whether the object it names has moved since.
 *
 * These types are the interface between the search code (this folder) and the comparator
 * (src/comparator). Change them only together with both sides.
 */

/** A direction on the sky, degrees, ICRS. */
export interface SkyPosition {
  ra: number;
  dec: number;
}

/** How an entry was understood. */
export type QueryKind = "degrees" | "sexagesimal" | "name";

/** An entry that could be read. */
export interface Resolved {
  /** The entry exactly as typed. Never rewritten. */
  query: string;
  kind: QueryKind;
  /** What the entry means as written. For a name: the catalogue position, which may be decades old. */
  position: SkyPosition;
  /** One sentence for the message line, e.g. "Read as RA 133.79513°, Dec −7.24515°." */
  readAs: string;
  /** Display name when the entry was a name or a known alias, else null. */
  name: string | null;
  /** Where the position came from. */
  source: "typed" | "team-api" | "known-movers";
}

export type Compass =
  | "north"
  | "north-east"
  | "east"
  | "south-east"
  | "south"
  | "south-west"
  | "west"
  | "north-west";

/** A fast mover that was at the entered position once and is somewhere else now. */
export interface MoverHint {
  /** "WISE 0855−0714", "Barnard's Star", or "Gaia DR3 4472832130942575872" when it has no other name. */
  name: string;
  /** The year the object was nearest the entered position. */
  wasHereYear: number;
  /** Where it is at the reference epoch of the frames (2026.0). */
  now: SkyPosition;
  /** Separation between the entered position and `now`, arcseconds. */
  offsetArcsec: number;
  /** Direction from the entered position to `now`. East is left on screen. */
  direction: Compass;
  /** Where the motion comes from, e.g. "Gaia DR3 proper motion". Shown in the data notes. */
  source: string;
  /** The banner sentence, e.g. "WISE 0855−0714 was here in 2010. It is now 126″ to the west." */
  sentence: string;
}

/** Why an entry could not be used. `message` is written for the reader and says what to do. */
export type SearchErrorCode =
  | "empty"
  | "range"
  | "unreadable"
  | "not_found"
  | "solar_system"
  | "unavailable";

export class SearchError extends Error {
  readonly code: SearchErrorCode;
  constructor(code: SearchErrorCode, message: string) {
    super(message);
    this.name = "SearchError";
    this.code = code;
  }
}

export interface SearchOptions {
  signal?: AbortSignal;
}
