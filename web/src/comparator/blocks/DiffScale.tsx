/**
 * DiffScale (LANE: image): the key of the difference image.
 *
 * PORTS: Main.dc.html 276–283; Phone.dc.html 183–190 (bc-diffscale: ends, bar, ±5σ ticks, note).
 * FLAGS: difference — rendered only when the Difference view is on screen.
 * STATES: static: "Brighter earlier", "Brighter later", "Later minus earlier, in units of noise
 *         (σ)". The image is drawn on the same diff-* steps (render.ts sigmaColour).
 *         At 1280 × 720 the note sits between the two ends, on their line: the design's stack
 *         (frame, margin, scale, ring row, label, legend) is 728 px there, and the page must not
 *         scroll or clip. Every word stays.
 */
import "../image/image.css";
import type { ViewModel } from "../vm";

const TICKS = ["−5σ", "−4σ", "−3σ", "−2σ", "−1σ", "0", "+1σ", "+2σ", "+3σ", "+4σ", "+5σ"];
const NOTE = "Later minus earlier, in units of noise (σ)";

export function DiffScale({ vm }: { vm: ViewModel }) {
  if (!vm.features.difference || vm.image.state !== "image" || vm.field?.view !== "difference") {
    return null;
  }
  const compact = vm.layout === "three";
  return (
    <div className="bc-diffscale img-diffscale">
      <div className="bc-diffscale__ends">
        <span>Brighter earlier</span>
        {compact && <span className="bc-note img-diffscale__note">{NOTE}</span>}
        <span>Brighter later</span>
      </div>
      <div className="bc-diffscale__bar" />
      <div className="bc-diffscale__ticks" aria-hidden="true">
        {TICKS.map((tick) => (
          <span key={tick}>{tick}</span>
        ))}
      </div>
      {!compact && <p className="bc-note">{NOTE}</p>}
    </div>
  );
}
