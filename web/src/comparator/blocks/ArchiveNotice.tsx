/**
 * ArchiveNotice (LANE: time).
 *
 * PORTS: Main.dc.html 33–41 (time rail, under the search); Phone.dc.html 41–51 (above the image,
 *        in the 16px gutter with 12px under it: time.css).
 * FLAGS: none.
 * STATES: rendered only while vm.notices.archive: "The archive is not responding. Showing the
 *         recorded field instead." with the button "Try again" (vm.handlers.retry).
 *         Warning notice, role="status". Focus never moves to it.
 * RETURNS null otherwise (the slot then takes no room).
 */
import { Icon } from "../../design/icons";
import "../time/time.css";
import type { ViewModel } from "../vm";

export function ArchiveNotice({ vm }: { vm: ViewModel }) {
  if (!vm.notices.archive) return null;
  return (
    <div className="bc-notice bc-notice--warning tl-notice" role="status">
      <Icon name="warning" label="Warning" />
      <div>
        <p>The archive is not responding. Showing the recorded field instead.</p>
        <div className="bc-notice__actions">
          <button className="bc-button" type="button" onClick={() => vm.handlers.retry()}>
            Try again
          </button>
        </div>
      </div>
    </div>
  );
}
