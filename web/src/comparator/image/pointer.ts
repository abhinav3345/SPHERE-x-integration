/**
 * The pixel under the pointer: state of the image lane only, shared by the frame (which sets it)
 * and the readouts (Margin at 1280, Readout in the column), which show it before the pixel cursor
 * and the ring (Handoff-behaviour, Pointer and touch). Touch never sets it: on a phone the
 * readout shows the ring.
 */
import { useSyncExternalStore } from "react";
import type { Offset } from "../model";

let pointer: Offset | null = null;
const listeners = new Set<() => void>();

export function setPointer(next: Offset | null): void {
  const same =
    next === pointer ||
    (next !== null && pointer !== null && next.dx === pointer.dx && next.dy === pointer.dy);
  if (same) return;
  pointer = next;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const snapshot = () => pointer;

/** The offset of the pixel under the pointer, or null. */
export function usePointer(): Offset | null {
  return useSyncExternalStore(subscribe, snapshot, () => null);
}
