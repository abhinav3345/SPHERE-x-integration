/**
 * How the comparator writes every value it prints. Pure functions, no DOM.
 *
 * Values that change with the frame come in a fixed-length form (README of the design system,
 * rule 1; Handoff-images "what changes, and why nothing moves"), so a field set in Source Code Pro
 * never changes width when the frame changes. Displayed numbers use the true minus (U+2212).
 */

export const MINUS = "−";
export const EN_DASH = "–";
export const EM_DASH = "—";
export const ARCSEC = "″";
export const ARCMIN = "′";
export const TIMES = "×";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

interface Day {
  year: number;
  /** 0..11 */
  month: number;
  day: number;
}

/** "2025-11-07" -> parts. Throws on anything else: dates come from the manifest, never typed. */
export function parseIsoDate(iso: string): Day {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) throw new RangeError(`not an ISO date: "${iso}"`);
  return { year: Number(match[1]), month: Number(match[2]) - 1, day: Number(match[3]) };
}

const monthName = (day: Day) => MONTHS[day.month];
const two = (n: number) => String(n).padStart(2, "0");

/**
 * Short form, for timeline rows and pair tags (Timeline card): "5–6 May 2025",
 * "31 Oct–14 Nov 2025", "28 Dec 2025–3 Jan 2026", or "5 May 2025" for one day.
 */
export function shortDateRange(startIso: string, endIso: string): string {
  const a = parseIsoDate(startIso);
  const b = parseIsoDate(endIso);
  if (a.year !== b.year) {
    return `${a.day} ${monthName(a)} ${a.year}${EN_DASH}${b.day} ${monthName(b)} ${b.year}`;
  }
  if (a.month !== b.month) {
    return `${a.day} ${monthName(a)}${EN_DASH}${b.day} ${monthName(b)} ${b.year}`;
  }
  if (a.day !== b.day) return `${a.day}${EN_DASH}${b.day} ${monthName(b)} ${b.year}`;
  return `${b.day} ${monthName(b)} ${b.year}`;
}

/**
 * Fixed form, for the frame label (FrameLabel card): "05 May to 06 May 2025", always 21
 * characters within one year. A range across a new year reads "28 Dec 2025 to 03 Jan 2026"
 * (26 characters); selectors pad every label of a sequence to its longest, so the field still
 * keeps one width while frames change.
 */
export function fixedDateRange(startIso: string, endIso: string): string {
  const a = parseIsoDate(startIso);
  const b = parseIsoDate(endIso);
  if (a.year !== b.year) {
    return `${two(a.day)} ${monthName(a)} ${a.year} to ${two(b.day)} ${monthName(b)} ${b.year}`;
  }
  return `${two(a.day)} ${monthName(a)} to ${two(b.day)} ${monthName(b)} ${b.year}`;
}

/** One date for a fact chip: "5 Oct 2026". */
export function shortDate(iso: string): string {
  const d = parseIsoDate(iso);
  return `${d.day} ${monthName(d)} ${d.year}`;
}

/** Replaces a leading hyphen-minus with the true minus. */
export function trueMinus(text: string): string {
  return text.startsWith("-") ? `${MINUS}${text.slice(1)}` : text;
}

/** Right ascension in degrees: "133.75977°". */
export function formatRa(ra: number, digits = 5): string {
  return `${ra.toFixed(digits)}°`;
}

/** Declination in degrees, always signed: "−7.24183°", "+4.76820°". */
export function formatDec(dec: number, digits = 5): string {
  const sign = dec < 0 ? MINUS : "+";
  return `${sign}${Math.abs(dec).toFixed(digits)}°`;
}

/** "RA 133.7598°  Dec −7.2422°": the position line of the title strip (4 decimals, 0.36″). */
export function positionLine(ra: number, dec: number): string {
  return `RA ${formatRa(ra, 4)}  Dec ${formatDec(dec, 4)}`;
}

/** "Read as RA 133.7598°, Dec −7.2422°." */
export function readAsSentence(ra: number, dec: number, digits = 4): string {
  return `Read as RA ${formatRa(ra, digits)}, Dec ${formatDec(dec, digits)}.`;
}

/** The exposure count of the frame label, right-aligned in three characters: "  9 exposures". */
export function countFixed(n: number | null): string {
  const digits = n === null ? EM_DASH : String(n);
  const noun = n === 1 ? "exposure " : "exposures";
  return `${digits.padStart(3, " ")} ${noun}`;
}

/** A timeline row's count with its qualifiers: "11 exposures, partial", "4 exposures, thin". */
export function rowCount(n: number, thin: boolean, partial: boolean): string {
  const words = [`${n} ${n === 1 ? "exposure" : "exposures"}`];
  if (thin) words.push("thin");
  if (partial) words.push("partial");
  return words.join(", ");
}

/** Wavelength range at fixed length: "3.96 to 5.00 µm"; "—.—— to —.—— µm" when unknown. */
export function rangeFixed(lamMin: number, lamMax: number): string {
  if (!Number.isFinite(lamMin) || !Number.isFinite(lamMax)) {
    return `${EM_DASH}.${EM_DASH}${EM_DASH} to ${EM_DASH}.${EM_DASH}${EM_DASH} µm`;
  }
  return `${lamMin.toFixed(2)} to ${lamMax.toFixed(2)} µm`;
}

/** The same range, spoken: "3.96 to 5.00 micrometres". */
export function rangeSpoken(lamMin: number, lamMax: number): string {
  if (!Number.isFinite(lamMin) || !Number.isFinite(lamMax)) return "wavelength range unknown";
  return `${lamMin.toFixed(2)} to ${lamMax.toFixed(2)} micrometres`;
}

/** A brightness with no more precision than the data has: "0.142", "−0.0180", "1.26", "214". */
export function brightness(value: number): string {
  if (!Number.isFinite(value)) return "no data";
  const text = Math.abs(value) >= 1000 ? String(Math.round(value)) : value.toPrecision(3);
  return trueMinus(text);
}

/** A difference in units of noise, signed: "+2.3 σ", "−0.4 σ", "0.0 σ". */
export function sigmas(value: number): string {
  if (!Number.isFinite(value)) return "no data";
  const rounded = Math.round(value * 10) / 10;
  if (rounded === 0) return "0.0 σ";
  return `${rounded > 0 ? "+" : MINUS}${Math.abs(rounded).toFixed(1)} σ`;
}

/** "Frame 2 of 4". */
export function frameCounter(shown: number, count: number): string {
  return `Frame ${shown + 1} of ${count}`;
}

/** "2 per second". */
export function speedLabel(speed: number): string {
  return `${speed} per second`;
}

/** A scale such as 4 (CSS px per image pixel) as "4×"; a fractional one as "1.7×". */
export function scaleLabel(scale: number): string {
  const text = Number.isInteger(scale) ? String(scale) : scale.toFixed(1);
  return `${text}${TIMES}`;
}

/** First letter upper case, final full stop: manifest warnings are written as phrases. */
export function asSentence(text: string): string {
  const trimmed = text.trim();
  if (trimmed === "") return trimmed;
  const capital = trimmed[0].toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capital) ? capital : `${capital}.`;
}
