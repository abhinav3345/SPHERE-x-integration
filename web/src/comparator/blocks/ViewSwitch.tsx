/**
 * ViewSwitch (LANE: view).
 *
 * PORTS: Main.dc.html 363–372 (4 × 1); Phone.dc.html 427–436 (2 × 2, also in the rail layout).
 * FLAGS: sideBySide, difference, thenAndNow — vm.views lists built views only; the other cells
 *        share the row (1280: four, three or two cells; phone: 2 × 2 becomes one row of three or
 *        two). With Blink alone (vm.views.length < 2) the group is NOT rendered.
 * STATES: aria-checked on the view in force; aria-disabled options. Under the group, only while a
 *         view is greyed: why, one sentence per greyed view, in model.ts's words (view/notes.ts
 *         switchNotes); before a frame is on screen, vm.viewNote. The Then and now pairing note
 *         (vm.viewNote when nothing is greyed) is left to the Then and now block (PairInfo), so it
 *         is on screen once and the rail fits 1280 × 720.
 * KEYS: one Tab stop; arrows move and select, skipping greyed options, wrapping; Home, End. At most
 *       six changes a second; a held key moves once.
 * USES: vm.views, vm.viewNote, vm.field, vm.handlers.setView.
 * IDS: label #tb-view; note #tb-view-note.
 */
import { switchNotes, viewColumns } from "../view/notes";
import { RadioGroup } from "../view/RadioGroup";
import "../view/view.css";
import type { ViewModel } from "../vm";

export function ViewSwitch({ vm }: { vm: ViewModel }) {
  if (vm.views.length < 2) return null;
  const notes = switchNotes(vm);
  return (
    <div className="bc-group">
      <span className="bc-group__label" id="tb-view">
        View
      </span>
      <RadioGroup
        labelledBy="tb-view"
        describedBy={notes.length > 0 ? "tb-view-note" : undefined}
        options={vm.views}
        columns={viewColumns(vm.layout, vm.views.length)}
        paced
        onSelect={vm.handlers.setView}
      >
        {(option) => option.label}
      </RadioGroup>
      {notes.length > 0 && (
        <p className="bc-note" id="tb-view-note">
          {notes.join(" ")}
        </p>
      )}
    </div>
  );
}
