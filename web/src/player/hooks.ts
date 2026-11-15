import { type MouseEvent, useEffect, useState, useSyncExternalStore } from "react";
import { type ClockState, FrameClock } from "./playback";

/**
 * A playback clock for a sequence of `count` frames. It is paused whenever `count` changes
 * and when the component unmounts: playback only ever starts from a user action.
 */
export function useFrameClock(count: number): [FrameClock, ClockState] {
  const [clock] = useState(() => new FrameClock());
  const state = useSyncExternalStore(clock.subscribe, clock.getState);
  useEffect(() => {
    clock.reset(count);
    return () => clock.dispose();
  }, [clock, count]);
  return [clock, state];
}

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

function subscribeToReducedMotion(onChange: () => void): () => void {
  const media = window.matchMedia(REDUCED_MOTION);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

/** True when the system asks for reduced motion; follows the setting live. */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeToReducedMotion,
    () => window.matchMedia(REDUCED_MOTION).matches,
    () => false,
  );
}

/**
 * `onMouseDown` handler for buttons: a mouse click then leaves keyboard focus where it was,
 * so Space still means play/pause right after clicking a control. Keyboard users are not
 * affected: a button they tab to keeps its own Space and Enter.
 */
export function keepFocus(event: MouseEvent): void {
  event.preventDefault();
}
