/**
 * Fast movers that the catalogue used for the hint (Gaia DR3, through the team backend's /stars)
 * does not hold, and that name services do not know by the spellings people type.
 *
 * Every number has its source beside it. Nothing here is written from memory.
 *
 * Not in this table, on purpose:
 * - Barnard's Star and Epsilon Indi B: Gaia DR3 holds both (4472832130942575872 and
 *   6412596012146801152), so /stars finds them; measured through the team backend on 14 Nov 2026.
 */

import type { Astrometry } from "./sky";
import type { SkyPosition } from "./types";

export interface KnownMover {
  /** Display name, as the design writes it. */
  name: string;
  /** Spellings that resolve to this object as a name (compared by `nameKey`). */
  aliases: readonly string[];
  /** Where the name points: the position a reader would be given for it. */
  catalogue: SkyPosition;
  /** Where `catalogue` comes from. */
  catalogueSource: string;
  /** Position at an epoch and proper motion, for the track. */
  astrometry: Astrometry;
  /** Where `astrometry` comes from. Shown in the data notes. */
  astrometrySource: string;
}

/** Hours, minutes, seconds to degrees. */
const hms = (h: number, m: number, s: number): number => 15 * (h + m / 60 + s / 3600);
/** Degrees, arcminutes, arcseconds to degrees (sign given separately). */
const dms = (sign: 1 | -1, d: number, m: number, s: number): number =>
  sign * (d + m / 60 + s / 3600);

export const KNOWN_MOVERS: readonly KnownMover[] = [
  {
    name: "WISE 0855-0714",
    aliases: [
      "WISE 0855",
      "WISE 0855-0714",
      "WISE 0855−0714",
      "WISE J0855-0714",
      "WISE J085510.83-071442.5",
    ],
    // The position the challenge brief gives for WISE 0855 ("RA 08h55m10.831s, Dec -07d14m42.53s"),
    // which is also the position its designation WISE J085510.83-071442.5 encodes. Its track below
    // passes within 0.2″ of it in 2010 (computed, see movers.test.ts).
    catalogue: { ra: hms(8, 55, 10.831), dec: dms(-1, 7, 14, 42.53) },
    catalogueSource: "NASA Space Apps 2026 challenge brief, Planet X and SPHEREx",
    // api/tombaugh/tools/make_fixture.py, TARGETS["wise0855"]: SIMBAD, read on 14 Nov 2026,
    // quoting Kirkpatrick et al. 2021 (2021ApJS..253....7K); ICRS position at epoch J2000.
    astrometry: {
      ra: hms(8, 55, 16.53798),
      dec: dms(-1, 7, 14, 49.3728),
      epoch: 2000.0,
      pmra: -8123.7,
      pmdec: 673.2,
    },
    astrometrySource:
      "Kirkpatrick et al. 2021 (2021ApJS..253....7K) via SIMBAD: position at J2000 and proper motion",
  },
];

/** Lower case, letters and digits only: "WISE 0855−0714" and "wise 0855-0714" match. */
export function nameKey(text: string): string {
  return text.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
}

/** The known mover a typed name refers to, if any. */
export function knownMoverByName(text: string): KnownMover | null {
  const key = nameKey(text);
  if (key === "") return null;
  return KNOWN_MOVERS.find((m) => m.aliases.some((a) => nameKey(a) === key)) ?? null;
}
