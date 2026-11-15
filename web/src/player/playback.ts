/**
 * Playback clock of the blink: which frame is shown, and when it may change.
 *
 * Two rules are built in here rather than left to the interface:
 *   - playback never starts by itself: only `play()` or `toggle()` starts it, and a new
 *     sequence always arrives paused;
 *   - the picture never changes more than 6 times per second, whatever asks for the change
 *     (the timer, a held arrow key, fast clicking). Six changes are three flashes per second.
 *
 * No React and no DOM in this file, so the rules are unit-tested with fake timers.
 */

/** Hard ceiling on frame changes per second. */
export const MAX_FPS = 6;
/** Default playback rate, frame changes per second. */
export const DEFAULT_FPS = 2;
/** Rates offered in the interface, frame changes per second. */
export const FPS_CHOICES = [1, 2, 3, 4, 6] as const;
/** Slowest rate accepted, frame changes per second. */
const MIN_FPS = 0.25;
/** Shortest time between two frame changes, ms. */
export const MIN_CHANGE_INTERVAL_MS = 1000 / MAX_FPS;

/** A rate limited to what the player allows; anything unusable becomes the default. */
export function clampFps(fps: number): number {
  if (!Number.isFinite(fps) || fps <= 0) return DEFAULT_FPS;
  return Math.min(MAX_FPS, Math.max(MIN_FPS, fps));
}

/** The index `delta` steps from `index` in a looping sequence of `count` frames. */
export function stepIndex(index: number, count: number, delta: number): number {
  if (count <= 0) return 0;
  return (((index + delta) % count) + count) % count;
}

/** How long to wait, in ms, before the next frame change is allowed (0 = now). */
export function waitBeforeChange(nowMs: number, lastChangeMs: number): number {
  return Math.max(0, lastChangeMs + MIN_CHANGE_INTERVAL_MS - nowMs);
}

type Timer = ReturnType<typeof setTimeout>;

/**
 * The one rate limit on picture changes: whatever asks for a change (a timer, a held arrow key,
 * the flip key, fast clicking), the picture changes at most 6 times per second.
 *
 * `request(apply)` runs `apply` at once when a change is allowed, else at the first allowed
 * moment. A newer request replaces one that is still waiting, so a held key changes the picture
 * once per slot. `apply` returns true when it really changed the picture; only then does the gate
 * close for 1/6 s.
 */
export class ChangeGate {
  private lastChangeMs = Number.NEGATIVE_INFINITY;
  private pending: Timer | null = null;

  /** @param now clock in ms; injectable so tests can drive time */
  constructor(private readonly now: () => number = () => performance.now()) {}

  request(apply: () => boolean): void {
    this.cancel();
    const wait = waitBeforeChange(this.now(), this.lastChangeMs);
    if (wait <= 0) {
      if (apply()) this.lastChangeMs = this.now();
      return;
    }
    // Timers take whole milliseconds and may fire a little early, so the limit is checked
    // again when this one fires.
    this.pending = setTimeout(() => {
      this.pending = null;
      this.request(apply);
    }, Math.ceil(wait));
  }

  /** True while a request waits for its slot. */
  get waiting(): boolean {
    return this.pending !== null;
  }

  /** Drops a request that is still waiting. */
  cancel(): void {
    if (this.pending !== null) clearTimeout(this.pending);
    this.pending = null;
  }
}

export interface ClockState {
  /** Index of the frame shown, 0-based. */
  index: number;
  /** Number of frames in the sequence. */
  count: number;
  playing: boolean;
  /** Playback rate, frame changes per second. */
  fps: number;
}

export class FrameClock {
  private state: ClockState = { index: 0, count: 0, playing: false, fps: DEFAULT_FPS };
  private readonly listeners = new Set<() => void>();
  private readonly gate: ChangeGate;
  private ticker: Timer | null = null;

  /** @param now clock in ms; injectable so tests can drive time */
  constructor(now: () => number = () => performance.now()) {
    this.gate = new ChangeGate(now);
  }

  /** Calls `listener` after every state change; returns the function that stops it. */
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getState = (): ClockState => this.state;

  /** A new sequence of `count` frames. It arrives paused; the index is kept when still valid. */
  reset(count: number): void {
    this.stopTimers();
    const size = Math.max(0, Math.floor(count));
    const index = this.state.index < size ? this.state.index : 0;
    this.update({ count: size, index, playing: false });
  }

  setFps(fps: number): void {
    this.update({ fps: clampFps(fps) });
    if (this.state.playing) this.startTicker();
  }

  /** Starts looping through the sequence. Does nothing with fewer than two frames. */
  play(): void {
    if (this.state.playing || this.state.count < 2) return;
    this.update({ playing: true });
    this.startTicker();
  }

  pause(): void {
    if (!this.state.playing) return;
    this.stopTimers();
    this.update({ playing: false });
  }

  toggle(): void {
    if (this.state.playing) this.pause();
    else this.play();
  }

  /** Moves `delta` frames forward (or back, when negative), looping at the ends. */
  step(delta: number): void {
    this.requestChange((index) => stepIndex(index, this.state.count, delta));
  }

  /** Shows the frame at `index`. */
  show(index: number): void {
    if (!Number.isInteger(index) || index < 0 || index >= this.state.count) return;
    this.requestChange(() => index);
  }

  /** Stops all timers. The clock can be reset and used again afterwards. */
  dispose(): void {
    this.stopTimers();
    this.update({ playing: false });
  }

  /**
   * Applies a change now when the rate limit allows, else at the first allowed moment.
   * A newer request replaces one that is still waiting, so a held key steps once per slot.
   */
  private requestChange(target: (index: number) => number): void {
    this.gate.request(() => this.applyChange(target));
  }

  /** Applies a change; false when it would not change the picture. */
  private applyChange(target: (index: number) => number): boolean {
    const next = target(this.state.index);
    if (next === this.state.index || next < 0 || next >= this.state.count) return false;
    this.update({ index: next });
    return true;
  }

  private startTicker(): void {
    if (this.ticker !== null) clearInterval(this.ticker);
    // Whole milliseconds, rounded up: at 6 per second a tick comes every 167 ms.
    const period = Math.ceil(1000 / clampFps(this.state.fps));
    this.ticker = setInterval(() => this.step(1), period);
  }

  private stopTimers(): void {
    if (this.ticker !== null) clearInterval(this.ticker);
    this.gate.cancel();
    this.ticker = null;
  }

  private update(patch: Partial<ClockState>): void {
    const next = { ...this.state, ...patch };
    const changed = (Object.keys(next) as (keyof ClockState)[]).some(
      (key) => next[key] !== this.state[key],
    );
    if (!changed) return;
    this.state = next;
    for (const listener of this.listeners) listener();
  }
}
