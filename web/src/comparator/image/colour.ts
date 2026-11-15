/**
 * Colours for the canvas come from the design tokens (tokens.css), read at run time, so the
 * tokens stay the one source: this file only parses what getComputedStyle returns.
 */
import type { Rgb } from "../../player/render";

/** "#2b2b2b", "#fff", "rgb(0 0 0)", "rgba(0, 0, 0, 0.62)" to [r, g, b]; null when unreadable. */
export function parseCssColour(text: string): Rgb | null {
  const value = text.trim().toLowerCase();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/.exec(value);
  if (hex) {
    const digits = hex[1];
    const full =
      digits.length === 3
        ? digits
            .split("")
            .map((d) => d + d)
            .join("")
        : digits;
    return [
      Number.parseInt(full.slice(0, 2), 16),
      Number.parseInt(full.slice(2, 4), 16),
      Number.parseInt(full.slice(4, 6), 16),
    ];
  }
  const rgb = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/.exec(value);
  if (rgb) {
    const parts = [rgb[1], rgb[2], rgb[3]].map((n) => Math.round(Number(n)));
    if (parts.every((n) => Number.isFinite(n) && n >= 0 && n <= 255)) {
      return [parts[0], parts[1], parts[2]];
    }
  }
  return null;
}
