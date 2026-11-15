/**
 * The four parts that need more than the SPHEREx stacks of one field: three-colour, catalogue
 * markers, Then and now, and the spectrum. This is the interface between the lane that produces
 * their data (extras: state, loading, the spectrum panel) and the lanes that draw them (image: the
 * frame, legend, ring row, frame label; view: the band and view options). Change it only together
 * with both sides.
 *
 * Positions are IMAGE pixels on the field grid: x to the right (west), y down (south), pixel
 * centres at integers, (0, 0) the top-left pixel. Brightness is MJy/sr; NaN means no data.
 */
import type { Limits } from "../../player/render";

/** One wavelength range of the three-colour view, with the scale shared by the whole sequence. */
export interface RgbChannelVM {
  data: Float32Array;
  /** Pooled over every frame of the sequence for this channel; null when the channel has no data. */
  limits: Limits | null;
}

export interface ThreeColourVM {
  /** One entry per frame of vm.field.sequence, or null when the band on screen is not three-colour. */
  frames: Array<{ r: RgbChannelVM; g: RgbChannelVM; b: RgbChannelVM }> | null;
  /** Legend text for each channel, e.g. "3.8 to 5.0 µm". */
  ranges: { r: string; g: string; b: string };
}

/** A catalogue source. `xy` has one entry per frame of vm.field.sequence: null when it is outside the image then. */
export interface MarkerVM {
  id: string;
  /** Short text beside the marker, or null. */
  label: string | null;
  xy: Array<{ x: number; y: number } | null>;
  /** True for a source that moves enough to show: draw its track through the frames. */
  fast: boolean;
}

export interface MarkersVM {
  /** "off": the reader hid markers. "unavailable": the catalogues could not be reached. */
  status: "off" | "loading" | "ready" | "unavailable";
  /** Why markers are missing, written for the reader, or null. */
  note: string | null;
  /**
   * While the markers drawn come from a recorded answer, not a live one: the caveat that says so,
   * with its date ("Catalogue markers were recorded on 14 Nov 2026."). Absent or null when live.
   */
  recorded?: string | null;
  /** Gaia DR3 stars at each frame's date: the open cross. */
  gaia: MarkerVM[];
  /** CatWISE neighbours: the diamond. */
  catwise: MarkerVM[];
  /** Where the catalogue says the object was: the dashed square, with its year. */
  was: { x: number; y: number; year: number } | null;
}

/** An older survey's image on this field's grid. Its brightness is never comparable with SPHEREx. */
export interface SurveyFrameVM {
  data: Float32Array;
  /** Its own scale. */
  limits: Limits | null;
  /** "WISE W2, 2010" */
  title: string;
  /** The real span of the observations, e.g. "May to Nov 2010". */
  dates: string;
}

export interface ThenAndNowVM {
  /** "none": this field has no older-survey image for the band on screen. */
  status: "ready" | "loading" | "none";
  /** Why there is nothing to show, written for the reader, or null. */
  note: string | null;
  older: SurveyFrameVM | null;
  /** The SPHEREx side: one stack of the paired band over every visit. */
  sphx: {
    data: Float32Array;
    limits: Limits | null;
    /** "SPHEREx 4.0–5.0 µm" */
    title: string;
    /** "82 exposures" */
    exposures: string;
    /** "May 2025 to May 2026" */
    dates: string;
  } | null;
}

export interface SpectrumPointVM {
  /** Wavelength, micrometres. */
  lam: number;
  /** Flux and its 1-sigma error, microjansky. */
  flux: number;
  err: number;
  /** Index into `visits`. */
  visit: number;
  /** Flagged data: drawn hollow. */
  flagged: boolean;
}

export interface SpectrumVM {
  /** The panel is open (the Spectrum button in the ring row is lit). */
  open: boolean;
  status: "closed" | "loading" | "ready" | "saturated" | "unavailable";
  /** State sentences, in the engine's words: saturated, indicative only, a neighbour nearby. */
  messages: string[];
  /** Visits in time order, at most five: one colour and one shape each. */
  visits: Array<{ label: string }>;
  /** One point per exposure. */
  points: SpectrumPointVM[];
  /** Binned points: drawn larger. */
  binned: SpectrumPointVM[];
  mode: "chart" | "table";
  /**
   * While the panel shows a recorded answer, not a live one: its chip, with the date it was
   * recorded ("Recorded 14 Nov 2026"). Null otherwise.
   */
  recorded: string | null;
}

export interface ExtrasVM {
  threeColour: ThreeColourVM;
  markers: MarkersVM;
  thenAndNow: ThenAndNowVM;
  spectrum: SpectrumVM;
  handlers: {
    /** Opens or closes the spectrum of the source under the ring. */
    toggleSpectrum(): void;
    setSpectrumMode(mode: "chart" | "table"): void;
    downloadCsv(): void;
  };
}
