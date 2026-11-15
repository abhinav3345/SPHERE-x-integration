/**
 * Readout (LANE: image): its own line under the ring buttons, on a phone and in the rail layout.
 *
 * PORTS: Phone.dc.html 208–212 (14ch, 13ch and the brightness; see image/readout.tsx for 15ch).
 * FLAGS: none.
 * STATES: Comparator places it on a phone and in the rail layout only (at 1280 the readout is in
 *         the Margin). Shows the pixel under a mouse pointer (rail layout), else the pixel cursor,
 *         else the ring (always the ring on a touch screen). aria-live="off". Each field holds a
 *         dash and keeps its width without a pixel.
 * USES: vm.readout, vm.readoutAt (image/pointer.ts).
 */
import "../image/image.css";
import { ReadoutLine } from "../image/readout";
import type { ViewModel } from "../vm";

export function Readout({ vm }: { vm: ViewModel }) {
  return <ReadoutLine vm={vm} inMargin={false} />;
}
