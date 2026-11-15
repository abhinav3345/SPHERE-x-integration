import { describe, expect, it } from "vitest";
import {
  cropCentredOn,
  pixelToPlate,
  pixelToScreen,
  pixelUnder,
  plateToPixel,
  screenToPixel,
} from "./screen";

// A 119 x 119 plane drawn 595 CSS pixels wide: every plane pixel covers 5 x 5 CSS pixels.
const box = { width: 595, height: 595 };
const n = 119;

function expectPoint(actual: { x: number; y: number }, x: number, y: number) {
  expect(actual.x).toBeCloseTo(x, 9);
  expect(actual.y).toBeCloseTo(y, 9);
}

describe("screenToPixel", () => {
  it("puts pixel centres at integer coordinates", () => {
    expectPoint(screenToPixel(box, n, n, { x: 2.5, y: 2.5 }), 0, 0);
    expectPoint(screenToPixel(box, n, n, { x: 297.5, y: 297.5 }), 59, 59);
    expectPoint(screenToPixel(box, n, n, { x: 592.5, y: 2.5 }), 118, 0);
  });

  it("maps the corners of the box to half a pixel outside the outer centres", () => {
    expectPoint(screenToPixel(box, n, n, { x: 0, y: 0 }), -0.5, -0.5);
    expectPoint(screenToPixel(box, n, n, { x: 595, y: 595 }), 118.5, 118.5);
  });

  it("handles a box that is not square", () => {
    expectPoint(screenToPixel({ width: 200, height: 100 }, 4, 2, { x: 125, y: 75 }), 2, 1);
  });
});

describe("pixelToScreen", () => {
  it("is the inverse of screenToPixel", () => {
    for (const screen of [
      { x: 0, y: 0 },
      { x: 13.25, y: 480.5 },
      { x: 595, y: 301 },
    ]) {
      const back = pixelToScreen(box, n, n, screenToPixel(box, n, n, screen));
      expectPoint(back, screen.x, screen.y);
    }
  });

  it("puts the centre pixel in the middle of the box", () => {
    expectPoint(pixelToScreen(box, n, n, { x: 59, y: 59 }), 297.5, 297.5);
  });
});

describe("plates and crops", () => {
  // The whole 119 px frame at 4× (476 CSS px), and the spotlight: 39 px around the ring at 12×.
  const whole = { x0: 0, y0: 0, size: 119, scale: 4 };

  it("draws the whole frame like pixelToScreen does", () => {
    expectPoint(pixelToPlate(whole, { x: 59, y: 59 }), 238, 238);
    expectPoint(pixelToPlate(whole, { x: 0, y: 0 }), 2, 2);
    const asBox = pixelToScreen({ width: 476, height: 476 }, 119, 119, { x: 17, y: 101 });
    expectPoint(pixelToPlate(whole, { x: 17, y: 101 }), asBox.x, asBox.y);
  });

  it("centres an odd crop on the ring's pixel", () => {
    const spot = cropCentredOn(59 + 7, 59 - 3, 39, 12);
    expect(spot).toEqual({ x0: 47, y0: 37, size: 39, scale: 12 });
    // The ring's pixel is the middle of the 468 px plate.
    expectPoint(pixelToPlate(spot, { x: 66, y: 56 }), 234, 234);
  });

  it("lets a crop reach past the edge of the frame", () => {
    expect(cropCentredOn(0, 118, 39, 12)).toEqual({ x0: -19, y0: 99, size: 39, scale: 12 });
  });

  it("inverts pixelToPlate", () => {
    const spot = { x0: -19, y0: 99, size: 39, scale: 12 };
    for (const pixel of [
      { x: 0, y: 118 },
      { x: -3.25, y: 101.5 },
    ]) {
      const back = plateToPixel(spot, pixelToPlate(spot, pixel));
      expectPoint(back, pixel.x, pixel.y);
    }
  });

  it("finds the whole pixel under a point, and none off the frame or the plate", () => {
    expect(pixelUnder(whole, 119, 119, { x: 0, y: 0 })).toEqual({ x: 0, y: 0 });
    expect(pixelUnder(whole, 119, 119, { x: 3.99, y: 4 })).toEqual({ x: 0, y: 1 });
    expect(pixelUnder(whole, 119, 119, { x: 475.9, y: 475.9 })).toEqual({ x: 118, y: 118 });
    expect(pixelUnder(whole, 119, 119, { x: 476, y: 10 })).toBeNull();
    expect(pixelUnder(whole, 119, 119, { x: -0.1, y: 10 })).toBeNull();
    // The spotlight's crop past the eastern edge: surround, no pixel.
    const spot = { x0: -19, y0: 40, size: 39, scale: 12 };
    expect(pixelUnder(spot, 119, 119, { x: 5, y: 5 })).toBeNull();
    expect(pixelUnder(spot, 119, 119, { x: 19 * 12 + 1, y: 5 })).toEqual({ x: 0, y: 40 });
  });
});
