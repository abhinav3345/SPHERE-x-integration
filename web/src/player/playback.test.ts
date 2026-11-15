import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ChangeGate,
  clampFps,
  DEFAULT_FPS,
  FPS_CHOICES,
  FrameClock,
  MAX_FPS,
  MIN_CHANGE_INTERVAL_MS,
  stepIndex,
  waitBeforeChange,
} from "./playback";

describe("clampFps", () => {
  it("never exceeds 6 frame changes per second", () => {
    expect(MAX_FPS).toBe(6);
    expect(clampFps(6)).toBe(6);
    expect(clampFps(7)).toBe(6);
    expect(clampFps(1000)).toBe(6);
    expect(clampFps(Number.POSITIVE_INFINITY)).toBe(DEFAULT_FPS);
  });

  it("defaults to 2 and repairs unusable values", () => {
    expect(DEFAULT_FPS).toBe(2);
    expect(clampFps(Number.NaN)).toBe(2);
    expect(clampFps(0)).toBe(2);
    expect(clampFps(-3)).toBe(2);
    expect(clampFps(0.01)).toBe(0.25);
    expect(clampFps(3)).toBe(3);
  });

  it("offers only allowed rates, the default among them", () => {
    expect(FPS_CHOICES.every((fps) => fps > 0 && fps <= MAX_FPS)).toBe(true);
    expect(FPS_CHOICES).toContain(DEFAULT_FPS);
  });
});

describe("stepIndex", () => {
  it("loops in both directions", () => {
    expect(stepIndex(0, 4, 1)).toBe(1);
    expect(stepIndex(3, 4, 1)).toBe(0);
    expect(stepIndex(0, 4, -1)).toBe(3);
    expect(stepIndex(1, 4, -6)).toBe(3);
    expect(stepIndex(0, 1, 1)).toBe(0);
    expect(stepIndex(2, 0, 1)).toBe(0);
  });
});

describe("waitBeforeChange", () => {
  it("allows a change one sixth of a second after the last one", () => {
    expect(MIN_CHANGE_INTERVAL_MS).toBeCloseTo(166.667, 3);
    expect(waitBeforeChange(1000, Number.NEGATIVE_INFINITY)).toBe(0);
    expect(waitBeforeChange(1000, 1000)).toBeCloseTo(166.667, 3);
    expect(waitBeforeChange(1100, 1000)).toBeCloseTo(66.667, 3);
    expect(waitBeforeChange(1200, 1000)).toBe(0);
  });
});

describe("FrameClock", () => {
  let clock: FrameClock;
  /** Times (ms) at which the shown frame changed. */
  let changes: number[];

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    clock = new FrameClock(() => Date.now());
    changes = [];
    let shown = clock.getState().index;
    clock.subscribe(() => {
      const { index } = clock.getState();
      if (index !== shown) changes.push(Date.now());
      shown = index;
    });
  });

  afterEach(() => {
    clock.dispose();
    vi.useRealTimers();
  });

  /** The largest number of frame changes inside any one-second window. */
  const busiestSecond = () =>
    Math.max(
      0,
      ...changes.map((start) => changes.filter((t) => t >= start && t < start + 1000).length),
    );

  it("starts paused and never starts by itself", () => {
    expect(clock.getState()).toEqual({ index: 0, count: 0, playing: false, fps: 2 });
    clock.reset(4);
    clock.setFps(6);
    clock.show(2);
    vi.advanceTimersByTime(60_000);
    expect(clock.getState().playing).toBe(false);
    expect(clock.getState().index).toBe(2);
    expect(changes).toHaveLength(1);
  });

  it("arrives paused again whenever the sequence is replaced", () => {
    clock.reset(4);
    clock.play();
    vi.advanceTimersByTime(1200);
    expect(clock.getState().playing).toBe(true);
    clock.reset(3);
    expect(clock.getState().playing).toBe(false);
    const before = changes.length;
    vi.advanceTimersByTime(10_000);
    expect(changes).toHaveLength(before);
  });

  it("plays at 2 changes per second by default and loops", () => {
    clock.reset(3);
    clock.play();
    vi.advanceTimersByTime(2000);
    expect(changes).toEqual([500, 1000, 1500, 2000]);
    expect(clock.getState().index).toBe(1); // 0 -> 1 -> 2 -> 0 -> 1
  });

  it("pauses and resumes on toggle", () => {
    clock.reset(3);
    clock.toggle();
    vi.advanceTimersByTime(1000);
    clock.toggle();
    expect(clock.getState().playing).toBe(false);
    vi.advanceTimersByTime(5000);
    expect(changes).toHaveLength(2);
  });

  it("does not play a sequence of fewer than two frames", () => {
    clock.reset(1);
    clock.play();
    expect(clock.getState().playing).toBe(false);
    clock.reset(0);
    clock.toggle();
    expect(clock.getState().playing).toBe(false);
  });

  it("never exceeds 6 changes per second at the fastest setting", () => {
    clock.reset(5);
    clock.setFps(1000); // clamped
    expect(clock.getState().fps).toBe(6);
    clock.play();
    vi.advanceTimersByTime(10_000);
    expect(changes.length).toBeGreaterThanOrEqual(58);
    expect(busiestSecond()).toBeLessThanOrEqual(6);
  });

  it("never exceeds 6 changes per second when an arrow key is held down", () => {
    clock.reset(5);
    // Key repeat every 30 ms for 5 s, with playback running at full speed as well.
    clock.setFps(6);
    clock.play();
    for (let t = 0; t < 5000; t += 30) {
      clock.step(1);
      vi.advanceTimersByTime(30);
    }
    expect(changes.length).toBeGreaterThan(20);
    expect(busiestSecond()).toBeLessThanOrEqual(6);
    const gaps = changes.slice(1).map((t, i) => t - changes[i]);
    expect(Math.min(...gaps)).toBeGreaterThanOrEqual(166);
  });

  it("steps and shows frames on request, looping at the ends", () => {
    clock.reset(3);
    clock.step(-1);
    expect(clock.getState().index).toBe(2);
    vi.advanceTimersByTime(200);
    clock.step(1);
    expect(clock.getState().index).toBe(0);
    vi.advanceTimersByTime(200);
    clock.show(1);
    expect(clock.getState().index).toBe(1);
    vi.advanceTimersByTime(200);
    clock.show(7); // out of range: ignored
    clock.show(-1);
    clock.show(1.5);
    expect(clock.getState().index).toBe(1);
  });

  it("defers a request made too soon instead of dropping it", () => {
    clock.reset(4);
    clock.show(1);
    vi.advanceTimersByTime(50);
    clock.show(3);
    expect(clock.getState().index).toBe(1);
    vi.advanceTimersByTime(120);
    expect(clock.getState().index).toBe(3);
    expect(changes).toEqual([0, 167]);
  });

  it("keeps the index when the new sequence is long enough, else returns to the start", () => {
    clock.reset(4);
    clock.show(3);
    clock.reset(6);
    expect(clock.getState().index).toBe(3);
    clock.reset(2);
    expect(clock.getState().index).toBe(0);
  });

  it("notifies subscribers only on real changes and stops after unsubscribe", () => {
    const listener = vi.fn();
    const unsubscribe = clock.subscribe(listener);
    clock.reset(3);
    clock.reset(3);
    clock.setFps(2);
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    clock.show(2);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("ChangeGate", () => {
  let gate: ChangeGate;
  /** Times (ms) at which a change was applied. */
  let applied: number[];
  const change =
    (changes = true) =>
    () => {
      applied.push(Date.now());
      return changes;
    };

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    gate = new ChangeGate(() => Date.now());
    applied = [];
  });

  afterEach(() => {
    gate.cancel();
    vi.useRealTimers();
  });

  it("applies the first change at once and holds the next for a sixth of a second", () => {
    gate.request(change());
    gate.request(change());
    expect(applied).toEqual([0]);
    expect(gate.waiting).toBe(true);
    vi.advanceTimersByTime(200);
    expect(applied).toEqual([0, 167]);
  });

  it("lets a newer request replace one that is waiting", () => {
    const order: string[] = [];
    gate.request(() => {
      order.push("down");
      return true;
    });
    gate.request(() => {
      order.push("up");
      return true;
    });
    gate.request(() => {
      order.push("down again");
      return true;
    });
    vi.advanceTimersByTime(500);
    expect(order).toEqual(["down", "down again"]);
  });

  it("stays open after a request that changed nothing", () => {
    gate.request(change(false));
    gate.request(change());
    expect(applied).toEqual([0, 0]);
  });

  it("never lets more than 6 changes through in a second, however fast they are asked for", () => {
    for (let t = 0; t < 3000; t += 10) {
      gate.request(change());
      vi.advanceTimersByTime(10);
    }
    const gaps = applied.slice(1).map((t, i) => t - applied[i]);
    expect(Math.min(...gaps)).toBeGreaterThanOrEqual(166);
    expect(applied.length).toBeLessThanOrEqual(19);
  });

  it("drops a waiting request on cancel", () => {
    gate.request(change());
    gate.request(change());
    gate.cancel();
    vi.advanceTimersByTime(1000);
    expect(applied).toEqual([0]);
  });
});
