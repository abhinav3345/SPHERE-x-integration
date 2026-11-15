/**
 * The wavelength rule of the band selector, ported from the design system's helper
 * (docs/design/system/components/bundle.js, wavelengthRule; the same drawing as rule() in
 * docs/design/comparator/Main.dc.html). 102 ticks, 17 to a detector, the chosen band lit, never a
 * rainbow: the only hue is the three channel bars of the three-colour view, where hue is the data.
 *
 * The rule is graduated by channel, not by micrometre: every detector gets the same length and its
 * 17 nominal channels (evenly spaced in log wavelength, as the instrument samples them) sit a whole
 * number of pixels apart. It is a picture of the instrument; the text alternative names the band.
 */
import type { BandId } from "../model";

/** The six detectors with the nominal ranges the system draws (BandSelector card). */
const DETECTORS = [
  { name: "D1", min: 0.74, max: 1.12 },
  { name: "D2", min: 1.1, max: 1.65 },
  { name: "D3", min: 1.64, max: 2.42 },
  { name: "D4", min: 2.42, max: 3.82 },
  { name: "D5", min: 3.81, max: 4.42 },
  { name: "D6", min: 4.41, max: 5.0 },
] as const;

/** Edge wavelengths written under the rule (Handoff-copy, section 10). */
const EDGES = ["0.74", "1.11", "1.65", "2.42", "3.82", "4.42", "5.00"] as const;

/** The selections that are not one detector. */
const SELECTIONS: Readonly<Record<"all" | "cold" | "rgb", { min: number; max: number }>> = {
  all: { min: 0.74, max: 5.0 },
  cold: { min: 4.0, max: 5.0 },
  rgb: { min: 0.74, max: 5.0 },
};

/** Three-colour channels, blue to red: two detectors each (docs/contract/presets.json "rgb"). */
const CHANNELS = [
  { key: "b", letter: "B" },
  { key: "g", letter: "G" },
  { key: "r", letter: "R" },
] as const;

export const TICKS = 102;
export const TICKS_PER_DETECTOR = 17;
/** Height of the rule; in three-colour the channel bars add 28px under it. */
export const RULE_HEIGHT = 58;
export const RULE_HEIGHT_RGB = 86;
/** Narrower than this the 102 ticks cannot be 2px apart: the helper draws nothing. */
export const RULE_MIN_WIDTH = 206;

const Y_BAND = 11;
const Y_TOP = 18;
const Y_BASE = 36;
const Y_NUM = 54;

/**
 * Half the width of an edge number ("0.74": four characters of text-micro in Source Code Pro,
 * whose advance is 0.6 em: 4 × 0.6 × 12px / 2 = 14.4px), rounded up. At a 2px pitch the detectors
 * are only 34px apart, so the end numbers are centred on their edges like the others, or the first
 * two and the last two would overlap. The designed widths (358 to 383px) all have a 3px pitch.
 */
const NUMBER_HALF = 15;

export interface RuleText {
  text: string;
  x: number;
  anchor: "start" | "middle" | "end";
}

export interface RuleDrawing {
  /** The width drawn, whole CSS pixels: the viewBox is 0 0 width height. */
  width: number;
  height: number;
  /** Pixels between ticks: a whole number, at least 2. */
  pitch: number;
  /** Length of the rule (102 × pitch) and its left edge. */
  length: number;
  x0: number;
  base: string;
  /** Path of the lit ticks (18px) and of the unlit ones (7px; the middle tick of a detector 10px). */
  lit: string;
  unlit: string;
  litCount: number;
  edges: string;
  /** The 2px line under the lit span; null in three-colour, where the channel bars say it. */
  span: string | null;
  /** Detector names above the rule, lit when the selection reaches them. */
  bands: Array<RuleText & { lit: boolean }>;
  /** Edge wavelengths under the rule. */
  numbers: RuleText[];
  /** "µm" after the last number, when there is room for it. */
  unitX: number | null;
  /** Three-colour: the channel bars under the rule, blue to red; else null. */
  channels: Array<{
    key: "r" | "g" | "b";
    letter: string;
    x: number;
    w: number;
    mid: number;
  }> | null;
}

/** Position of a wavelength along the rule, 0 to 1: each detector gets a sixth, log-spaced within. */
export function ruleFraction(lam: number): number {
  for (let i = 0; i < DETECTORS.length; i++) {
    const d = DETECTORS[i];
    if (lam <= d.max || i === DETECTORS.length - 1) {
      const f = Math.log(Math.max(lam, d.min) / d.min) / Math.log(d.max / d.min);
      return (i + Math.min(1, Math.max(0, f))) / DETECTORS.length;
    }
  }
  return 1;
}

function detectorIndex(band: BandId): number {
  return ["d1", "d2", "d3", "d4", "d5", "d6"].indexOf(band);
}

/** The drawing of the rule at `width` CSS pixels for `band`, or null when it does not fit. */
export function ruleDrawing(width: number, band: BandId): RuleDrawing | null {
  const W = Math.floor(width);
  if (!(W >= RULE_MIN_WIDTH)) return null;
  const pitch = Math.max(2, Math.floor((W - 2) / TICKS));
  const L = pitch * TICKS;
  const x0 = Math.floor((W - L) / 2);
  const rgb = band === "rgb";
  const det = detectorIndex(band);
  const range: { min: number; max: number } =
    det > -1 ? DETECTORS[det] : SELECTIONS[band as "all" | "cold" | "rgb"];
  const along = (lam: number) => x0 + ruleFraction(lam) * L;

  let lit = "";
  let unlit = "";
  let litCount = 0;
  const bands: RuleDrawing["bands"] = [];
  for (let d = 0; d < DETECTORS.length; d++) {
    const { name, min, max } = DETECTORS[d];
    for (let c = 0; c < TICKS_PER_DETECTOR; c++) {
      const n = d * TICKS_PER_DETECTOR + c;
      const centre = min * (max / min) ** ((c + 0.5) / TICKS_PER_DETECTOR);
      const on = det > -1 ? d === det : centre >= range.min && centre <= range.max;
      const x = x0 + n * pitch + Math.floor(pitch / 2) + 0.5;
      if (on) {
        lit += `M${x} ${Y_TOP}V${Y_BASE}`;
        litCount++;
      } else {
        unlit += `M${x} ${c === 8 ? Y_BASE - 10 : Y_BASE - 7}V${Y_BASE}`;
      }
    }
    bands.push({
      text: name,
      x: x0 + (d + 0.5) * TICKS_PER_DETECTOR * pitch,
      anchor: "middle",
      lit: det > -1 ? d === det : max > range.min + 0.05,
    });
  }

  // At a 2px pitch every number is centred on its edge (see NUMBER_HALF), when the margins hold it.
  const compact = pitch < 3 && x0 >= NUMBER_HALF;
  let edges = "";
  const numbers: RuleText[] = [];
  for (let e = 0; e < EDGES.length; e++) {
    const ex = x0 + e * TICKS_PER_DETECTOR * pitch + (e === 6 ? -0.5 : 0.5);
    edges += `M${ex} ${Y_TOP - 4}V${Y_BASE + 5}`;
    const end = e === 0 || e === 6;
    numbers.push({
      text: EDGES[e],
      x: end && !compact ? (e === 0 ? x0 : x0 + L) : ex,
      anchor: end && !compact ? (e === 0 ? "start" : "end") : "middle",
    });
  }
  const unitAt = compact ? x0 + L + NUMBER_HALF + 3 : x0 + L + 5;
  const unitRoom = compact ? W - unitAt >= NUMBER_HALF : W - (x0 + L) >= 24;

  const channels: RuleDrawing["channels"] = rgb
    ? CHANNELS.map((channel, k) => {
        const xa = x0 + k * 34 * pitch + (k === 0 ? 0.5 : 1.5);
        const xb = x0 + (k + 1) * 34 * pitch - (k === 2 ? 0.5 : 1.5);
        return { key: channel.key, letter: channel.letter, x: xa, w: xb - xa, mid: (xa + xb) / 2 };
      })
    : null;

  return {
    width: W,
    height: rgb ? RULE_HEIGHT_RGB : RULE_HEIGHT,
    pitch,
    length: L,
    x0,
    base: `M${x0} ${Y_BASE + 0.5}H${x0 + L}`,
    lit,
    unlit,
    litCount,
    edges,
    span: rgb ? null : `M${along(range.min)} ${Y_BASE + 1.5}H${along(range.max)}`,
    bands,
    numbers,
    unitX: unitRoom ? unitAt : null,
    channels,
  };
}

/** Rows of the rule's text, for the component: band names at 11, numbers at 54, letters at 82. */
export const RULE_Y = { band: Y_BAND, number: Y_NUM, channel: 62.5, channelHeight: 6, letter: 82 };
