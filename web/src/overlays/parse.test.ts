import { describe, expect, it } from "vitest";
import {
  DEC_RANGE,
  formatDegrees,
  MINUTES_RANGE,
  RA_RANGE,
  readAsMessage,
  UNREADABLE,
} from "./messages";
import { parseCoordinates } from "./parse";
import { SearchError } from "./types";

// The brief's coordinates for WISE 0855: RA 08h55m10.831s, Dec -07d14m42.53s.
const BRIEF_RA = 15 * (8 + 55 / 60 + 10.831 / 3600);
const BRIEF_DEC = -(7 + 14 / 60 + 42.53 / 3600);

function errorOf(text: string): SearchError {
  try {
    parseCoordinates(text);
  } catch (error) {
    if (error instanceof SearchError) return error;
    throw error;
  }
  throw new Error(`"${text}" was accepted`);
}

describe("decimal degrees", () => {
  it.each([
    "133.7599 -7.2418",
    "133.7599, -7.2418",
    "133.7599,-7.2418",
    "133.7599 −7.2418",
    "133.7599° −7.2418°",
    "133.7599°, -7.2418°",
    "  133.7599   -7.2418  ",
    "+133.7599 -7.2418",
    "133.7599-7.2418",
    "RA 133.7599 Dec -7.2418",
  ])("reads %s", (text) => {
    expect(parseCoordinates(text)).toEqual({
      kind: "degrees",
      position: { ra: 133.7599, dec: -7.2418 },
    });
  });

  it("reads a northern position without a sign", () => {
    expect(parseCoordinates("269.45208 4.69336")?.position).toEqual({
      ra: 269.45208,
      dec: 4.69336,
    });
  });

  it("accepts the edges of the ranges", () => {
    expect(parseCoordinates("0 -90")?.position).toEqual({ ra: 0, dec: -90 });
    expect(parseCoordinates("359.99999 90")?.position).toEqual({ ra: 359.99999, dec: 90 });
    expect(Object.is(parseCoordinates("-0 0")?.position.ra, 0)).toBe(true);
  });
});

describe("hours and degrees", () => {
  it.each([
    "08h55m10.831s -07d14m42.53s",
    "08h55m10.831s, -07d14m42.53s",
    "08:55:10.831 -07:14:42.53",
    "08:55:10.831, -07:14:42.53",
    "08 55 10.831 -07 14 42.53",
    "08 55 10.831 −07 14 42.53",
    "08h 55m 10.831s −07° 14′ 42.53″",
    "08h55m10.831s -07°14'42.53\"",
    "RA 08h55m10.831s, Dec -07d14m42.53s",
    "ra: 08:55:10.831 dec: -07:14:42.53",
    "8h55m10.831s-7d14m42.53s",
    "08h55m10.831s -07d14m42.53s J2000",
    "08 55 10.831 -07 14 42.53 (ICRS)",
  ])("reads %s as the brief's WISE 0855 position", (text) => {
    const parsed = parseCoordinates(text);
    expect(parsed?.kind).toBe("sexagesimal");
    expect(parsed?.position.ra).toBeCloseTo(BRIEF_RA, 9);
    expect(parsed?.position.dec).toBeCloseTo(BRIEF_DEC, 9);
  });

  it("reads a declination with no sign as north", () => {
    // Barnard's Star at J2000 as CDS Sesame gives it, 269.45208 +4.69336, written in hours.
    const parsed = parseCoordinates("17 57 48.50 04 41 36.1");
    expect(parsed?.position.ra).toBeCloseTo(15 * (17 + 57 / 60 + 48.5 / 3600), 9);
    expect(parsed?.position.dec).toBeCloseTo(4 + 41 / 60 + 36.1 / 3600, 9);
    expect(parseCoordinates("17h57m48.50s 04d41m36.1s")?.position).toEqual(parsed?.position);
  });

  it("keeps the sign of a declination between 0 and -1 degree", () => {
    expect(parseCoordinates("12 00 00 -00 30 00")?.position.dec).toBeCloseTo(-0.5, 12);
    expect(parseCoordinates("12h00m00s -00d30m00s")?.position.dec).toBeCloseTo(-0.5, 12);
  });

  it("reads hours and minutes without seconds, and decimal hours", () => {
    expect(parseCoordinates("08:55.5 -07:14.5")?.position.ra).toBeCloseTo(15 * (8 + 55.5 / 60), 9);
    expect(parseCoordinates("8.5h -7.25")?.position).toEqual({ ra: 127.5, dec: -7.25 });
  });
});

describe("range errors use the design's sentences", () => {
  it.each([
    ["133.7599 -97.2418", DEC_RANGE],
    ["133.7599 90.0001", DEC_RANGE],
    ["08h55m10.831s -97d14m42.53s", DEC_RANGE],
    ["-7.2418 133.7599", DEC_RANGE],
    ["360 0", RA_RANGE],
    ["400 10", RA_RANGE],
    ["-10 20", RA_RANGE],
    ["24h00m00s +10d00m00s", RA_RANGE],
    ["08h75m00s -07d00m00s", MINUTES_RANGE],
    ["08:55:10 -07:14:60", MINUTES_RANGE],
  ])("%s", (text, message) => {
    const error = errorOf(text);
    expect(error.code).toBe("range");
    expect(error.message).toBe(message);
  });
});

describe("numbers that are not a position", () => {
  it.each([
    "133.7599",
    "1 2 3",
    "1.2.3 4",
    "08h55m10.831s",
    "133.7599 / -7.2418",
    "1, 2, 3",
    "133.7599 -7.2418 5",
    "08h55m10.831s -07h14m42.53s",
  ])("%s", (text) => {
    const error = errorOf(text);
    expect(error.code).toBe("unreadable");
    expect(error.message).toBe(UNREADABLE);
  });
});

describe("names are left to the name lookup", () => {
  it.each([
    "M31",
    "Barnard's Star",
    "HD 209100",
    "61 Cyg",
    "2MASS J0415-0935",
    "WISE 0855",
    "Rasalhague",
    "3I/ATLAS",
    "Epsilon Indi B",
  ])("%s", (text) => {
    expect(parseCoordinates(text)).toBeNull();
  });
});

describe("the message line", () => {
  it("writes five decimals and the true minus, as the design does", () => {
    expect(readAsMessage(BRIEF_RA, BRIEF_DEC)).toBe("Read as RA 133.79513°, Dec −7.24515°.");
    expect(readAsMessage(269.4520769586187, 4.69336496657667)).toBe(
      "Read as RA 269.45208°, Dec 4.69336°.",
    );
  });

  it("never writes a minus zero or 360", () => {
    expect(formatDegrees(-0.000001, false)).toBe("0.00000");
    expect(formatDegrees(359.999999, true)).toBe("0.00000");
    expect(formatDegrees(-90, false)).toBe("−90.00000");
  });
});
