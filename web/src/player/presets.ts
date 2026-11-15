/**
 * Typed access to docs/contract/presets.json, the single definition of detectors, wave bins
 * and presets (Contract v1.0 section 4). The JSON is copied to src/generated/ by
 * scripts/sync-contract.mjs; no preset is defined anywhere else.
 */
import type { WaveBin } from "../contract";
import presetsJson from "../generated/presets.json";

/** "uniform": every wave bin counts the same. "ivar": inverse-variance, maximum signal to noise. */
export type Weighting = "uniform" | "ivar";

/** Picks wave bins by detector (1..6), by wavelength range in µm, or both. */
export interface BinSelector {
  detectors?: number[];
  lam_min?: number;
  lam_max?: number;
}

interface PresetBase {
  id: string;
  label: string;
  short: string;
  note?: string;
}

/** A preset shown as one grey image. */
export interface MonoPreset extends PresetBase, BinSelector {
  kind: "mono";
}

/** A preset shown as three colour channels. */
export interface RgbPreset extends PresetBase {
  kind: "rgb";
  r: BinSelector;
  g: BinSelector;
  b: BinSelector;
}

export type Preset = MonoPreset | RgbPreset;

export interface DetectorRange {
  det: number;
  /** µm. */
  lam_min: number;
  /** µm. */
  lam_max: number;
}

export interface LegacyPair {
  mission: string;
  band: string;
  lam_min: number;
  lam_max: number;
  spherex_preset: string;
}

export interface PresetsFile {
  contract: string;
  sub_bins_per_detector: number;
  detectors: DetectorRange[];
  weighting: { default: Weighting; options: Weighting[] };
  presets: Preset[];
  legacy_pairs: LegacyPair[];
}

export const PRESETS_FILE = presetsJson as PresetsFile;
export const PRESETS: readonly Preset[] = PRESETS_FILE.presets;
export const DEFAULT_WEIGHTING: Weighting = PRESETS_FILE.weighting.default;

/** The older-survey bands, in the order of presets.json `legacy_pairs` (W1, W2, J, H, Ks). */
export const LEGACY_PAIRS: readonly LegacyPair[] = PRESETS_FILE.legacy_pairs;

/** The `legacy_pairs` entry of an older-survey band ("W1", "W2", "J", "H", "Ks"), or null. */
export function legacyPair(band: string | null): LegacyPair | null {
  return LEGACY_PAIRS.find((pair) => pair.band === band) ?? null;
}

/** The preset with this id; throws for an id presets.json does not define. */
export function getPreset(presetId: string): Preset {
  const preset = PRESETS.find((candidate) => candidate.id === presetId);
  if (!preset) throw new RangeError(`unknown preset "${presetId}"`);
  return preset;
}

/**
 * The 24 wave bins of the contract: each detector cut into equal sub-bins from blue to red,
 * with id = (detector - 1) * sub_bins_per_detector + sub. Wavelengths in µm.
 */
export function contractWaveBins(file: PresetsFile = PRESETS_FILE): WaveBin[] {
  const subBins = file.sub_bins_per_detector;
  return file.detectors.flatMap((detector) => {
    const width = (detector.lam_max - detector.lam_min) / subBins;
    return Array.from({ length: subBins }, (_, sub) => ({
      id: (detector.det - 1) * subBins + sub,
      detector: detector.det,
      lam_min: detector.lam_min + sub * width,
      lam_max: sub === subBins - 1 ? detector.lam_max : detector.lam_min + (sub + 1) * width,
    }));
  });
}
