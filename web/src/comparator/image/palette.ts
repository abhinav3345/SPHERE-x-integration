/**
 * The canvas's colours, read once from the design tokens (tokens.css): the two greys of the
 * hatch and the eleven steps of the difference scale. Nothing here names a colour of its own;
 * should a token ever be unreadable, render.ts's built-in values stand in.
 */
import {
  DIVERGING_NEGATIVE,
  DIVERGING_POSITIVE,
  DIVERGING_ZERO,
  NO_DATA_BASE,
  NO_DATA_STRIPE,
  type Rgb,
  type SigmaRamp,
} from "../../player/render";
import { parseCssColour } from "./colour";
import type { Hatch } from "./device";

export interface Palette {
  hatch: Hatch;
  ramp: SigmaRamp;
}

let cached: Palette | null = null;

function read(style: CSSStyleDeclaration, name: string): Rgb | null {
  return parseCssColour(style.getPropertyValue(`--${name}`));
}

/** The palette of the page's tokens. */
export function palette(): Palette {
  if (cached) return cached;
  const style = getComputedStyle(document.documentElement);
  const a = read(style, "nodata-a");
  const b = read(style, "nodata-b");
  const zero = read(style, "diff-zero");
  const steps = (side: string) => [1, 2, 3, 4, 5].map((n) => read(style, `diff-${side}-${n}`));
  const earlier = steps("earlier");
  const later = steps("later");
  const complete = (list: Array<Rgb | null>): list is Rgb[] => list.every((c) => c !== null);
  if (a && b && zero && complete(earlier) && complete(later)) {
    cached = { hatch: { a, b }, ramp: { earlier, zero, later } };
    return cached;
  }
  // Tokens not readable (not loaded yet): stand-ins, not cached, so the tokens win next time.
  return {
    hatch: { a: NO_DATA_STRIPE, b: NO_DATA_BASE },
    ramp: {
      zero: DIVERGING_ZERO,
      earlier: [1, 2, 3, 4, 5].map((n) => mix(DIVERGING_ZERO, DIVERGING_POSITIVE, n / 5)),
      later: [1, 2, 3, 4, 5].map((n) => mix(DIVERGING_ZERO, DIVERGING_NEGATIVE, n / 5)),
    },
  };
}

function mix(from: Rgb, to: Rgb, f: number): Rgb {
  return [
    Math.round(from[0] + (to[0] - from[0]) * f),
    Math.round(from[1] + (to[1] - from[1]) * f),
    Math.round(from[2] + (to[2] - from[2]) * f),
  ];
}
