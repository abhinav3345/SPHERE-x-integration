import { describe, expect, it } from "vitest";
import { createGate, moveTarget, type RadioLike, tabStop } from "./radio";

const opts = (spec: string): RadioLike[] =>
  // "x" checked, "-" disabled, "+" checked and disabled, "." plain
  [...spec].map((c) => ({ checked: c === "x" || c === "+", disabled: c === "-" || c === "+" }));

describe("radio group keys", () => {
  it("moves on and back, wrapping at the ends", () => {
    expect(moveTarget(opts("x..."), 0, "ArrowRight")).toBe(1);
    expect(moveTarget(opts("x..."), 0, "ArrowDown")).toBe(1);
    expect(moveTarget(opts("...x"), 3, "ArrowRight")).toBe(0);
    expect(moveTarget(opts("x..."), 0, "ArrowLeft")).toBe(3);
    expect(moveTarget(opts("x..."), 0, "ArrowUp")).toBe(3);
  });

  it("skips greyed options in both directions", () => {
    expect(moveTarget(opts("x-.."), 0, "ArrowRight")).toBe(2);
    expect(moveTarget(opts(".-x-"), 2, "ArrowRight")).toBe(0);
    expect(moveTarget(opts("x.--"), 0, "ArrowLeft")).toBe(1);
  });

  it("jumps to the first and last option that can be chosen", () => {
    expect(moveTarget(opts("-.x.-"), 2, "Home")).toBe(1);
    expect(moveTarget(opts("-.x.-"), 2, "End")).toBe(3);
  });

  it("stays when it is the only option that can be chosen, and does nothing when none can", () => {
    expect(moveTarget(opts("-x-"), 1, "ArrowRight")).toBe(1);
    expect(moveTarget(opts("+--"), 0, "ArrowRight")).toBeNull();
    expect(moveTarget(opts("+--"), 0, "Home")).toBeNull();
  });

  it("ignores every other key", () => {
    for (const key of [" ", "Enter", "Tab", "a", "Escape", "PageDown"]) {
      expect(moveTarget(opts("x..."), 0, key)).toBeNull();
    }
    expect(moveTarget([], 0, "ArrowRight")).toBeNull();
  });

  it("puts the one Tab stop on the chosen option, else the first that can be chosen", () => {
    expect(tabStop(opts("..x."))).toBe(2);
    expect(tabStop(opts("+---"))).toBe(0);
    expect(tabStop(opts("--.."))).toBe(2);
    expect(tabStop(opts("----"))).toBe(0);
  });
});

describe("pace gate", () => {
  it("lets at most six changes a second through", () => {
    const pass = createGate(6);
    const times = Array.from({ length: 60 }, (_, i) => i * 20); // a change asked every 20 ms for 1.2 s
    const passed = times.filter((t) => pass(t));
    for (let i = 1; i < passed.length; i++) {
      expect(passed[i] - passed[i - 1]).toBeGreaterThanOrEqual(1000 / 6);
    }
    expect(passed.filter((t) => t < 1000).length).toBeLessThanOrEqual(6);
    expect(passed[0]).toBe(0);
  });

  it("never holds back changes made at a reading pace", () => {
    const pass = createGate(6);
    expect([0, 400, 800, 1200].every((t) => pass(t))).toBe(true);
  });
});
