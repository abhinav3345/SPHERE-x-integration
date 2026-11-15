/**
 * Every sentence search can put on screen. Strings marked "design" are word for word from
 * docs/design/comparator/Handoff-copy.dc.html (section 2) or the SearchField card; the others are
 * new, written in the system's voice: what is true, then what to do; no exclamation marks.
 */

/** Example position: WISE 0855 at the reference epoch, as in the design. */
const EXAMPLE_POSITION = "133.7599 -7.2418";
const EXAMPLE_HOURS = "08h55m10.831s -07d14m42.53s";

/** The hint under the field when names can be looked up (design). */
export const HINT_WITH_NAMES = `Try ${EXAMPLE_POSITION}, ${EXAMPLE_HOURS} or Barnard's Star.`;
/** The hint when they cannot: only the forms that work (new, the design's hint without the name). */
export const HINT_WITHOUT_NAMES = `Try ${EXAMPLE_POSITION} or ${EXAMPLE_HOURS}.`;

/** Message line while a name resolves (design). For the comparator; search itself never shows it. */
export const LOOKING_UP = "Looking up the name.";

/** Range errors (design: declination; right ascension in the pattern of the declination error). */
export const DEC_RANGE = "Declination must be between −90 and +90 degrees.";
export const RA_RANGE = "Right ascension must be between 0 and 360 degrees.";
/** New, in the same pattern. */
export const MINUTES_RANGE = "Minutes and seconds must be between 0 and 60.";

/** New. Numbers and units that do not make a position. */
export const UNREADABLE = `This could not be read as a position. Try ${EXAMPLE_POSITION} or ${EXAMPLE_HOURS}.`;

/** Design. */
export const NOT_FOUND = `No object of that name was found. Try Barnard's Star, or a position such as ${EXAMPLE_POSITION}.`;

/** New. The name service did not answer (network error, 502, 503, or nothing in 25 s). */
export const NAMES_DOWN = `Names cannot be looked up right now. Enter RA and Dec instead, such as ${EXAMPLE_POSITION}.`;

/** New. This build has no name service configured. */
export const NAMES_OFF = `Names cannot be looked up on this site. Enter RA and Dec, such as ${EXAMPLE_POSITION}.`;

/** New. Planets, moons, comets and asteroids: no fixed patch of sky holds them for months. */
export function solarSystemMessage(subject: string, namesAvailable: boolean): string {
  const advice = namesAvailable
    ? "Try a star, such as Barnard's Star."
    : `Try a position such as ${EXAMPLE_POSITION}.`;
  return `${capitalise(subject)} moves too fast to stay in one patch of sky between visits. ${advice}`;
}

/** "Read as RA 133.79513°, Dec −7.24515°." (design: five decimals, true minus). */
export function readAsMessage(ra: number, dec: number): string {
  return `Read as RA ${formatDegrees(ra, true)}°, Dec ${formatDegrees(dec, false)}°.`;
}

/**
 * Five decimals (0.036″), the true minus for negative values, no plus sign (as the design writes
 * "Dec −7.24515°"). A value that rounds to zero has no sign; right ascension that rounds to 360
 * is written 0.
 */
export function formatDegrees(value: number, isRightAscension: boolean): string {
  let text = Math.abs(value).toFixed(5);
  if (isRightAscension && text === "360.00000") text = "0.00000";
  const negative = value < 0 && !/^0\.0+$/.test(text);
  return negative ? `−${text}` : text;
}

/** The moved-object banner: "WISE 0855-0714 was here in 2010. It is now 126″ to the west." */
export function moverSentence(
  subject: string,
  year: number,
  offsetArcsec: number,
  direction: string,
): string {
  return `${capitalise(subject)} was here in ${year}. It is now ${Math.round(offsetArcsec)}″ to the ${direction}.`;
}

/** The subject for a Gaia star with no name of its own. */
export function unnamedStar(gaiaName: string): string {
  return `A fast-moving star (${gaiaName})`;
}

/**
 * First letter upper case, for a name that starts a sentence ("barnard's star" was typed). Only
 * a to z: a Greek Bayer letter ("α Cen") must stay lower case.
 */
export function capitalise(text: string): string {
  return /^[a-z]/.test(text) ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}
