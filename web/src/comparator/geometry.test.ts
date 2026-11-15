import { describe, expect, it } from "vitest";
import {
  fitImage,
  fitSpotlight,
  frameSquare,
  geometryFor,
  layoutFor,
  pairSquare,
  scaleBarFor,
} from "./geometry";

describe("layoutFor", () => {
  it("follows the breakpoints of Handoff-behaviour", () => {
    expect(layoutFor(390, 844)).toBe("phone");
    expect(layoutFor(719, 900)).toBe("phone");
    expect(layoutFor(720, 900)).toBe("rail");
    expect(layoutFor(1279, 900)).toBe("rail");
    expect(layoutFor(1280, 720)).toBe("three");
    expect(layoutFor(1280, 600)).toBe("three"); // under 720 tall: three columns, the page scrolls
    expect(layoutFor(1440, 899)).toBe("three");
    expect(layoutFor(1440, 900)).toBe("wide");
    expect(layoutFor(1920, 1080)).toBe("wide");
  });
});

describe("image scale", () => {
  it("draws the 119 px frame at 3×, 4× and 5×", () => {
    expect(fitImage(frameSquare("phone", 390), 119, 1)).toMatchObject({ scale: 3, plate: 357 });
    expect(fitImage(frameSquare("three", 0), 119, 1)).toMatchObject({ scale: 4, plate: 476 });
    expect(fitImage(frameSquare("wide", 0), 119, 1)).toMatchObject({ scale: 5, plate: 595 });
  });

  it("gives a 197 px field the largest whole scale that fits the same square", () => {
    expect(fitImage(476, 197, 1)).toMatchObject({ scale: 2, plate: 394 });
    expect(fitImage(595, 197, 1)).toMatchObject({ scale: 3, plate: 591 });
    expect(fitImage(390, 197, 1)).toMatchObject({ scale: 1, plate: 197 });
    // A dense phone counts whole DEVICE pixels: 3 device px per image pixel at 2×.
    expect(fitImage(390, 197, 2)).toMatchObject({ devicePerPixel: 3, scale: 1.5, plate: 295.5 });
  });

  it("keeps whole device pixels on dense screens", () => {
    const fit = fitImage(476, 119, 2);
    expect(fit.devicePerPixel).toBe(8);
    expect(fit.scale).toBe(4);
  });

  it("halves the column for a pair at 1280 and 1440, stacks them below", () => {
    expect(pairSquare("three", 0)).toBe(238);
    expect(pairSquare("wide", 0)).toBe(297.5);
    expect(pairSquare("phone", 390)).toBe(390);
    expect(fitImage(pairSquare("three", 0), 119, 1).scale).toBe(2);
    expect(fitImage(pairSquare("wide", 0), 119, 1).scale).toBe(2);
  });

  it("draws the spotlight's 39 × 39 pixels at three times the scale", () => {
    expect(fitSpotlight(fitImage(476, 119, 1), 1)).toMatchObject({
      imagePx: 39,
      scale: 12,
      plate: 468,
    });
    expect(fitSpotlight(fitImage(390, 119, 1), 1)).toMatchObject({
      imagePx: 39,
      scale: 9,
      plate: 351,
    });
    expect(fitSpotlight(fitImage(595, 119, 1), 1)).toMatchObject({
      imagePx: 39,
      scale: 15,
      plate: 585,
    });
    expect(fitSpotlight(fitImage(238, 119, 1), 1)).toMatchObject({
      imagePx: 39,
      scale: 6,
      plate: 234,
    });
  });

  it("crops the spotlight smaller when 39 pixels would not fit, keeping it odd", () => {
    const spot = fitSpotlight(fitImage(476, 59, 1), 1); // 3′: 8× then 24×
    expect(spot.imagePx % 2).toBe(1);
    expect(spot.plate).toBeLessThanOrEqual(476);
  });
});

describe("scale bar", () => {
  it("has one drawn length per layout and a label that follows the scale", () => {
    expect(scaleBarFor("phone").lengthPx).toBe(58.5);
    expect(scaleBarFor("three").lengthPx).toBe(78);
    expect(scaleBarFor("wide").lengthPx).toBe(97.5);
    const bar = scaleBarFor("three");
    expect(bar.arcsecAt(4)).toBe(60);
    expect(bar.arcsecAt(12)).toBe(20);
    expect(bar.arcsecAt(2)).toBe(120);
    expect(bar.arcsecAt(6)).toBe(40);
    expect(scaleBarFor("wide").arcsecAt(2)).toBe(150);
  });

  it("is part of the geometry of a layout", () => {
    const g = geometryFor("three", 0, 1, 119);
    expect(g.one.plate).toBe(476);
    expect(g.two.plate).toBe(238);
    expect(g.spot.plate).toBe(468);
    expect(g.spotTwo.plate).toBe(234);
    expect(g.scaleBar.arcsecAt(g.one.scale)).toBe(60);
  });
});
