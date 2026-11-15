/**
 * The readout: three fixed fields, RA, Dec and the brightness, for the pixel under the pointer,
 * else the pixel cursor, else the ring (Handoff-behaviour, Pointer and touch). Each field keeps
 * its width whatever it holds, so nothing moves when the frame changes under a resting pointer.
 */
import type { ViewModel } from "../vm";
import { usePointer } from "./pointer";
import { chars } from "./states";

/**
 * Field widths in characters. At 1280 the third field is the design's 24. On a phone the design
 * gives it 12, the width of "0.142 MJy/sr"; 15 holds every brightness the formatter writes
 * ("−0.0180 MJy/sr"), so the field never jumps between the first and the second line.
 */
const WIDE = [14, 13, 24] as const;
const NARROW = [14, 13, 15] as const;

export function ReadoutLine({ vm, inMargin }: { vm: ViewModel; inMargin: boolean }) {
  const pointer = usePointer();
  const readout = pointer && vm.image.state === "image" ? vm.readoutAt(pointer) : vm.readout;
  const [ra, dec, value] = inMargin ? WIDE : NARROW;
  return (
    <p className={inMargin ? "bc-readout img-readout--margin" : "bc-readout"} aria-live="off">
      <span className="bc-readout__field" style={chars(ra)}>
        <span className="bc-readout__key">RA </span>
        {readout.ra}
      </span>
      <span className="bc-readout__field" style={chars(dec)}>
        <span className="bc-readout__key">Dec </span>
        {readout.dec}
      </span>
      <span className="bc-readout__field" style={chars(value)}>
        {readout.value}
      </span>
    </p>
  );
}
