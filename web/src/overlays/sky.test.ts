import { describe, expect, it } from "vitest";
import { KNOWN_MOVERS } from "./known-movers";
import {
  type Astrometry,
  calendarYear,
  closestApproach,
  compassPoint,
  positionAngleDeg,
  propagate,
  separationArcsec,
} from "./sky";

// Gaia DR3 4472832130942575872, Barnard's Star, epoch 2016.0, as the team backend's /stars
// returned it on 14 Nov 2026 (the same values as api/tombaugh/tools/make_fixture.py).
const BARNARD: Astrometry = {
  ra: 269.44850252543836,
  dec: 4.739420051112412,
  epoch: 2016.0,
  pmra: -801.5509783684709,
  pmdec: 10362.394206546573,
};
// Gaia DR3 6412596012146801152, Epsilon Indi Ba/Bb, from the same backend on the same night.
const EPS_INDI_B: Astrometry = {
  ra: 331.07645259656397,
  dec: -56.79381206688221,
  epoch: 2016.0,
  pmra: 3981.97666296105,
  pmdec: -2466.8318147663504,
};
const WISE_0855 = KNOWN_MOVERS[0]?.astrometry as Astrometry;
const BRIEF = { ra: 15 * (8 + 55 / 60 + 10.831 / 3600), dec: -(7 + 14 / 60 + 42.53 / 3600) };

// Reference values computed independently with astropy 7 (SkyCoord.apply_space_motion, no
// distance), scratch script refvalues.py of 14 Nov 2026.
const ASTROPY = {
  barnard2026: { ra: 269.4462683, dec: 4.7682045 },
  wise2026: { ra: 133.7597653, dec: -7.2421822 },
  epsIndi2026: { ra: 331.0966534, dec: -56.8006627 },
};

describe("propagate", () => {
  it("puts Barnard's Star at the recorded field's centre in 2026.0", () => {
    const now = propagate(BARNARD, 2026.0);
    expect(separationArcsec(now, { ra: 269.44627, dec: 4.7682 })).toBeLessThan(0.2);
    expect(separationArcsec(now, ASTROPY.barnard2026)).toBeLessThan(0.01);
  });

  it("puts WISE 0855 where it is in 2026.0", () => {
    const now = propagate(WISE_0855, 2026.0);
    expect(separationArcsec(now, { ra: 133.75977, dec: -7.24218 })).toBeLessThan(0.5);
    expect(separationArcsec(now, ASTROPY.wise2026)).toBeLessThan(0.01);
  });

  it("agrees with astropy for Epsilon Indi B", () => {
    expect(separationArcsec(propagate(EPS_INDI_B, 2026.0), ASTROPY.epsIndi2026)).toBeLessThan(0.01);
  });

  it("returns the catalogue position at the catalogue epoch", () => {
    const at = propagate(BARNARD, 2016.0);
    expect(separationArcsec(at, BARNARD)).toBeLessThan(1e-6);
  });

  it("wraps right ascension through 0", () => {
    const synthetic: Astrometry = { ra: 0.0001, dec: 10, epoch: 2016, pmra: -1000, pmdec: 0 };
    const later = propagate(synthetic, 2026.0);
    expect(later.ra).toBeGreaterThan(359.99);
    expect(later.ra).toBeLessThan(360);
  });
});

describe("separation and direction", () => {
  it("finds WISE 0855 about 126.7″ west of the brief's coordinates", () => {
    const now = propagate(WISE_0855, 2026.0);
    expect(separationArcsec(BRIEF, now)).toBeCloseTo(126.744, 1);
    expect(positionAngleDeg(BRIEF, now)).toBeCloseTo(274.83, 1);
  });

  it("finds Barnard's Star north of its J2000 position", () => {
    const sesame = { ra: 269.4520769586187, dec: 4.69336496657667 };
    const now = propagate(BARNARD, 2026.0);
    expect(separationArcsec(sesame, now)).toBeCloseTo(270.25, 1);
    expect(compassPoint(positionAngleDeg(sesame, now))).toBe("north");
  });

  it("names the eight compass points", () => {
    expect(compassPoint(0)).toBe("north");
    expect(compassPoint(22.4)).toBe("north");
    expect(compassPoint(22.6)).toBe("north-east");
    expect(compassPoint(90)).toBe("east");
    expect(compassPoint(121.8)).toBe("south-east");
    expect(compassPoint(180)).toBe("south");
    expect(compassPoint(225)).toBe("south-west");
    expect(compassPoint(274.8)).toBe("west");
    expect(compassPoint(315)).toBe("north-west");
    expect(compassPoint(337.6)).toBe("north");
    expect(compassPoint(-45)).toBe("north-west");
    expect(compassPoint(360)).toBe("north");
  });
});

describe("closestApproach", () => {
  it("finds WISE 0855 at the brief's coordinates in 2010", () => {
    const a = closestApproach(WISE_0855, BRIEF, 1990, 2026);
    expect(a.epoch).toBeCloseTo(2010.45, 1);
    expect(a.distanceArcsec).toBeLessThan(0.3);
    expect(calendarYear(a.epoch)).toBe(2010);
  });

  it("finds Barnard's Star at its J2000 position in 2000", () => {
    const a = closestApproach(
      BARNARD,
      { ra: 269.4520769586187, dec: 4.69336496657667 },
      1990,
      2026,
    );
    expect(a.epoch).toBeCloseTo(2000.0, 2);
    expect(a.distanceArcsec).toBeLessThan(0.05);
    expect(calendarYear(a.epoch)).toBe(2000);
  });

  it("stays inside the span", () => {
    const a = closestApproach(BARNARD, BARNARD, 1990, 2010);
    expect(a.epoch).toBe(2010);
    expect(a.distanceArcsec).toBeCloseTo((6 * Math.hypot(BARNARD.pmra, BARNARD.pmdec)) / 1000, 2);
  });
});

describe("calendarYear", () => {
  it("gives the calendar year that holds a Julian epoch", () => {
    expect(calendarYear(1990.0)).toBe(1990);
    expect(calendarYear(2000.0)).toBe(2000);
    expect(calendarYear(2010.45)).toBe(2010);
    expect(calendarYear(2025.999)).toBe(2025);
  });
});
