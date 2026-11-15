import type { ExtrasVM } from "./types";

/** The four parts with nothing to show: the value every block must be able to draw. */
export const EMPTY_EXTRAS: ExtrasVM = {
  threeColour: { frames: null, ranges: { r: "", g: "", b: "" } },
  markers: { status: "unavailable", note: null, gaia: [], catwise: [], was: null },
  thenAndNow: { status: "none", note: null, older: null, sphx: null },
  spectrum: {
    open: false,
    status: "closed",
    messages: [],
    visits: [],
    points: [],
    binned: [],
    mode: "chart",
    recorded: null,
  },
  handlers: { toggleSpectrum() {}, setSpectrumMode() {}, downloadCsv() {} },
};
