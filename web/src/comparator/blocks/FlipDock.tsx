/**
 * FlipDock (LANE: time).
 *
 * PORTS: Phone.dc.html 250–255 (the sticky dock: last child of the image section).
 * FLAGS: holdToFlip — when off the dock is not rendered (the transport then sits under the label).
 * STATES: rendered on a phone and in the rail layout, in Blink only (not in Side by side,
 *         Difference or Then and now). position: sticky; bottom: 0 inside the image section, so
 *         it holds the foot of the screen while the section is on screen and its own slot is
 *         below the fold, and lets go by itself; 8px padding, color-bg, a color-line top edge,
 *         72px in all. Not pinned when the window is shorter than 560px (time.css). Held: the
 *         key's 2px inset line (aria-pressed), no fill. Greyed when there is nothing to flip; the
 *         reason is under the transport (Playback).
 * USES: vm.playback.{enabled,held}, vm.handlers.flipKey (time/FlipKey.tsx), vm.layout.
 */
import { FlipKey } from "../time/FlipKey";
import { isColumn } from "../time/rail";
import "../time/time.css";
import type { ViewModel } from "../vm";

export function FlipDock({ vm }: { vm: ViewModel }) {
  if (!vm.features.holdToFlip || !isColumn(vm.layout)) return null;
  if (vm.field && vm.field.view !== "blink") return null;
  return (
    <div className="tl-dock">
      <FlipKey vm={vm} />
    </div>
  );
}
