/**
 * The plate annotations (FrameLabel card; Main.dc.html 295–339, Phone.dc.html 214–248), shared by
 * FrameLabel and, on a phone, ImageFrame (frame A's label sits between the two squares).
 * Every value that changes with the frame sits in a fixed field: the dates padded to one width,
 * the range at fixed length, the count right-aligned in three characters, the chip row 24 px.
 */
import type { SurveyFrameVM, ThenAndNowVM } from "../extras/types";
import type { FrameLabel } from "../model";
import type { ViewModel } from "../vm";

export function SaturatedChip() {
  return (
    <span className="bc-chip bc-chip--qualifier">
      <span className="bc-mark bc-mark--hatch" />
      Saturated core
    </span>
  );
}

/**
 * The qualifier chips of one frame. "Saturated core" is a fact of the field, so it comes first:
 * a frame's own chips (Partial frame, Thin frame) then appear after it and never push it along
 * when the frame changes (the design lists it last).
 */
export function Chips({ label }: { label: FrameLabel }) {
  return (
    <>
      {label.saturated && <SaturatedChip />}
      {label.partial && <span className="bc-chip bc-chip--qualifier">Partial frame</span>}
      {label.thin && <span className="bc-chip bc-chip--qualifier">Thin frame</span>}
    </>
  );
}

/** The date range, then the wavelength range and the exposure count. */
export function Facts({ label }: { label: FrameLabel }) {
  return (
    <>
      <p className="bc-framelabel__when">{label.when}</p>
      <p className="bc-framelabel__facts">
        <span>{label.range}</span>
        <span>{label.count}</span>
      </p>
    </>
  );
}

export function EpochTag({ which, value }: { which: "A" | "B"; value?: string }) {
  return (
    <span className="bc-epochtag">
      <span className={`bc-swatch bc-swatch--${which === "A" ? "a" : "b"}`} />
      {which}
      {value !== undefined && <span className="bc-value">{value}</span>}
    </span>
  );
}

/** Blink and the states: the frame on screen, or "Building this image", "No frames here"… */
export function OneLabel({ vm }: { vm: ViewModel }) {
  const label = vm.frameLabel;
  const newest = vm.image.state === "empty" ? vm.timeline.newest : null;
  return (
    <div className="bc-framelabel img-label" aria-live="off">
      <div className="bc-framelabel__chips">
        <Chips label={label.one} />
        {newest && (
          <span className="bc-chip">
            Newest SPHEREx image: <span className="bc-value">{newest}</span>
          </span>
        )}
      </div>
      <Facts label={label.one} />
      {label.showPixels && <p className="bc-note">{label.pixels}</p>}
    </div>
  );
}

/** Side by side: the label of frame A or B. */
export function PairLabel({ which, label }: { which: "A" | "B"; label: FrameLabel }) {
  return (
    <div className="bc-framelabel img-label img-label--pair" aria-live="off">
      <div className="bc-framelabel__chips">
        <EpochTag which={which} />
        <Chips label={label} />
      </div>
      <Facts label={label} />
    </div>
  );
}

/** Then and now: the older survey's label, dashed, on its own brightness scale. */
export function SurveyLabel({ older }: { older: SurveyFrameVM | null }) {
  return (
    <div className="bc-framelabel bc-framelabel--survey img-label img-label--pair" aria-live="off">
      <div className="bc-framelabel__chips">
        {older && <span className="bc-chip bc-chip--qualifier">Its own brightness scale</span>}
      </div>
      {older && <p className="bc-framelabel__source">{older.title}</p>}
      {older && (
        <p className="bc-framelabel__facts">
          <span>{older.dates}</span>
        </p>
      )}
      <p className="bc-note">Other survey</p>
    </div>
  );
}

/** Then and now: the SPHEREx stack's label. On a phone it carries the note about brightness. */
export function SphxLabel({
  then,
  saturated,
  note,
}: {
  then: ThenAndNowVM;
  saturated: boolean;
  note: boolean;
}) {
  const sphx = then.sphx;
  return (
    <div className="bc-framelabel img-label img-label--pair" aria-live="off">
      <div className="bc-framelabel__chips">
        <span className="bc-chip">SPHEREx</span>
        {saturated && <SaturatedChip />}
      </div>
      {sphx && <p className="bc-framelabel__when">{sphx.dates}</p>}
      {sphx && (
        <p className="bc-framelabel__facts">
          <span>{sphx.title}</span>
          <span>{sphx.exposures}</span>
        </p>
      )}
      {note && (
        <p className="bc-note">
          Only positions compare. Each survey keeps its own brightness scale.
        </p>
      )}
    </div>
  );
}

/** Difference: "B 21 Apr–14 May 2026 minus A 7–14 Nov 2025". */
export function DiffLabel({ diff, note }: { diff: { a: string; b: string }; note: boolean }) {
  return (
    <div className="bc-framelabel img-label" aria-live="off">
      <p className="img-difflabel">
        <EpochTag which="B" value={diff.b} />
        <span className="bc-note">minus</span>
        <EpochTag which="A" value={diff.a} />
      </p>
      {note && (
        <p className="bc-note">Pairs half a year apart leave small marks on bright stars.</p>
      )}
    </div>
  );
}
