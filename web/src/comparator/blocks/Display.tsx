/**
 * Display (LANE: view).
 *
 * PORTS: Main.dc.html 514–527; Phone.dc.html 498–509 (Contrast slider 0–8 with its note on the same
 *        line, the nine engraved ticks, then the Invert and Markers toggles).
 * FLAGS: contrast (off: the slider and its label go, the note "Same brightness scale for every
 *        frame" becomes the first line), invert (off: Markers starts the row). The note and the
 *        Markers toggle always stay. Markers hides the ring and every catalogue marker (the image
 *        lane draws them from vm.image.markers).
 * STATES: greyed with vm.display.note while no frame is on screen: the slider is disabled; the
 *         toggles stay focusable with aria-disabled and the note as their description (Button
 *         card). Toggles: role="switch", aria-checked, state word "On"/"Off".
 * USES: vm.display, vm.features.{contrast,invert}, vm.handlers.{setContrast,setInvert,setMarkers}.
 * IDS: slider #tb-contrast; note #tb-display-note.
 */
import { CONTRAST_STEPS } from "../model";
import "../view/view.css";
import type { ViewModel } from "../vm";

const NOTE = "Same brightness scale for every frame";
const TICKS = Array.from({ length: CONTRAST_STEPS + 1 }, (_, step) => step);

function Toggle({
  label,
  on,
  disabled,
  describedBy,
  onToggle,
}: {
  label: string;
  on: boolean;
  disabled: boolean;
  describedBy: string | undefined;
  onToggle(): void;
}) {
  return (
    <button
      className="bc-toggle"
      type="button"
      role="switch"
      aria-checked={on}
      aria-disabled={disabled || undefined}
      aria-describedby={disabled ? describedBy : undefined}
      onClick={() => {
        if (!disabled) onToggle();
      }}
    >
      <span className="bc-toggle__track">
        <span className="bc-toggle__knob" />
      </span>
      <span>{label}</span>
      <span className="bc-toggle__state" aria-hidden="true">
        {on ? "On" : "Off"}
      </span>
    </button>
  );
}

export function Display({ vm }: { vm: ViewModel }) {
  const d = vm.display;
  const noteId = d.note ? "tb-display-note" : undefined;
  return (
    <div className="bc-group">
      {vm.features.contrast ? (
        <>
          <div className="vw-display__head">
            <label className="bc-group__label" htmlFor="tb-contrast">
              Contrast
            </label>
            <span className="bc-note">{NOTE}</span>
          </div>
          <div>
            <input
              className="bc-slider"
              id="tb-contrast"
              type="range"
              min={0}
              max={CONTRAST_STEPS}
              step={1}
              value={d.contrast}
              disabled={d.disabled}
              aria-describedby={noteId}
              onChange={(event) => vm.handlers.setContrast(Number(event.currentTarget.value))}
            />
            <div className="bc-ticks" aria-hidden="true">
              {TICKS.map((step) => (
                <span key={step} />
              ))}
            </div>
          </div>
        </>
      ) : (
        <p className="bc-note">{NOTE}</p>
      )}
      <div className="vw-display__toggles">
        {vm.features.invert && (
          <Toggle
            label="Invert"
            on={d.invert}
            disabled={d.disabled}
            describedBy={noteId}
            onToggle={() => vm.handlers.setInvert(!d.invert)}
          />
        )}
        <Toggle
          label="Markers"
          on={d.markers}
          disabled={d.disabled}
          describedBy={noteId}
          onToggle={() => vm.handlers.setMarkers(!d.markers)}
        />
      </div>
      {d.note && (
        <p className="bc-note" id="tb-display-note">
          {d.note}
        </p>
      )}
    </div>
  );
}
