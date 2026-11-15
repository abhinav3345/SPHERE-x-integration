/**
 * FrameLabel (LANE: image): the plate annotation under the image.
 *
 * PORTS: Main.dc.html 295–339 (one frame; "B … minus A …"; two labels side by side);
 *        Phone.dc.html 214–248 (frame B's label here, frame A's between the squares).
 * FLAGS: sideBySide (two labels), difference ("B … minus A …"), thenAndNow (the survey labels:
 *        dashed "WISE W2, 2010" with "Its own brightness scale", and the SPHEREx stack's).
 * STATES: vm.frameLabel.kind: one | diff | two | state. The chip row (24 px) is reserved even
 *         when empty: Partial frame, Thin frame, Saturated core; "Newest SPHEREx image: …" when
 *         no image covers the position. The date in its fixed 21-character form (padded to the
 *         sequence's longest), the range at fixed length, the count right-aligned in 3 characters.
 *         The resampling note when vm.frameLabel.showPixels. aria-live="off": nothing is announced.
 * USES: vm.frameLabel, vm.field, vm.extras.thenAndNow.
 */
import "../image/image.css";
import { DiffLabel, OneLabel, PairLabel, SphxLabel, SurveyLabel } from "../image/labels";
import type { ViewModel } from "../vm";

export function FrameLabel({ vm }: { vm: ViewModel }) {
  const label = vm.frameLabel;
  const field = vm.field;
  const phoneLike = vm.layout === "phone" || vm.layout === "rail";
  const onScreen = vm.image.state === "image" && field !== null;

  if (onScreen && field.view === "difference" && label.diff) {
    return <DiffLabel diff={label.diff} note={phoneLike} />;
  }

  if (onScreen && field.view === "then") {
    const then = vm.extras.thenAndNow;
    const saturated = field.labels.some((l) => l.saturated);
    const sphx = <SphxLabel then={then} saturated={saturated} note={phoneLike} />;
    if (phoneLike) return sphx;
    return (
      <div className="img-labels">
        <SurveyLabel older={then.status === "ready" ? then.older : null} />
        {sphx}
      </div>
    );
  }

  if (onScreen && field.view === "side" && label.a && label.b) {
    if (phoneLike) return <PairLabel which="B" label={label.b} />;
    return (
      <div className="img-labels">
        <PairLabel which="A" label={label.a} />
        <PairLabel which="B" label={label.b} />
      </div>
    );
  }

  return <OneLabel vm={vm} />;
}
