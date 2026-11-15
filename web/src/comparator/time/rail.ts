/**
 * Pure helpers of the time lane (Search, notices, Playback, PairInfo, Timeline, Targets,
 * Caveats, FlipDock). No React and no DOM, so Vitest checks them in node.
 */
import type { ExtrasVM, ThenAndNowVM } from "../extras/types";
import type { Layout } from "../geometry";
import { type TargetId, targetById, targetPosition } from "../model";
import type { NoticesVM, PlaybackVM } from "../vm";

/** 1280 and 1440: the time rail of three columns. */
export function isThreeColumns(layout: Layout): boolean {
  return layout === "three" || layout === "wide";
}

/** Under 1280: the phone column (alone, or with the rail beside it). */
export function isColumn(layout: Layout): boolean {
  return layout === "phone" || layout === "rail";
}

// ------------------------------------------------------------------------------------- playback

export interface PlaybackParts {
  /** The flip key heads the block: at 1280 and 1440 only (the dock carries it below 1280). */
  flipKey: boolean;
  /** Play or Pause: never under reduced motion. */
  play: boolean;
  /** The speed slider: never under reduced motion. */
  speed: boolean;
  /** Ticks numbered 1 to 6 (phone and rail), or plain ticks (1280). */
  labelledTicks: boolean;
  /** The notes under the controls, in the board's order: reduced motion, then why it is greyed. */
  notes: string[];
}

export function playbackParts(
  layout: Layout,
  holdToFlip: boolean,
  playback: Pick<PlaybackVM, "enabled" | "why" | "reduced" | "reducedNote">,
): PlaybackParts {
  const notes: string[] = [];
  if (playback.reduced && playback.reducedNote) notes.push(playback.reducedNote);
  if (!playback.enabled && playback.why) notes.push(playback.why);
  return {
    flipKey: isThreeColumns(layout) && holdToFlip,
    play: !playback.reduced,
    speed: !playback.reduced,
    labelledTicks: !isThreeColumns(layout),
    notes,
  };
}

/** The six stops of the speed slider: 1 to 6 changes a second (blink-rate-max). */
export const SPEED_STOPS: readonly number[] = [1, 2, 3, 4, 5, 6];

/** The slider's value as a whole speed, or null for anything that is not one of the stops. */
export function speedFromInput(value: string): number | null {
  const speed = Number(value);
  return SPEED_STOPS.includes(speed) ? speed : null;
}

// ------------------------------------------------------------------------------------- timeline

/**
 * The row of the timeline to keep in view, as a position in `rows`: the chosen frame (the one on
 * screen in Blink when the flip key is up; the partner shown while it is held never moves the
 * list). Null when there is no such row.
 */
export function rowToKeep(rows: readonly { index: number }[], frame: number | null): number | null {
  if (frame === null) return null;
  const chosen = rows.findIndex((row) => row.index === frame);
  return chosen >= 0 ? chosen : null;
}

/**
 * What the timeline shows, as one string: the list is brought to its chosen row whenever this
 * changes (another build, band or view; playback starting or stopping), and never because only
 * the frame changed.
 */
export function listContext(parts: {
  key: string | null;
  band: string | null;
  view: string | null;
  rows: number;
  playing: boolean;
}): string {
  return [
    parts.key ?? "",
    parts.band ?? "",
    parts.view ?? "",
    String(parts.rows),
    parts.playing ? "playing" : "still",
  ].join("|");
}

/** Half a pixel: what rounding of fractional layout may leave over, never a reason to scroll. */
const SLACK_PX = 0.5;

/**
 * The scroll position that shows a whole row inside a scrolling list, moving as little as
 * possible, or null when the row is already in view (then nothing moves). `row.top` is measured
 * from the top of the list's content, like `scrollTop`.
 */
export function scrollToShow(
  view: { scrollTop: number; height: number },
  row: { top: number; height: number },
): number | null {
  if (!(view.height > 0) || !Number.isFinite(row.top) || !Number.isFinite(row.height)) return null;
  const top = Math.max(0, row.top);
  const bottom = row.top + row.height;
  if (top < view.scrollTop - SLACK_PX) return top;
  if (bottom > view.scrollTop + view.height + SLACK_PX) {
    // A row taller than the list shows its top.
    return row.height > view.height ? top : bottom - view.height;
  }
  return null;
}

// -------------------------------------------------------------------------------------- targets

/**
 * Where a target row links to, so that it also opens in a new tab: a recorded field's own address
 * (?target=…); for a target without one, the position the row opens a build at (model.ts
 * targetPosition: its catalogue position moved to the frames' epoch), written as the address bar
 * writes a position (url.ts writeLink). "#tb-targets" only if a target had no position at all.
 */
export function targetHref(id: TargetId): string {
  const target = targetById(id);
  if (target.recorded) return `?target=${target.recorded}`;
  const at = targetPosition(target);
  return at ? `?ra=${at.ra}&dec=${at.dec}` : "#tb-targets";
}

/** A plain click opens the target in place; a click with a modifier is the browser's (new tab). */
export function opensInPlace(click: {
  button: number;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}): boolean {
  return click.button === 0 && !click.metaKey && !click.ctrlKey && !click.shiftKey && !click.altKey;
}

// -------------------------------------------------------------------------------------- caveats

/**
 * Every sentence of the caveat list (CaveatList card), each once: the field's own caveats (the
 * manifest's warnings, written with dates), then why catalogue markers are missing, or, while the
 * markers drawn come from a recorded answer, the sentence that says so with its date. Transient
 * states (loading, markers the reader hid) are not caveats and never enter the list.
 *
 * What the engine says about the spectrum at the ring stays in the spectrum panel, which prints
 * it: repeated here it was on screen twice, made the list longer than the rail at 1280, and,
 * the list being a live region, was read out again each time the ring moved.
 */
export function caveatList(
  field: readonly string[],
  extras: Pick<ExtrasVM, "markers">,
  options: {
    onScreen: boolean;
    catalogueMarkers: boolean;
  },
): string[] {
  const out: string[] = [...field];
  // Recorded markers say so once, where the sentence for missing markers would stand (R4).
  if (options.onScreen && options.catalogueMarkers) {
    const markers = extras.markers;
    if (markers.recorded && markers.status === "ready") out.push(markers.recorded);
    if (markers.note !== null && (markers.status === "ready" || markers.status === "unavailable")) {
      out.push(markers.note);
    }
  }
  const seen = new Set<string>();
  const list: string[] = [];
  for (const sentence of out) {
    const text = sentence.trim();
    if (text === "" || seen.has(text)) continue;
    seen.add(text);
    list.push(text);
  }
  return list;
}

/**
 * Whether the phone and rail columns hold their notices block under the playback (Comparator
 * Column): for a mover notice that cannot jump, or for any sentence of the caveat list as the
 * Caveats block writes it, the field's own or the markers'. A field with no caveat of its own
 * still says why its markers are missing, or that the markers drawn were recorded (R4).
 */
export function columnHasNotices(
  notices: Pick<NoticesVM, "mover" | "caveats">,
  extras: Pick<ExtrasVM, "markers">,
  options: { onScreen: boolean; catalogueMarkers: boolean },
): boolean {
  if (notices.mover !== null && !notices.mover.canJump) return true;
  return caveatList(notices.caveats, extras, options).length > 0;
}

/**
 * Shown under the caveat list when the rail at 1280 has made it scroll: without it nothing on
 * screen says that a caveat is out of view (overlay scroll bars stay hidden until used). A new
 * string: the boards' caveat lists always fit.
 */
export const CAVEATS_CUT = "More caveats below: scroll the list.";

/**
 * True when a box that scrolls holds more than it shows. scrollHeight and clientHeight are whole
 * pixels, each rounded on its own, so one pixel of difference is rounding, not a hidden line.
 */
export function isCut(box: { scrollHeight: number; clientHeight: number }): boolean {
  return box.clientHeight > 0 && box.scrollHeight - box.clientHeight > 1;
}

// --------------------------------------------------------------------------------- then and now

export interface ThenAndNowLines {
  /** "Then: WISE W2, 2010", or null while no older image is there. */
  older: string | null;
  /** "Now: SPHEREx 4.0–5.0 µm, May 2025 to May 2026": the stack the other square shows, or null. */
  sphx: string | null;
  /** Why there is nothing to show, in the extras lane's words, or null. */
  why: string | null;
}

/**
 * The lines of the Then and now block (Main.dc.html 104–111). The SPHEREx square of Then and now
 * is one stack over every visit (extras/types.ts), not a frame chosen in the timeline, so the
 * "Now" line names that stack rather than "the SPHEREx frame chosen below".
 */
export function thenAndNowLines(view: ThenAndNowVM): ThenAndNowLines {
  const older = view.older;
  const sphx = view.sphx;
  return {
    older: older && older.title.trim() !== "" ? `Then: ${older.title.trim()}` : null,
    sphx:
      sphx && sphx.title.trim() !== ""
        ? `Now: ${[sphx.title.trim(), sphx.dates.trim()].filter((part) => part !== "").join(", ")}`
        : null,
    why: view.note !== null && view.note.trim() !== "" ? view.note.trim() : null,
  };
}
