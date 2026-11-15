/**
 * Targets (LANE: time).
 *
 * PORTS: Main.dc.html 129–140 (time rail, in the timeline's place when no frame is on screen:
 *        the list gives up height and scrolls like the timeline);
 *        Phone.dc.html 542–551 (in "Go to another position").
 * FLAGS: none of its own. Rows without a recorded field (Epsilon Indi B, RW Aurigae, R Draconis)
 *        open a build where the target is at the frames' epoch (vm.handlers.openTarget; no name
 *        lookup). A row that cannot open (vm.targets[].available false: the archive is not
 *        responding) says why in place of its caption and is not a link.
 * STATES: row.current (8px filled mark, aria-current="true"), row.loading (caption "Building this
 *         image…", aria-busy), row.saturated (qualifier chip "Saturated core" with the hatch
 *         mark). A recorded field's link is its own address (?target=…), so it also opens in a
 *         new tab; a plain click opens it in place through vm.handlers.openTarget.
 * USES: vm.targets, vm.layout, vm.handlers.openTarget(id).
 * IDS: the group #tb-targets ("See the targets" jumps here).
 */
import type { MouseEvent } from "react";
import type { TargetId } from "../model";
import { isThreeColumns, opensInPlace, targetHref } from "../time/rail";
import "../time/time.css";
import type { TargetRowVM, ViewModel } from "../vm";

function Name({ row }: { row: TargetRowVM }) {
  return (
    <span className="bc-target__name">
      {row.name}
      {row.saturated && (
        <span className="bc-chip bc-chip--qualifier">
          <span className="bc-mark bc-mark--hatch" />
          Saturated core
        </span>
      )}
    </span>
  );
}

export function Targets({ vm }: { vm: ViewModel }) {
  const open = (id: TargetId) => (event: MouseEvent<HTMLAnchorElement>) => {
    const href = event.currentTarget.getAttribute("href") ?? "";
    // A modified click on a real address is the browser's: a new tab or window.
    if (href.startsWith("?") && !opensInPlace(event)) return;
    event.preventDefault();
    vm.handlers.openTarget(id);
  };
  const list = (
    <div className="bc-targets">
      {vm.targets.map((row) =>
        row.available ? (
          <a
            key={row.id}
            className="bc-target"
            href={targetHref(row.id)}
            aria-current={row.current ? "true" : undefined}
            aria-busy={row.loading || undefined}
            onClick={open(row.id)}
          >
            <Name row={row} />
            <span className="bc-target__caption">{row.caption}</span>
          </a>
        ) : (
          <div key={row.id} className="bc-target tl-target--off">
            <Name row={row} />
            <span className="bc-target__caption">{row.unavailable}</span>
          </div>
        ),
      )}
    </div>
  );
  return isThreeColumns(vm.layout) ? (
    <div className="tl-targets" id="tb-targets">
      <span className="bc-group__label">Targets</span>
      {list}
    </div>
  ) : (
    <div className="bc-group" id="tb-targets">
      <span className="bc-group__label">Targets</span>
      {list}
    </div>
  );
}
