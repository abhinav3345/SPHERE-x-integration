/**
 * The flip key (Playback card, item 1): 56px, full width, the largest control of the page. It
 * flips on pointer down and returns on pointer up, leave, cancel and blur; Space or Enter held
 * does the same and key repeat is ignored; its long-press menu is suppressed. All of that is
 * vm.handlers.flipKey. Held, it shows the system's 2px inset line and no fill (aria-pressed).
 * Used first in Playback at 1280 and 1440, and in FlipDock on a phone and in the rail layout.
 */
import { Icon } from "../../design/icons";
import type { ViewModel } from "../vm";

export function FlipKey({ vm }: { vm: ViewModel }) {
  return (
    <button
      className="bc-flip"
      type="button"
      aria-pressed={vm.playback.held}
      disabled={!vm.playback.enabled}
      {...vm.handlers.flipKey}
    >
      <Icon name="flip" />
      Hold to flip
    </button>
  );
}
