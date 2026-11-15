/**
 * Reading a typed position, in the browser and without the network.
 *
 * Accepted: decimal degrees "133.7599 -7.2418" (space or comma, keyboard hyphen or true minus,
 * optional degree signs) and hours with degrees in the forms "08h55m10.831s -07d14m42.53s",
 * "08:55:10.831 -07:14:42.53" and "08 55 10.831 -07 14 42.53" (right ascension in hours, unless
 * written in degrees with "d" or "°"). Optional "RA" and "Dec" labels, as in the brief's
 * "RA 08h55m10.831s, Dec -07d14m42.53s", are ignored.
 */

import { DEC_RANGE, MINUTES_RANGE, RA_RANGE, UNREADABLE } from "./messages";
import { type QueryKind, SearchError, type SkyPosition } from "./types";

export interface ParsedPosition {
  kind: Exclude<QueryKind, "name">;
  position: SkyPosition;
}

/**
 * Unifies what people paste: minus signs and dashes, primes and quotes, degree look-alikes,
 * unusual spaces. Used before parsing only; what the reader typed is never rewritten.
 */
export function normaliseEntry(text: string): string {
  return text
    .replace(/[−‒–—―﹣－]/g, "-")
    .replace(/＋/g, "+")
    .replace(/，/g, ",")
    .replace(/[′‘’´ʹʼ]/g, "'")
    .replace(/[″“”ʺ]/g, '"')
    .replace(/''/g, '"')
    .replace(/[º˚]/g, "°")
    .replace(/[   -​  　]/g, " ")
    .trim();
}

type Unit = "h" | "m" | "s" | "d" | "'" | '"';

interface Token {
  sign: "" | "+" | "-";
  digits: string;
  value: number;
  unit: Unit | null;
  /** Followed by ":" (the next number continues this angle). */
  colon: boolean;
  /** Followed by "," or ";" (the next number starts declination). */
  comma: boolean;
}

const TOKEN = /\s*([+-]?)\s*(\d+(?:\.\d*)?|\.\d+)\s*([hmsd°'"])?\s*(:)?\s*([,;])?\s*/y;

/** Numbers with their units, or null when the text holds anything else. */
function tokenise(text: string): Token[] | null {
  const tokens: Token[] = [];
  let at = 0;
  while (at < text.length) {
    TOKEN.lastIndex = at;
    const m = TOKEN.exec(text);
    if (m === null) return null;
    const [whole, sign = "", digits = "", unitText, colon, comma] = m;
    const unit = unitText === undefined ? null : unitText === "°" ? "d" : (unitText as Unit);
    // "1.2.3": two numbers must be separated by a space, a sign, a unit, ":" or ",".
    const next = text.charAt(TOKEN.lastIndex);
    const separated =
      unit !== null || colon !== undefined || comma !== undefined || /\s$/.test(whole);
    if (!separated && /[\d.]/.test(next)) return null;
    tokens.push({
      sign: sign as Token["sign"],
      digits,
      value: Number(digits),
      unit,
      colon: colon !== undefined,
      comma: comma !== undefined,
    });
    at = TOKEN.lastIndex;
  }
  return tokens;
}

/** Splits the numbers into right ascension and declination. */
function splitAxes(tokens: Token[]): [Token[], Token[]] | null {
  const commas = tokens.flatMap((t, i) => (t.comma ? [i] : []));
  if (commas.length > 1) return null;
  if (commas.length === 1) {
    const i = commas[0] as number;
    return i === tokens.length - 1 ? null : [tokens.slice(0, i + 1), tokens.slice(i + 1)];
  }
  const signed = tokens.findIndex((t, i) => i > 0 && t.sign !== "");
  if (signed > 0) return [tokens.slice(0, signed), tokens.slice(signed)];

  const groups: Token[][] = [];
  if (tokens.some((t) => t.colon)) {
    // 08:55:10.831 07:14:42.53
    let current: Token[] = [];
    for (const t of tokens) {
      current.push(t);
      if (!t.colon) {
        groups.push(current);
        current = [];
      }
    }
    if (current.length > 0) return null;
  } else if (tokens.some((t) => t.unit !== null)) {
    // 08h55m10.831s 07d14m42.53s, or 133.7599° 7.2418°
    tokens.forEach((t, i) => {
      const prev = tokens[i - 1];
      const starts =
        i === 0 ||
        t.unit === "h" ||
        t.unit === "d" ||
        prev?.unit === "s" ||
        prev?.unit === '"' ||
        ((prev?.unit === "d" || prev?.unit === "h") && t.unit === null);
      if (starts) groups.push([t]);
      else groups[groups.length - 1]?.push(t);
    });
  } else if (tokens.length === 2 || tokens.length === 4 || tokens.length === 6) {
    // 133.7599 7.2418, or 08 55 10.831 07 14 42.53
    const half = tokens.length / 2;
    groups.push(tokens.slice(0, half), tokens.slice(half));
  }
  return groups.length === 2 ? [groups[0] as Token[], groups[1] as Token[]] : null;
}

interface Angle {
  degrees: number;
  sexagesimal: boolean;
}

/** One axis: a decimal number, or two or three sexagesimal parts. Null when malformed. */
function readAngle(group: Token[], axis: "ra" | "dec"): Angle | null {
  const first = group[0];
  const last = group[group.length - 1];
  if (first === undefined || last === undefined || group.length > 3 || last.colon) return null;
  const rest = group.slice(1);
  const inner = group.slice(0, -1);
  if (rest.some((t) => t.sign !== "")) return null;
  if (inner.some((t) => t.digits.includes("."))) return null;
  if (inner.some((t) => t.colon) && !inner.every((t) => t.colon)) return null;
  const sign = first.sign === "-" ? -1 : 1;

  if (group.length === 1) {
    if (first.unit === null || first.unit === "d") {
      return { degrees: sign * first.value, sexagesimal: false };
    }
    if (axis === "ra" && first.unit === "h") {
      return { degrees: sign * first.value * 15, sexagesimal: true };
    }
    return null;
  }

  // Hours (or degrees) with minutes and optional seconds.
  const lead = first.unit;
  const scale = axis === "ra" && lead !== "d" ? 15 : 1;
  if (lead !== null && lead !== "d" && !(axis === "ra" && lead === "h")) return null;
  if (lead === null && rest.some((t) => t.unit !== null)) return null;
  const minutes = group[1] as Token;
  const seconds = group[2];
  const minuteUnits: (Unit | null)[] = lead === "h" ? [null, "m"] : [null, "m", "'"];
  const secondUnits: (Unit | null)[] = lead === "h" ? [null, "s"] : [null, "s", '"'];
  if (!minuteUnits.includes(minutes.unit)) return null;
  if (seconds !== undefined && !secondUnits.includes(seconds.unit)) return null;
  if (minutes.value >= 60 || (seconds?.value ?? 0) >= 60) {
    throw new SearchError("range", MINUTES_RANGE);
  }
  const value = first.value + minutes.value / 60 + (seconds?.value ?? 0) / 3600;
  return { degrees: sign * value * scale, sexagesimal: true };
}

/** "RA 08h55m10.831s, Dec -07d14m42.53s" -> "08h55m10.831s, -07d14m42.53s" (lower case in). */
function stripLabels(text: string): string {
  return text
    .replace(/^(?:r\.?a\.?|α)\s*[:=]?\s*(?=[\d+\-.])/, "")
    .replace(/(^|[\s,;])(?:decl?\.?|δ)\s*[:=]?\s*(?=[\d+\-.])/, "$1 ")
    .replace(/(?<=[\d.hmsd°'"])\s*[,;]?\s*\(?(?:j2000(?:\.0)?|icrs|fk5)\)?$/, "");
}

/**
 * Reads a typed position. Returns null when the entry is not a position (it holds letters other
 * than units: a name). Throws a SearchError ("unreadable" or "range") for numbers that do not
 * make a position, with the design's sentence.
 */
export function parseCoordinates(text: string): ParsedPosition | null {
  const lower = normaliseEntry(text).toLowerCase();
  const tokens = tokenise(stripLabels(lower));
  if (tokens === null) {
    if (/\p{L}/u.test(lower)) return null;
    throw new SearchError("unreadable", UNREADABLE);
  }
  const axes = splitAxes(tokens);
  const ra = axes && readAngle(axes[0], "ra");
  const dec = axes && readAngle(axes[1], "dec");
  if (!ra || !dec) throw new SearchError("unreadable", UNREADABLE);
  if (!(dec.degrees >= -90 && dec.degrees <= 90)) throw new SearchError("range", DEC_RANGE);
  if (!(ra.degrees >= 0 && ra.degrees < 360)) throw new SearchError("range", RA_RANGE);
  return {
    kind: ra.sexagesimal || dec.sexagesimal ? "sexagesimal" : "degrees",
    // + 0 turns a typed "-0" into 0.
    position: { ra: ra.degrees + 0, dec: dec.degrees + 0 },
  };
}
