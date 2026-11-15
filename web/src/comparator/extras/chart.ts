/**
 * The spectrum chart's geometry, ported from `spectrum()` and `shapePath()` in
 * docs/design/system/components/bundle.js (the SpectrumChart card): flux in microjansky against
 * wavelength from 0.75 to 5.0 µm, ticks at 1 to 5 µm, one series colour and one shape per visit in
 * time order, per-exposure points first and the larger binned points on top, hollow flagged
 * points, a vertical error bar on every point. The flux axis follows the data (the design's 0 to
 * 240 was for its example values): it always includes zero, every unflagged point and every
 * binned point with its error bar, and the flagged points too when they are at least half of the
 * points (a bright star whose centre overflowed in most exposures: they ARE its spectrum). A few
 * flagged points or a long error bar beyond that are clipped at the plot's edge (`clip`), so a
 * few faint, noisy exposures cannot flatten the rest; `outside` counts the points clipped so, and
 * the panel says so. The table holds every value.
 */
import { MINUS } from "../format";
import type { SpectrumPointVM, SpectrumVM } from "./types";

export const LAMBDA_MIN = 0.75;
export const LAMBDA_MAX = 5.0;

/** The system's five shapes, by series number 1 to 5. */
export const SHAPES = ["circle", "square", "triangle", "diamond", "triangle-down"] as const;
export type Shape = (typeof SHAPES)[number];

/** Which series tokens a number of visits uses, earliest to latest (bundle.js SERIES_FOR). */
const SERIES_FOR: Record<number, number[]> = {
  1: [3],
  2: [1, 5],
  3: [1, 3, 5],
  4: [1, 2, 4, 5],
  5: [1, 2, 3, 4, 5],
};

/** The series number (1 to 5) of each visit. */
export function seriesFor(visits: number): number[] {
  return SERIES_FOR[Math.min(Math.max(visits, 1), 5)].slice(0, Math.max(visits, 0));
}

const r1 = (value: number) => Math.round(value * 10) / 10;

/** An SVG path for a marker shape centred on (x, y). */
export function shapePath(shape: Shape, x: number, y: number, r: number): string {
  const cx = r1(x);
  const cy = r1(y);
  switch (shape) {
    case "square":
      return `M${r1(cx - r)} ${r1(cy - r)}h${2 * r}v${2 * r}h${-2 * r}Z`;
    case "triangle":
      return `M${cx} ${r1(cy - r * 1.2)}L${r1(cx + r * 1.15)} ${r1(cy + r * 0.85)}L${r1(cx - r * 1.15)} ${r1(cy + r * 0.85)}Z`;
    case "triangle-down":
      return `M${cx} ${r1(cy + r * 1.2)}L${r1(cx + r * 1.15)} ${r1(cy - r * 0.85)}L${r1(cx - r * 1.15)} ${r1(cy - r * 0.85)}Z`;
    case "diamond":
      return `M${cx} ${r1(cy - r * 1.3)}L${r1(cx + r * 1.3)} ${cy}L${cx} ${r1(cy + r * 1.3)}L${r1(cx - r * 1.3)} ${cy}Z`;
    default:
      return `M${r1(cx - r)} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0Z`;
  }
}

/** A step of 1, 2, 2.5 or 5 times a power of ten, so that `span` takes about `count` steps (0 to 240 in steps of 50). */
export function niceStep(span: number, count = 4): number {
  if (!(span > 0) || !Number.isFinite(span)) return 1;
  const raw = span / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / power;
  // The nice step nearest the raw one (geometric midpoints between 1, 2, 2.5, 5 and 10).
  const nice = unit < 1.5 ? 1 : unit < 2.25 ? 2 : unit < 3.5 ? 2.5 : unit < 7.5 ? 5 : 10;
  return nice * power;
}

/** Tick text with the true minus and only the decimals the step needs. */
export function tickLabel(value: number, step: number): string {
  const decimals = (String(Number(step.toPrecision(6))).split(".")[1] ?? "").length;
  const text = (Math.abs(value) < step / 1e6 ? 0 : value).toFixed(Math.min(decimals, 6));
  return text.startsWith("-") ? `${MINUS}${text.slice(1)}` : text;
}

export interface Tick {
  at: number;
  label: string;
}

export interface SeriesGeometry {
  /** 1 to 5: the class bc-series-N. */
  series: number;
  /** Error bars of the per-exposure points. */
  err: string;
  /** Filled per-exposure points. */
  pts: string;
  /** Hollow (flagged) per-exposure points. */
  flag: string;
  /** Error bars and shapes of the binned points. */
  berr: string;
  bin: string;
}

export interface ChartGeometry {
  width: number;
  height: number;
  viewBox: string;
  /** The plot area. */
  left: number;
  right: number;
  top: number;
  bottom: number;
  grid: string;
  axis: string;
  yTicks: Tick[];
  xTicks: Array<Tick & { anchor: "middle" | "end" }>;
  /** The plot area as a rectangle: points and error bars are clipped to it. */
  clip: { x: number; y: number; width: number; height: number };
  /** The band on screen, as a lighter rectangle; null when it does not overlap the axis. */
  band: { x: number; width: number } | null;
  xTitle: { x: number; y: number };
  yTitle: { transform: string };
  series: SeriesGeometry[];
  /** Per-exposure points whose flux lies beyond the flux axis (drawn clipped, or not at all). */
  outside: number;
}

/**
 * The flux range of the chart: zero, every unflagged point, every binned point with its error,
 * and every flagged point when flagged points are at least half of them.
 */
export function fluxRange(
  points: readonly SpectrumPointVM[],
  binned: readonly SpectrumPointVM[],
): [number, number] {
  let lo = 0;
  let hi = 0;
  const good = points.filter((p) => !p.flagged);
  const firm = points.length - good.length >= good.length ? points : good;
  for (const p of firm) {
    lo = Math.min(lo, p.flux);
    hi = Math.max(hi, p.flux);
  }
  for (const p of binned) {
    lo = Math.min(lo, p.flux - Math.abs(p.err));
    hi = Math.max(hi, p.flux + Math.abs(p.err));
  }
  if (hi <= lo) hi = lo + 1;
  return [lo, hi];
}

/** The chart of a spectrum at a size in CSS pixels, with the band on screen as [lo, hi] µm. */
export function chartGeometry(
  spectrum: Pick<SpectrumVM, "visits" | "points" | "binned">,
  width: number,
  height: number,
  band: [number, number] | null,
): ChartGeometry {
  const [lo, hi] = fluxRange(spectrum.points, spectrum.binned);
  const step = niceStep(hi - lo);
  const y0 = Math.floor(lo / step) * step;
  const y1 = Math.ceil(hi / step) * step;
  const yTicks: Tick[] = [];
  for (let v = y0, i = 0; v <= y1 + step / 2 && i < 50; v += step, i++) {
    yTicks.push({ at: v, label: tickLabel(v, step) });
  }
  // The left margin holds the rotated axis title (its glyphs reach about 14 px from the edge)
  // and, right of it, the longest tick label (Source Code Pro at the micro size, under 7.5 px a
  // character), so the two never overlap.
  const chars = Math.max(...yTicks.map((tick) => tick.label.length));
  const ml = Math.max(40, 22 + Math.ceil(7.5 * chars));
  const mr = 10;
  const mt = 10;
  const mb = 40;
  const xOf = (lam: number) =>
    ml + ((lam - LAMBDA_MIN) / (LAMBDA_MAX - LAMBDA_MIN)) * (width - ml - mr);
  const yOf = (flux: number) => mt + (1 - (flux - y0) / (y1 - y0)) * (height - mt - mb);

  let grid = "";
  let axis = "";
  for (const tick of yTicks) {
    const gy = Math.round(yOf(tick.at)) + 0.5;
    const line = `M${ml} ${gy}H${width - mr}`;
    if (tick.at === 0) axis += line;
    else grid += line;
    tick.at = gy;
  }
  // The zero line is the axis; when zero is not a tick (it always is here) the bottom is.
  if (axis === "") axis += `M${ml} ${Math.round(yOf(y0)) + 0.5}H${width - mr}`;
  const xTicks: ChartGeometry["xTicks"] = [];
  for (let u = 1; u <= 5; u++) {
    const gx = Math.round(xOf(u)) + (u === 5 ? -0.5 : 0.5);
    axis += `M${gx} ${height - mb}V${height - mb + 5}`;
    xTicks.push({
      at: u === 5 ? width - mr : gx,
      label: String(u),
      anchor: u === 5 ? "end" : "middle",
    });
  }
  axis += `M${ml + 0.5} ${mt}V${height - mb}`;

  let bandRect: ChartGeometry["band"] = null;
  if (band && band[1] > LAMBDA_MIN && band[0] < LAMBDA_MAX) {
    const a = xOf(Math.max(band[0], LAMBDA_MIN));
    const b = xOf(Math.min(band[1], LAMBDA_MAX));
    bandRect = { x: r1(a), width: r1(b - a) };
  }

  const map = seriesFor(spectrum.visits.length);
  const series: SeriesGeometry[] = map.map((n, visit) => {
    const shape = SHAPES[n - 1];
    const g: SeriesGeometry = { series: n, err: "", pts: "", flag: "", berr: "", bin: "" };
    for (const p of spectrum.points) {
      if (p.visit !== visit) continue;
      const cx = r1(xOf(p.lam));
      g.err += `M${cx} ${r1(yOf(p.flux - p.err))}V${r1(yOf(p.flux + p.err))}`;
      if (p.flagged) g.flag += shapePath(shape, cx, yOf(p.flux), 3);
      else g.pts += shapePath(shape, cx, yOf(p.flux), 2.5);
    }
    for (const p of spectrum.binned) {
      if (p.visit !== visit) continue;
      const bx = r1(xOf(p.lam));
      g.berr += `M${bx} ${r1(yOf(p.flux - p.err))}V${r1(yOf(p.flux + p.err))}`;
      g.bin += shapePath(shape, bx, yOf(p.flux), 5);
    }
    return g;
  });

  return {
    width,
    height,
    viewBox: `0 0 ${width} ${height}`,
    left: ml,
    right: width - mr,
    top: mt,
    bottom: height - mb,
    grid,
    axis,
    clip: { x: ml, y: mt, width: width - ml - mr, height: height - mt - mb },
    yTicks,
    xTicks,
    band: bandRect,
    xTitle: { x: (ml + width - mr) / 2, y: height - 6 },
    yTitle: { transform: `translate(11 ${(mt + height - mb) / 2}) rotate(-90)` },
    series,
    outside: spectrum.points.filter((p) => p.flux < y0 || p.flux > y1).length,
  };
}

/** The note under a chart that clips points: "3 points lie outside the chart; the table holds every value." */
export function outsideNote(outside: number): string | null {
  if (outside <= 0) return null;
  return `${outside} ${outside === 1 ? "point lies" : "points lie"} outside the chart; the table holds every value.`;
}
