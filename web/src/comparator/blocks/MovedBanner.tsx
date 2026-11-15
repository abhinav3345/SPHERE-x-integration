/**
 * MovedBanner (LANE: time).
 *
 * PORTS: Main.dc.html 43–51 (time rail, above the playback, with or without its button);
 *        Phone.dc.html 53–63 (above the image while it carries its button, in the gutter:
 *        time.css) and 389–393 (under the playback after the jump). Comparator places it; the
 *        block just renders.
 * FLAGS: movedBanner — vm.notices.mover is null when it is off, so the block renders nothing.
 * STATES: vm.notices.mover.sentence (from the search lane's MoverHint, e.g. "WISE 0855-0714 was
 *         here in 2010. It is now 126″ to the west."); vm.notices.mover.canJump adds the one lit
 *         button "Go to where it is now" (bc-button--primary, vm.handlers.jump), while the reader
 *         is at the catalogue position; after the jump the banner stays without it. Message
 *         notice, role="status", information icon. Focus never moves to it.
 */
import { Icon } from "../../design/icons";
import "../time/time.css";
import type { ViewModel } from "../vm";

export function MovedBanner({ vm }: { vm: ViewModel }) {
  const mover = vm.notices.mover;
  if (!vm.features.movedBanner || !mover) return null;
  return (
    <div className="bc-notice tl-notice" role="status">
      <Icon name="information" />
      <div>
        <p>{mover.sentence}</p>
        {mover.canJump && (
          <div className="bc-notice__actions">
            <button
              className="bc-button bc-button--primary"
              type="button"
              onClick={() => vm.handlers.jump()}
            >
              Go to where it is now
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
