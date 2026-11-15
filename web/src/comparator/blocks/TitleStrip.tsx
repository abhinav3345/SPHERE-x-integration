/**
 * TitleStrip (LANE: view).
 *
 * PORTS: Phone.dc.html 31–38 (title in bc-title, the position in Source Code Pro at
 *        text-caption, the link "Change" to #tb-go with a 44px target).
 * FLAGS: none.
 * STATES: vm.title: "WISE 0855" / place name / "Sky position" / "No position yet", then the
 *         position line or "Type a position or a name below." or "Looking up the name.".
 *         Placed by Comparator on a phone and in the rail layout only.
 * USES: vm.title.
 */
import "../view/view.css";
import type { ViewModel } from "../vm";

export function TitleStrip({ vm }: { vm: ViewModel }) {
  return (
    <div className="vw-title">
      <div className="vw-title__text">
        <h1 className="bc-title">{vm.title.title}</h1>
        <p className="bc-value vw-title__line">{vm.title.line}</p>
      </div>
      <a className="bc-link bc-link--target" href="#tb-go">
        Change
      </a>
    </div>
  );
}
