/**
 * The spectrum panel's data: the engine's answer (contract section 7.1) turned into the visits,
 * points and messages the panel draws, and into the CSV file it hands over. Pure functions, no
 * DOM. Nothing here is ever invented: the panel shows only what the engine returned.
 *
 * Words are the design's (Handoff-copy, sections 11 and 15): "Saturated: no reliable
 * brightness", "Indicative only: the star's centre overflowed", "A neighbour 7.5″ away may
 * contaminate this" (the real distance), "No spectrum at this position yet.", "Measuring 120 of
 * 258".
 */
import type { Manifest, SpectrumResponse, TimeBin } from "../../contract";
import { ARCSEC, asSentence, fixedDateRange, shortDateRange } from "../format";
import type { SpectrumPointVM, SpectrumVM } from "./types";

/** One colour and one shape per visit: the series tokens hold five. */
export const MAX_VISITS = 5;

export const SATURATED = "Saturated: no reliable brightness";
export const INDICATIVE = "Indicative only: the star's centre overflowed";
export const NO_SPECTRUM = "No spectrum at this position yet.";

/** "A neighbour 7.5″ away may contaminate this", with the engine's distance. */
export function neighbourSentence(sepArcsec: number): string {
  return `A neighbour ${sepArcsec.toFixed(1)}${ARCSEC} away may contaminate this`;
}

/** "Measuring 120 of 258" when the engine gave counts, else "Measuring…". */
export function measuringSentence(done: number | null, total: number | null): string {
  return done !== null && total !== null && total > 0
    ? `Measuring ${done} of ${total}`
    : "Measuring…";
}

/** A visit of the spectrum: one time bin of the field. */
export interface SpectrumVisit {
  timeBin: number;
  /** ISO dates of the visit (the manifest's time bin, else the span of its points). */
  start: string;
  end: string;
  /** The legend's short form: "7–14 Nov 2025". */
  label: string;
  /** The table's fixed form: "07 Nov to 14 Nov 2025". */
  when: string;
}

export interface SpectrumRow {
  visit: number;
  kind: "exposure" | "binned";
  lam: number;
  flux: number;
  err: number;
  /** "good", "flagged" or "saturated" for an exposure; "binned" for a binned point. */
  quality: string;
  /** Exposures behind the point: 1, or the binned point's n. */
  n: number;
}

/** Everything the panel shows of one answer, in one place, so the chart, the table and the CSV agree. */
export interface SpectrumModel {
  state: SpectrumResponse["state"];
  target: { ra: number; dec: number };
  visits: SpectrumVisit[];
  /** Visits in the answer that the panel leaves out (only the five latest are drawn). */
  dropped: number;
  rows: SpectrumRow[];
  messages: string[];
}

const DAY_MS = 86_400_000;
/** MJD of 1970-01-01. */
const MJD_UNIX = 40587;

function isoOfMjd(mjd: number): string {
  return new Date((mjd - MJD_UNIX) * DAY_MS).toISOString().slice(0, 10);
}

const finite = (...values: number[]) => values.every((value) => Number.isFinite(value));

/**
 * The engine's X-Tombaugh-Incomplete header (contract 7.1, "<n> of <m> exposures not measured;
 * not cached") as a sentence for the reader: "12 of 258 exposures not measured." Null without it.
 */
export function incompleteSentence(header: string | null | undefined): string | null {
  const said = header?.replace(/;\s*not cached\s*$/i, "").trim();
  return said ? asSentence(said) : null;
}

/** The answer as the panel shows it: visits in time order (the five latest), rows, messages. */
export function spectrumModel(
  answer: SpectrumResponse & { incomplete?: string },
  manifest: Manifest,
): SpectrumModel {
  const bins = new Map<number, TimeBin>(manifest.time_bins.map((bin) => [bin.id, bin]));
  const mjds = new Map<number, number[]>();
  const note = (timeBin: number, mjd: number) => {
    const list = mjds.get(timeBin) ?? [];
    if (Number.isFinite(mjd)) list.push(mjd);
    mjds.set(timeBin, list);
  };
  const saturated = answer.state === "saturated";
  // The contract: "saturated" carries no points; never draw any that came anyway.
  const points = saturated ? [] : answer.points.filter((p) => finite(p.lam, p.flux_ujy, p.err_ujy));
  const binned = saturated ? [] : answer.binned.filter((p) => finite(p.lam, p.flux_ujy, p.err_ujy));
  for (const p of points) note(p.time_bin, p.mjd);
  for (const p of binned) note(p.time_bin, Number.NaN);

  const all = [...mjds.keys()].map((timeBin): SpectrumVisit & { order: number } => {
    const bin = bins.get(timeBin);
    const times = mjds.get(timeBin) ?? [];
    const start = bin?.date_start ?? (times.length ? isoOfMjd(Math.min(...times)) : null);
    const end = bin?.date_end ?? (times.length ? isoOfMjd(Math.max(...times)) : null);
    const order = bin?.mjd_mid ?? (times.length ? Math.min(...times) : Number.POSITIVE_INFINITY);
    return {
      timeBin,
      start: start ?? "",
      end: end ?? "",
      label: start && end ? shortDateRange(start, end) : "",
      when: start && end ? fixedDateRange(start, end) : "",
      order,
    };
  });
  // A visit with no date at all cannot be labelled: it is left out, never given a made-up name.
  const dated = all.filter((visit) => visit.start !== "").sort((a, b) => a.order - b.order);
  const kept = dated.slice(-MAX_VISITS);
  const index = new Map(kept.map((visit, i) => [visit.timeBin, i]));
  const visits: SpectrumVisit[] = kept.map(({ order: _order, ...visit }) => visit);

  const rows: SpectrumRow[] = [];
  for (const p of points) {
    const visit = index.get(p.time_bin);
    if (visit === undefined) continue;
    rows.push({
      visit,
      kind: "exposure",
      lam: p.lam,
      flux: p.flux_ujy,
      err: p.err_ujy,
      quality: p.quality,
      n: 1,
    });
  }
  for (const p of binned) {
    const visit = index.get(p.time_bin);
    if (visit === undefined) continue;
    rows.push({
      visit,
      kind: "binned",
      lam: p.lam,
      flux: p.flux_ujy,
      err: p.err_ujy,
      quality: "binned",
      n: p.n,
    });
  }
  rows.sort((a, b) => a.visit - b.visit || a.lam - b.lam || (a.kind === "binned" ? 1 : -1));

  const messages: string[] = [];
  if (answer.state === "saturated") messages.push(SATURATED);
  else if (answer.state === "indicative") messages.push(INDICATIVE);
  else if (answer.state === "contaminated") {
    const near = [...answer.neighbours]
      .filter((n) => Number.isFinite(n.sep_arcsec))
      .sort((a, b) => Number(a.fitted) - Number(b.fitted) || a.sep_arcsec - b.sep_arcsec)[0];
    // The contract says a neighbour lies within 15″; without its distance the sentence is not written.
    if (near) messages.push(neighbourSentence(near.sep_arcsec));
  }
  if (!saturated && rows.length === 0) messages.push(NO_SPECTRUM);
  // Some exposures could not be read this time: the spectrum is incomplete (and not cached).
  const incomplete = incompleteSentence(answer.incomplete);
  if (incomplete) messages.push(incomplete);
  const dropped = dated.length - kept.length;
  if (dropped > 0) {
    messages.push(`Showing the ${kept.length} latest of ${dated.length} visits.`);
  }
  return {
    state: answer.state,
    target: { ra: answer.target.ra, dec: answer.target.dec },
    visits,
    dropped,
    rows,
    messages,
  };
}

/** The panel's view of a model (whether the answer is live or recorded is the caller's to say). */
export function spectrumVM(
  model: SpectrumModel,
  mode: SpectrumVM["mode"],
): Omit<SpectrumVM, "open" | "recorded"> {
  const point = (row: SpectrumRow): SpectrumPointVM => ({
    lam: row.lam,
    flux: row.flux,
    err: row.err,
    visit: row.visit,
    flagged: row.kind === "exposure" && row.quality !== "good",
  });
  const status: SpectrumVM["status"] =
    model.state === "saturated" ? "saturated" : model.rows.length === 0 ? "unavailable" : "ready";
  return {
    status,
    messages: model.messages,
    visits: model.visits.map((visit) => ({ label: visit.label })),
    points: model.rows.filter((row) => row.kind === "exposure").map(point),
    binned: model.rows.filter((row) => row.kind === "binned").map(point),
    mode,
  };
}

const csvNumber = (value: number, digits: number) =>
  Number.isFinite(value) ? value.toFixed(digits) : "";

/**
 * The CSV of exactly the points the panel shows: one row per exposure and per binned point,
 * with the visit's dates and the measured position. Units in the header.
 */
export function spectrumCsv(model: SpectrumModel): string {
  const header = [
    "ra_deg",
    "dec_deg",
    "visit_start",
    "visit_end",
    "kind",
    "wavelength_um",
    "flux_ujy",
    "error_ujy",
    "quality",
    "n_exposures",
  ];
  const lines = [header.join(",")];
  for (const row of model.rows) {
    const visit = model.visits[row.visit];
    lines.push(
      [
        csvNumber(model.target.ra, 6),
        csvNumber(model.target.dec, 6),
        visit.start,
        visit.end,
        row.kind,
        csvNumber(row.lam, 4),
        csvNumber(row.flux, 3),
        csvNumber(row.err, 3),
        row.quality,
        String(row.n),
      ].join(","),
    );
  }
  return `${lines.join("\n")}\n`;
}

/**
 * "tombaugh-spectrum-133.75977_-7.24183.csv"; a recorded answer's file says so in its name, with
 * the UTC date it was recorded: "tombaugh-spectrum-133.75977_-7.24218-recorded-2026-11-14.csv".
 * The rows are the same either way.
 */
export function spectrumFileName(model: SpectrumModel, recordedAt: string | null = null): string {
  const { ra, dec } = model.target;
  const recorded = recordedAt ? `-recorded-${recordedAt.slice(0, 10)}` : "";
  return `tombaugh-spectrum-${ra.toFixed(5)}_${dec.toFixed(5)}${recorded}.csv`;
}
