import { describe, expect, it } from "vitest";
import { BAND_IDS, type BandId } from "../model";
import {
  RULE_HEIGHT,
  RULE_HEIGHT_RGB,
  RULE_MIN_WIDTH,
  ruleDrawing,
  ruleFraction,
  TICKS,
  TICKS_PER_DETECTOR,
} from "./rule";

/** x of every tick in a path of "M<x> <y>V<y>" moves. */
function tickXs(path: string): number[] {
  return [...path.matchAll(/M([\d.]+) [\d.]+V[\d.]+/g)].map((m) => Number(m[1]));
}

describe("wavelength rule", () => {
  it("draws 102 ticks a whole number of pixels apart, centred, on half pixels", () => {
    for (const width of [304, 358, 362, 383, 410]) {
      const d = ruleDrawing(width, "d3");
      expect(d).not.toBeNull();
      if (!d) continue;
      const xs = [...tickXs(d.lit), ...tickXs(d.unlit)].sort((a, b) => a - b);
      expect(xs).toHaveLength(TICKS);
      for (let i = 1; i < xs.length; i++) expect(xs[i] - xs[i - 1]).toBe(d.pitch);
      for (const x of xs) expect(x - Math.floor(x)).toBe(0.5);
      expect(Number.isInteger(d.pitch)).toBe(true);
      expect(d.length).toBe(d.pitch * TICKS);
      expect(d.x0).toBe(Math.floor((d.width - d.length) / 2));
      expect(xs[0]).toBeGreaterThan(0);
      expect(xs.at(-1)).toBeLessThan(d.width);
    }
  });

  it("uses the system's pitch: 3px at the rail widths of 1280, 1440 and a phone, 4px from 410px, 2px in the 320px rail", () => {
    expect(ruleDrawing(362, "all")?.pitch).toBe(3);
    expect(ruleDrawing(383, "all")?.pitch).toBe(3);
    expect(ruleDrawing(358, "all")?.pitch).toBe(3);
    expect(ruleDrawing(410, "all")?.pitch).toBe(4);
    expect(ruleDrawing(304, "all")?.pitch).toBe(2);
  });

  it("draws nothing narrower than the system's minimum", () => {
    expect(ruleDrawing(RULE_MIN_WIDTH - 1, "all")).toBeNull();
    expect(ruleDrawing(0, "all")).toBeNull();
    expect(ruleDrawing(Number.NaN, "all")).toBeNull();
    expect(ruleDrawing(RULE_MIN_WIDTH, "all")).not.toBeNull();
  });

  it("lights one detector's 17 ticks and its name for D1 to D6", () => {
    for (const [i, band] of (["d1", "d2", "d3", "d4", "d5", "d6"] as BandId[]).entries()) {
      const d = ruleDrawing(362, band);
      expect(d?.litCount).toBe(TICKS_PER_DETECTOR);
      expect(d?.bands.filter((b) => b.lit).map((b) => b.text)).toEqual([`D${i + 1}`]);
      // The lit ticks are the detector's own run of 17.
      const lit = tickXs(d?.lit ?? "");
      const first = (d?.x0 ?? 0) + i * TICKS_PER_DETECTOR * (d?.pitch ?? 0);
      expect(Math.min(...lit)).toBeGreaterThan(first);
      expect(Math.max(...lit)).toBeLessThan(first + TICKS_PER_DETECTOR * (d?.pitch ?? 0));
    }
  });

  it("lights all 102 for All and Three-colour, and channels from 4.0 µm up for Cold objects", () => {
    expect(ruleDrawing(362, "all")?.litCount).toBe(102);
    expect(ruleDrawing(362, "rgb")?.litCount).toBe(102);
    const cold = ruleDrawing(362, "cold");
    // All of D6 and the 11 reddest channels of D5 (centres from 4.0 µm).
    expect(cold?.litCount).toBe(17 + 11);
    expect(cold?.bands.filter((b) => b.lit).map((b) => b.text)).toEqual(["D5", "D6"]);
  });

  it("is 58px high with the accent span, and 86px in three-colour with the B, G, R bars instead", () => {
    for (const band of BAND_IDS) {
      const d = ruleDrawing(362, band);
      if (band === "rgb") {
        expect(d?.height).toBe(RULE_HEIGHT_RGB);
        expect(d?.span).toBeNull();
        expect(d?.channels?.map((c) => c.letter)).toEqual(["B", "G", "R"]);
        expect(d?.channels?.map((c) => c.key)).toEqual(["b", "g", "r"]);
      } else {
        expect(d?.height).toBe(RULE_HEIGHT);
        expect(d?.span).toMatch(/^M[\d.]+ 37\.5H[\d.]+$/);
        expect(d?.channels).toBeNull();
      }
    }
  });

  it("spans two detectors with each channel bar, inside the rule", () => {
    const d = ruleDrawing(362, "rgb");
    const pitch = d?.pitch ?? 0;
    const x0 = d?.x0 ?? 0;
    for (const [k, c] of (d?.channels ?? []).entries()) {
      expect(c.x).toBeGreaterThanOrEqual(x0 + k * 34 * pitch);
      expect(c.x + c.w).toBeLessThanOrEqual(x0 + (k + 1) * 34 * pitch);
      expect(c.w).toBeGreaterThan(30 * pitch);
    }
  });

  it("writes the seven edge wavelengths and the unit only when there is room", () => {
    const d = ruleDrawing(362, "all");
    expect(d?.numbers.map((n) => n.text)).toEqual([
      "0.74",
      "1.11",
      "1.65",
      "2.42",
      "3.82",
      "4.42",
      "5.00",
    ]);
    expect(d?.numbers[0].anchor).toBe("start");
    expect(d?.numbers[6].anchor).toBe("end");
    expect(d?.unitX).toBe((d?.x0 ?? 0) + (d?.length ?? 0) + 5);
    // 206px: 2px pitch, 204px long, 1px either side: no room for "µm".
    expect(ruleDrawing(206, "all")?.unitX).toBeNull();
  });

  it("keeps the edge numbers apart at every width the comparator draws (288 to 383px)", () => {
    // Four characters of 12px Source Code Pro (0.6 em each), plus a 2px gap between neighbours.
    const half = (4 * 0.6 * 12) / 2;
    const extent = (n: { x: number; anchor: string }) =>
      n.anchor === "start"
        ? [n.x, n.x + 2 * half]
        : n.anchor === "end"
          ? [n.x - 2 * half, n.x]
          : [n.x - half, n.x + half];
    for (let width = 288; width <= 383; width++) {
      const d = ruleDrawing(width, "cold");
      if (!d) throw new Error(`no rule at ${width}`);
      const spans = d.numbers.map(extent);
      for (let i = 1; i < spans.length; i++)
        expect(spans[i][0] - spans[i - 1][1]).toBeGreaterThanOrEqual(2);
      expect(spans[0][0]).toBeGreaterThanOrEqual(0);
      expect(spans[spans.length - 1][1]).toBeLessThanOrEqual(width);
      if (d.unitX !== null) {
        expect(d.unitX).toBeGreaterThanOrEqual(spans[spans.length - 1][1] + 2);
        expect(d.unitX + 2 * 0.6 * 12).toBeLessThanOrEqual(width);
      }
    }
    // The 320px rail (304px inside its gutter): 2px pitch, every number centred, the unit kept.
    const rail = ruleDrawing(304, "cold");
    expect(rail?.pitch).toBe(2);
    expect(rail?.numbers.every((n) => n.anchor === "middle")).toBe(true);
    expect(rail?.unitX).not.toBeNull();
  });

  it("places a wavelength by detector, log-spaced within it", () => {
    expect(ruleFraction(0.74)).toBe(0);
    expect(ruleFraction(5.0)).toBeCloseTo(1, 10);
    expect(ruleFraction(1.12)).toBeCloseTo(1 / 6, 10);
    expect(ruleFraction(4.42)).toBeCloseTo(5 / 6, 10);
    expect(ruleFraction(0.5)).toBe(0);
    expect(ruleFraction(6)).toBe(1);
    for (let lam = 0.75; lam < 5; lam += 0.05) {
      expect(ruleFraction(lam + 0.05)).toBeGreaterThanOrEqual(ruleFraction(lam));
    }
  });
});
