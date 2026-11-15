/**
 * Shortcuts (LANE: time).
 *
 * PORTS: Main.dc.html 77–83 (bc-shortcuts: Space, ← →, Esc).
 * FLAGS: spotlight — the Esc line reads "Stop playing, then close the spotlight" when on,
 *        "Stop playing" when off (Handoff-removable: Esc then only stops playback).
 * STATES: rendered only when vm.playback.shortcuts (1440 × 900, Blink, a frame on screen, motion
 *         allowed: never under reduced motion).
 */
import type { ViewModel } from "../vm";

export function Shortcuts({ vm }: { vm: ViewModel }) {
  if (!vm.playback.shortcuts) return null;
  return (
    <dl className="bc-shortcuts">
      <dt>
        <kbd className="bc-kbd">Space</kbd>
      </dt>
      <dd>Play or pause</dd>
      <dt>
        <kbd className="bc-kbd">←</kbd>
        <kbd className="bc-kbd">→</kbd>
      </dt>
      <dd>Previous or next frame</dd>
      <dt>
        <kbd className="bc-kbd">Esc</kbd>
      </dt>
      <dd>{vm.features.spotlight ? "Stop playing, then close the spotlight" : "Stop playing"}</dd>
    </dl>
  );
}
