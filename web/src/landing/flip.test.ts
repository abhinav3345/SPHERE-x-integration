import { describe, expect, it } from "vitest";
import {
  dwellMs,
  type Epoch,
  FLIP_PERIOD_MS,
  HERO_PERIOD_MS,
  type HeroState,
  type HoldEvent,
  type HoldState,
  heroLook,
  heroReducer,
  heroStart,
  holdReducer,
  holdShown,
  holdStart,
  isHeld,
  MAX_CHANGES_PER_SECOND,
  MIN_DWELL_MS,
  nextCut,
  other,
} from "./flip";

describe("flip timing", () => {
  it("runs the hero at the design's steady speed: 2.4 s for the pair", () => {
    expect(FLIP_PERIOD_MS).toEqual({ slow: 3600, steady: 2400, quick: 1600 });
    expect(HERO_PERIOD_MS).toBe(2400);
    expect(dwellMs(HERO_PERIOD_MS)).toBe(1200);
  });

  it("never keeps a picture up for less than 1/6 s, whatever period it is given", () => {
    expect(MAX_CHANGES_PER_SECOND).toBe(6);
    expect(MIN_DWELL_MS).toBeCloseTo(1000 / 6, 9);
    for (const period of [0, -1, 10, 333, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(dwellMs(period)).toBeGreaterThanOrEqual(MIN_DWELL_MS);
    }
    expect(dwellMs(FLIP_PERIOD_MS.quick)).toBe(800);
  });

  it("asks for the other picture after one dwell while flipping, and for nothing while still", () => {
    expect(nextCut(true, "a", HERO_PERIOD_MS)).toEqual({ frame: "b", afterMs: 1200 });
    expect(nextCut(true, "b", HERO_PERIOD_MS)).toEqual({ frame: "a", afterMs: 1200 });
    expect(nextCut(false, "a", HERO_PERIOD_MS)).toBeNull();
  });

  it("flips a, b, a, b at each cut when the timer is punctual", () => {
    let state = heroStart(true);
    let now = 0;
    const seen: [number, Epoch][] = [[0, state.frame]];
    for (let cut = nextCut(state.playing, state.frame, HERO_PERIOD_MS); cut && now < 6000; ) {
      now += cut.afterMs;
      state = heroReducer(state, { type: "show", frame: cut.frame });
      seen.push([now, state.frame]);
      cut = nextCut(state.playing, state.frame, HERO_PERIOD_MS);
    }
    expect(seen).toEqual([
      [0, "a"],
      [1200, "b"],
      [2400, "a"],
      [3600, "b"],
      [4800, "a"],
      [6000, "b"],
    ]);
  });

  it("keeps every change at least a dwell after the one before, however late the timer runs", () => {
    let seed = 7;
    const random = () => {
      seed = (seed * 16807) % 2147483647;
      return seed / 2147483647;
    };
    let state = heroStart(true);
    let now = 0;
    const changes: number[] = [];
    for (let i = 0; i < 2000; i += 1) {
      const cut = nextCut(state.playing, state.frame, HERO_PERIOD_MS);
      if (!cut) break;
      // A throttled or busy page fires the timer late, by up to three seconds.
      now += cut.afterMs + (random() < 0.3 ? random() * 3000 : random() * 5);
      const next = heroReducer(state, { type: "show", frame: cut.frame });
      if (next.frame !== state.frame) changes.push(now);
      state = next;
    }
    expect(changes).toHaveLength(2000);
    for (let i = 1; i < changes.length; i += 1) {
      expect(changes[i] - changes[i - 1]).toBeGreaterThanOrEqual(1200);
    }
  });
});

describe("hero", () => {
  it("opens flipping, unless reduced motion is asked for", () => {
    expect(heroStart(true)).toEqual({ playing: true, frame: "a", still: "both" });
    expect(heroStart(false)).toEqual({ playing: false, frame: "a", still: "both" });
  });

  it("pause stops on the picture that is showing", () => {
    let s = heroStart(true);
    s = heroReducer(s, { type: "show", frame: "b" });
    s = heroReducer(s, { type: "pause" });
    expect(s).toEqual({ playing: false, frame: "b", still: "b" });
    // A tick that arrives after the pause changes nothing.
    expect(heroReducer(s, { type: "show", frame: "a" })).toBe(s);
    expect(nextCut(s.playing, s.frame, HERO_PERIOD_MS)).toBeNull();
  });

  it("pausing a still hero changes nothing, so its light stays on both colours", () => {
    const still = heroStart(false);
    expect(heroReducer(still, { type: "pause" })).toBe(still);
  });

  it("play resumes from the picture that is showing", () => {
    const paused: HeroState = { playing: false, frame: "b", still: "b" };
    expect(heroReducer(paused, { type: "play" })).toEqual({
      playing: true,
      frame: "b",
      still: "b",
    });
  });

  it("an epoch button shows that picture and stops the flipping", () => {
    const playing = heroReducer(heroStart(true), { type: "show", frame: "b" });
    expect(heroReducer(playing, { type: "pick", frame: "a" })).toEqual({
      playing: false,
      frame: "a",
      still: "a",
    });
    expect(heroReducer(heroStart(false), { type: "pick", frame: "b" })).toEqual({
      playing: false,
      frame: "b",
      still: "b",
    });
  });

  it("presses no epoch button while flipping, and lights the frame on screen", () => {
    const playing: HeroState = { playing: true, frame: "b", still: "both" };
    expect(heroLook(playing, false)).toEqual({ frame: "b", pixel: "b", light: "b", pressed: null });
  });

  it("holds the light still under reduced motion while the pictures flip", () => {
    const playing: HeroState = { playing: true, frame: "b", still: "both" };
    expect(heroLook(playing, true)).toEqual({
      frame: "b",
      pixel: "b",
      light: "both",
      pressed: null,
    });
  });

  it("when still, presses the button of the picture on screen", () => {
    expect(heroLook(heroStart(false), true)).toEqual({
      frame: "a",
      pixel: "both",
      light: "both",
      pressed: "a",
    });
    const picked: HeroState = { playing: false, frame: "b", still: "b" };
    expect(heroLook(picked, false)).toEqual({ frame: "b", pixel: "b", light: "b", pressed: "b" });
  });
});

describe("hold to flip", () => {
  const run = (events: HoldEvent[], from: HoldState = holdStart) =>
    events.reduce((s, e) => holdReducer(s, e), from);

  it("rests on the earlier picture", () => {
    expect(holdShown(holdStart)).toBe("a");
    expect(other("a")).toBe("b");
    expect(other("b")).toBe("a");
  });

  it("flips while a pointer is down and returns on release, leave or cancel", () => {
    const down = run([{ type: "pointerdown", button: 0 }]);
    expect(holdShown(down)).toBe("b");
    expect(holdShown(run([{ type: "pointerup" }], down))).toBe("a");
    expect(holdShown(run([{ type: "pointerleave" }], down))).toBe("a");
    expect(holdShown(run([{ type: "pointercancel" }], down))).toBe("a");
    expect(holdShown(run([{ type: "blur" }], down))).toBe("a");
  });

  it("ignores buttons other than the main one", () => {
    expect(isHeld(run([{ type: "pointerdown", button: 2 }]))).toBe(false);
    expect(isHeld(run([{ type: "pointerdown", button: 1 }]))).toBe(false);
  });

  it("flips while Space or Enter is down and returns on its release", () => {
    for (const key of [" ", "Enter"]) {
      const down = run([{ type: "keydown", key, repeat: false }]);
      expect(holdShown(down)).toBe("b");
      expect(holdShown(run([{ type: "keyup", key }], down))).toBe("a");
    }
  });

  it("ignores key repeat and other keys", () => {
    expect(isHeld(run([{ type: "keydown", key: " ", repeat: true }]))).toBe(false);
    expect(isHeld(run([{ type: "keydown", key: "a", repeat: false }]))).toBe(false);
    const down = run([{ type: "keydown", key: " ", repeat: false }]);
    expect(run([{ type: "keydown", key: " ", repeat: true }], down)).toBe(down);
    expect(run([{ type: "keyup", key: "Shift" }], down)).toBe(down);
  });

  it("returns when the key or the window loses focus", () => {
    const down = run([
      { type: "keydown", key: "Enter", repeat: false },
      { type: "pointerdown", button: 0 },
    ]);
    expect(holdShown(run([{ type: "blur" }], down))).toBe("a");
  });

  it("keeps a keyboard hold when only the pointer leaves", () => {
    const down = run([{ type: "keydown", key: " ", repeat: false }]);
    expect(holdShown(run([{ type: "pointerleave" }], down))).toBe("b");
  });

  it("the epoch buttons choose the resting picture and end any hold", () => {
    const later = run([{ type: "choose", frame: "b" }]);
    expect(holdShown(later)).toBe("b");
    const held = run([{ type: "pointerdown", button: 0 }], later);
    expect(holdShown(held)).toBe("a");
    expect(holdShown(run([{ type: "pointerup" }], held))).toBe("b");
    const chosen = run([{ type: "choose", frame: "a" }], held);
    expect(chosen).toEqual({ base: "a", pointer: false, key: false });
  });

  it("returns the same state when nothing changes, so nothing re-renders", () => {
    expect(run([{ type: "pointerup" }])).toBe(holdStart);
    expect(run([{ type: "blur" }])).toBe(holdStart);
    expect(run([{ type: "keyup", key: " " }])).toBe(holdStart);
  });
});
