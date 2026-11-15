/**
 * Margin (LANE: image): scale bar, readout (at 1280 and 1440 only) and compass, under the image.
 *
 * PORTS: Main.dc.html 263–274 (scale bar, the readout between, compass; padding 0 at 1280);
 *        Phone.dc.html 175–181 (scale bar and compass only; the readout is its own line).
 * FLAGS: none (never removed with a feature).
 * STATES: the bar is drawn vm.geometry.scaleBar.lengthPx long in every state; its label says what
 *         that length is on the sky at the scale in use (one frame, pair, spotlight), in a fixed
 *         field of 5 characters, and the scale beside it in 3 ("4×", "12×", "2×").
 *         Compass: "North is up, east is left".
 * USES: vm.geometry, the readout (image/readout.tsx), vm.layout.
 */
import "../image/image.css";
import { scaleLabel } from "../format";
import { ReadoutLine } from "../image/readout";
import { fitInUse } from "../image/scene";
import { chars } from "../image/states";
import type { ViewModel } from "../vm";

function Compass() {
  return (
    <svg
      className="bc-compass"
      viewBox="0 0 44 44"
      role="img"
      aria-label="North is up, east is left"
    >
      <path d="M32.5 36V12M29 16l3.5-4 3.5 4M32.5 36H10M14 32.5l-4 3.5 4 3.5" />
      <text x="32.5" y="9" textAnchor="middle">
        N
      </text>
      <text x="4" y="40" textAnchor="middle">
        E
      </text>
    </svg>
  );
}

export function Margin({ vm }: { vm: ViewModel }) {
  const inline = vm.layout === "three" || vm.layout === "wide";
  const scale = fitInUse(vm).scale;
  const bar = vm.geometry.scaleBar;
  const length = bar.lengthPx;
  const arcsec = bar.arcsecAt(scale);
  const drawn = Number.isInteger(scale) ? String(scale) : scale.toFixed(1);
  return (
    <div className="bc-framefoot img-margin">
      <span
        className="bc-scalebar"
        role="img"
        aria-label={`Scale bar: ${arcsec} arcseconds. Each image pixel is drawn ${drawn} pixels wide.`}
      >
        <svg width={length + 1} height="9" viewBox={`0 0 ${length + 1} 9`} aria-hidden="true">
          <path d={`M0.5 0V9M0.5 4.5H${length + 0.5}M${length + 0.5} 0V9`} />
        </svg>
        <span aria-hidden="true">
          <span className="bc-fixed" style={chars(5)}>{`${arcsec}″`}</span>
          <span className="bc-fixed bc-muted" style={chars(3)}>
            {scaleLabel(scale)}
          </span>
        </span>
      </span>
      {inline && <ReadoutLine vm={vm} inMargin />}
      <Compass />
    </div>
  );
}
