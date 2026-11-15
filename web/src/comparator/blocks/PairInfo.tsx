/**
 * PairInfo (LANE: time).
 *
 * PORTS: Main.dc.html 85–92 (Side by side: "The pair on screen", A and B with dates, the note),
 *        94–102 (Difference: "Later minus earlier", B then A, two notes) and 104–111 (Then and
 *        now: the survey lines and the note); min-height 160px at 1280 (time.css).
 *        Phone.dc.html 284–308 (Difference keeps only its second note; Then and now has no note
 *        there: it sits under the other survey's label).
 * FLAGS: sideBySide, difference — vm.pairInfo is null outside those views. thenAndNow — the
 *        Then and now block, from vm.extras.thenAndNow.
 * STATES: Then and now names the other survey ("Then: WISE W2, 2010") and the SPHEREx stack the
 *         other square shows (extras: one stack over every visit, so "Now:" names that stack,
 *         not "the SPHEREx frame chosen below"). While the older image is missing or loading,
 *         the extras lane's note says why; nothing is invented in its place.
 * USES: vm.pairInfo.{aWhen,bWhen} (fixed form), vm.field.view, vm.extras.thenAndNow, vm.layout.
 */
import { isThreeColumns, thenAndNowLines } from "../time/rail";
import "../time/time.css";
import type { ViewModel } from "../vm";

function EpochTag({ tag, when }: { tag: "A" | "B"; when: string }) {
  return (
    <span className="bc-epochtag">
      <span className={tag === "A" ? "bc-swatch bc-swatch--a" : "bc-swatch bc-swatch--b"} />
      {tag}
      <span className="bc-value">{when}</span>
    </span>
  );
}

const CHOOSE = "Choose a frame below and it takes the place of the one you chose before.";

export function PairInfo({ vm }: { vm: ViewModel }) {
  const view = vm.field?.view ?? null;
  const wide = isThreeColumns(vm.layout);

  if (view === "then") {
    if (!vm.features.thenAndNow) return null;
    const lines = thenAndNowLines(vm.extras.thenAndNow);
    return (
      <div className="bc-stack tl-block">
        <span className="bc-group__label">Then and now</span>
        {lines.older && <p className="bc-framelabel__source">{lines.older}</p>}
        {lines.sphx && <p className="bc-framelabel__source">{lines.sphx}</p>}
        {lines.why && <p className="bc-note">{lines.why}</p>}
        {wide && lines.older && (
          <p className="bc-note">
            Only positions compare. Each survey keeps its own brightness scale.
          </p>
        )}
      </div>
    );
  }

  const pair = vm.pairInfo;
  if (!pair) return null;
  if (view === "side" && vm.features.sideBySide) {
    return (
      <div className="bc-stack tl-block">
        <span className="bc-group__label">The pair on screen</span>
        <EpochTag tag="A" when={pair.aWhen} />
        <EpochTag tag="B" when={pair.bWhen} />
        <p className="bc-note">A is always the earlier frame. {CHOOSE}</p>
      </div>
    );
  }
  if (view === "difference" && vm.features.difference) {
    return (
      <div className="bc-stack tl-block">
        <span className="bc-group__label">Later minus earlier</span>
        <EpochTag tag="B" when={pair.bWhen} />
        <EpochTag tag="A" when={pair.aWhen} />
        {wide && (
          <p className="bc-note">Pairs half a year apart leave small marks on bright stars.</p>
        )}
        <p className="bc-note">{CHOOSE}</p>
      </div>
    );
  }
  return null;
}
