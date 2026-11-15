import { describe, expect, it } from "vitest";
import {
  asSentence,
  brightness,
  countFixed,
  fixedDateRange,
  formatDec,
  formatRa,
  frameCounter,
  positionLine,
  rangeFixed,
  readAsSentence,
  rowCount,
  scaleLabel,
  shortDate,
  shortDateRange,
  sigmas,
  speedLabel,
  trueMinus,
} from "./format";

describe("dates", () => {
  it("writes the timeline's short form as the design does", () => {
    expect(shortDateRange("2025-05-05", "2025-05-06")).toBe("5–6 May 2025");
    expect(shortDateRange("2025-10-31", "2025-11-14")).toBe("31 Oct–14 Nov 2025");
    expect(shortDateRange("2026-04-21", "2026-05-14")).toBe("21 Apr–14 May 2026");
    expect(shortDateRange("2025-09-30", "2025-10-01")).toBe("30 Sep–1 Oct 2025");
    expect(shortDateRange("2025-12-28", "2026-01-03")).toBe("28 Dec 2025–3 Jan 2026");
    expect(shortDateRange("2025-05-05", "2025-05-05")).toBe("5 May 2025");
  });

  it("writes the frame label's fixed form in 21 characters within a year", () => {
    expect(fixedDateRange("2025-11-07", "2025-11-14")).toBe("07 Nov to 14 Nov 2025");
    expect(fixedDateRange("2025-05-05", "2025-05-06")).toBe("05 May to 06 May 2025");
    expect(fixedDateRange("2025-05-05", "2025-05-05")).toHaveLength(21);
    expect(fixedDateRange("2025-12-28", "2026-01-03")).toBe("28 Dec 2025 to 03 Jan 2026");
  });

  it("writes one date for the newest-image chip", () => {
    expect(shortDate("2026-10-05")).toBe("5 Oct 2026");
  });

  it("rejects anything that is not an ISO date", () => {
    expect(() => shortDate("5 Oct 2026")).toThrow(RangeError);
  });
});

describe("numbers", () => {
  it("uses the true minus and signs declinations", () => {
    expect(trueMinus("-7.2")).toBe("−7.2");
    expect(formatRa(133.759771)).toBe("133.75977°");
    expect(formatDec(-7.241834)).toBe("−7.24183°");
    expect(formatDec(4.7682, 4)).toBe("+4.7682°");
    expect(positionLine(133.7598, -7.2422)).toBe("RA 133.7598°  Dec −7.2422°");
    expect(readAsSentence(133.7598, -7.2422)).toBe("Read as RA 133.7598°, Dec −7.2422°.");
  });

  it("right-aligns the frame label's count in three characters", () => {
    expect(countFixed(9)).toBe("  9 exposures");
    expect(countFixed(32)).toBe(" 32 exposures");
    expect(countFixed(116)).toBe("116 exposures");
    expect(countFixed(1)).toHaveLength(countFixed(32).length);
    expect(countFixed(null)).toBe("  — exposures");
  });

  it("writes a row's count with its qualifiers", () => {
    expect(rowCount(32, false, false)).toBe("32 exposures");
    expect(rowCount(11, false, true)).toBe("11 exposures, partial");
    expect(rowCount(4, true, false)).toBe("4 exposures, thin");
    expect(rowCount(0, true, true)).toBe("0 exposures, thin, partial");
    expect(rowCount(1, true, false)).toBe("1 exposure, thin");
  });

  it("keeps the wavelength range at one length, known or not", () => {
    expect(rangeFixed(3.96175, 5.002)).toBe("3.96 to 5.00 µm");
    expect(rangeFixed(Number.NaN, Number.NaN)).toBe("—.—— to —.—— µm");
    expect(rangeFixed(Number.NaN, 1)).toHaveLength(rangeFixed(0.744, 1.116).length);
  });

  it("gives brightness with three significant figures", () => {
    expect(brightness(0.14234)).toBe("0.142");
    expect(brightness(-0.018)).toBe("−0.0180");
    expect(brightness(1.2634)).toBe("1.26");
    expect(brightness(694.2)).toBe("694");
    expect(brightness(12345.6)).toBe("12346");
    expect(brightness(Number.NaN)).toBe("no data");
  });

  it("gives a difference in units of noise, signed", () => {
    expect(sigmas(2.34)).toBe("+2.3 σ");
    expect(sigmas(-0.44)).toBe("−0.4 σ");
    expect(sigmas(0.01)).toBe("0.0 σ");
    expect(sigmas(Number.NaN)).toBe("no data");
  });

  it("writes the counter, the speed and the scale", () => {
    expect(frameCounter(1, 4)).toBe("Frame 2 of 4");
    expect(speedLabel(2)).toBe("2 per second");
    expect(scaleLabel(4)).toBe("4×");
    expect(scaleLabel(5 / 3)).toBe("1.7×");
  });

  it("turns a manifest phrase into a sentence", () => {
    expect(asSentence("time bin 1 has only 9 exposures")).toBe("Time bin 1 has only 9 exposures.");
    expect(asSentence("Already a sentence.")).toBe("Already a sentence.");
  });
});
