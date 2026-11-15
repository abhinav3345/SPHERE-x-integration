/**
 * The removable parts of the comparator (docs/design/comparator/Handoff-removable.dc.html), one
 * flag each. A part that is not finished is switched off HERE, never left half done: every block
 * reads these flags and closes the gap exactly as the hand-off says ("How a gap closes").
 *
 * Every part is being built: the owner asked that none be dropped. Name search follows the search
 * lane: it is on only when it reports that names can be looked up. The moved-object banner is
 * always on ("never cut", CLAUDE.md section 11): its known movers (WISE 0855 at the brief's own
 * coordinates) need no network, and findMover resolves to null when it has nothing, so the banner
 * simply does not appear. Switching a flag off is the last resort for a part that cannot be made
 * right.
 */
import { NAME_LOOKUP_AVAILABLE } from "../overlays/resolve";

export interface Features {
  /** Search by name, or by hours and degrees. Off: only the hint changes (SEARCH_HINT). */
  nameSearch: boolean;
  /** The moved-object banner and "Go to where it is now". Off: the notice is not rendered. */
  movedBanner: boolean;
  /** The flip key (1280: first in the playback; phone: the dock). Off: transport comes first. */
  holdToFlip: boolean;
  /** Side by side: a cell of the view switch, two squares, two labels, the pair block. */
  sideBySide: boolean;
  /** Difference image: a cell of the view switch, the difference scale, the pair block. */
  difference: boolean;
  /** Then and now: a cell of the view switch and the other survey's square. */
  thenAndNow: boolean;
  /** The Contrast slider and its label. Off: the note becomes the group's first line. */
  contrast: boolean;
  /** The Invert toggle. Off: Markers starts the row. */
  invert: boolean;
  /** The Spotlight button in the ring row, and Esc closing it. */
  spotlight: boolean;
  /** The ninth band option and the R, G, B bars on the rule and in the legend. */
  threeColour: boolean;
  /** The Spectrum button in the ring row and its panel. */
  spectrum: boolean;
  /** The dashed square for 2010, the Gaia cross and the CatWISE diamond, and their legend items. */
  catalogueMarkers: boolean;
  /** Copy link and its status in the header. Off: the chip moves to the end of the header. */
  copyLink: boolean;
}

export type FeatureName = keyof Features;

export const FEATURES: Readonly<Features> = {
  nameSearch: NAME_LOOKUP_AVAILABLE,
  movedBanner: true,
  holdToFlip: true,
  sideBySide: true,
  difference: true,
  thenAndNow: true,
  contrast: true,
  invert: true,
  spotlight: true,
  threeColour: true,
  spectrum: true,
  catalogueMarkers: true,
  copyLink: true,
};

/** A copy of FEATURES with some flags changed: for tests, and for nothing else. */
export function withFeatures(changes: Partial<Features>): Readonly<Features> {
  return { ...FEATURES, ...changes };
}
