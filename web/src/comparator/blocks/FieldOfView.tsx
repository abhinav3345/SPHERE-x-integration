/**
 * FieldOfView (LANE: view).
 *
 * PORTS: Main.dc.html 500–512; Phone.dc.html 486–496 (3′ 4′ 5′ 6′ 8′ 10′, one row).
 * FLAGS: none.
 * STATES: aria-checked on vm.state.fov; with the engine down and a recorded field on screen every
 *         size but 6′ is aria-disabled and vm.fovNote says why, under the group.
 * KEYS: one Tab stop; arrows move and select, skipping greyed options, wrapping; Home, End.
 * USES: vm.fovs, vm.fovNote, vm.handlers.setFov.
 * IDS: label #tb-fov; note #tb-fov-note.
 */
import { RadioGroup } from "../view/RadioGroup";
import "../view/view.css";
import type { ViewModel } from "../vm";

export function FieldOfView({ vm }: { vm: ViewModel }) {
  return (
    <div className="bc-group">
      <span className="bc-group__label" id="tb-fov">
        Field of view
      </span>
      <RadioGroup
        labelledBy="tb-fov"
        describedBy={vm.fovNote ? "tb-fov-note" : undefined}
        options={vm.fovs}
        onSelect={vm.handlers.setFov}
      >
        {(option) => option.label}
      </RadioGroup>
      {vm.fovNote && (
        <p className="bc-note" id="tb-fov-note">
          {vm.fovNote}
        </p>
      )}
    </div>
  );
}
