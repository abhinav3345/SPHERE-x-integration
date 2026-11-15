/**
 * The address bar: what a copied link restores (Handoff-behaviour, "What a copied link
 * restores"). The system's five: position (or a recorded target), field of view, band, view and
 * frame. This design's four extras: the flip partner, the ring when it is off centre, the
 * spotlight, and whether the spectrum panel is open (`spec=1`, read only when the part is built).
 *
 *   ?target=wise0855&band=cold&frame=4&partner=2
 *   ?ra=133.7598&dec=-7.2422&fov=8&view=difference&frame=3&partner=1&ring=-41,3&spot=1&spec=1
 *
 * Frames are counted from 1 in time order, as on screen ("Frame 2 of 4"). A view or a band that
 * is unknown or not built in this version opens Blink, or the field's default band, with the rest
 * of the link honoured (Handoff-removable).
 */
import { FIXTURE_NAMES } from "../contract";
import { FEATURES, type Features } from "./features";
import {
  type Action,
  BAND_IDS,
  type BandId,
  bandBuilt,
  DEFAULT_FOV,
  FOVS,
  type Fov,
  type Offset,
  type Place,
  placeAt,
  RECORDED_CENTRES,
  RECORDED_FOV,
  type RecordedId,
  resolve,
  searchTextFor,
  type TargetId,
  targetOfRecorded,
  VIEW_IDS,
  type ViewId,
  type ViewState,
  viewBuilt,
} from "./model";

export interface LinkState {
  /** A recorded target, a position (no name: a link never carries free text), or none. */
  place: Place;
  fov: Fov;
  /** Null: the field's default band. */
  band: BandId | null;
  view: ViewId;
  /** 0-based index in the time-ordered sequence; null: the opening frame. */
  frame: number | null;
  /** 0-based; null: the default partner. */
  partner: number | null;
  /** Null: the ring is at the centre. */
  ring: Offset | null;
  spotlight: boolean;
  /** The spectrum panel is open. */
  spectrum: boolean;
}

export const EMPTY_LINK: LinkState = {
  place: { kind: "none" },
  fov: DEFAULT_FOV,
  band: null,
  view: "blink",
  frame: null,
  partner: null,
  ring: null,
  spotlight: false,
  spectrum: false,
};

/** The largest ring offset a link may carry: half of the 10′ frame (197 px). */
const MAX_OFFSET = 98;
/** Frames a link may name: far more than any field has. */
const MAX_FRAME = 999;

/** A finite decimal number written as such, or NaN. Rejects "", "1e3", "0x10", " 5". */
function decimal(text: string | null): number {
  if (text === null || !/^[-+]?(\d+(\.\d*)?|\.\d+)$/.test(text)) return Number.NaN;
  return Number(text);
}

function frameNumber(text: string | null): number | null {
  if (text === null || !/^\d{1,3}$/.test(text)) return null;
  const n = Number(text);
  return n >= 1 && n <= MAX_FRAME ? n - 1 : null;
}

function readPlace(params: URLSearchParams): Place {
  const target = params.get("target");
  if (target !== null) {
    return (FIXTURE_NAMES as readonly string[]).includes(target)
      ? { kind: "recorded", target: target as RecordedId }
      : { kind: "none" };
  }
  const ra = decimal(params.get("ra"));
  const dec = decimal(params.get("dec"));
  if (
    Number.isFinite(ra) &&
    Number.isFinite(dec) &&
    ra >= 0 &&
    ra < 360 &&
    dec >= -90 &&
    dec <= 90
  ) {
    return { kind: "position", ra, dec, name: null };
  }
  return { kind: "none" };
}

function readRing(text: string | null): Offset | null {
  const match = text === null ? null : /^(-?\d{1,3}),(-?\d{1,3})$/.exec(text);
  if (!match) return null;
  const dx = Number(match[1]);
  const dy = Number(match[2]);
  if (Math.abs(dx) > MAX_OFFSET || Math.abs(dy) > MAX_OFFSET) return null;
  return dx === 0 && dy === 0 ? null : { dx, dy };
}

/** Reads a query string ("?a=b" or "a=b"). Anything unusable falls back; nothing throws. */
export function readLink(search: string, features: Features = FEATURES): LinkState {
  const params = new URLSearchParams(search);
  const fovText = params.get("fov");
  const fov = FOVS.find((choice) => String(choice) === fovText) ?? DEFAULT_FOV;
  const bandText = params.get("band");
  const band = BAND_IDS.find((id) => id === bandText && bandBuilt(id, features)) ?? null;
  const viewText = params.get("view");
  const view = VIEW_IDS.find((id) => id === viewText && viewBuilt(id, features)) ?? "blink";
  const frame = frameNumber(params.get("frame"));
  const partner = frameNumber(params.get("partner"));
  return {
    place: readPlace(params),
    fov,
    band,
    view,
    frame,
    partner: partner !== null && partner !== frame ? partner : null,
    ring: readRing(params.get("ring")),
    spotlight: features.spotlight && params.get("spot") === "1",
    spectrum: features.spectrum && params.get("spec") === "1",
  };
}

/** Writes the link as a query string with its "?", or "" when there is nothing to restore. */
export function writeLink(link: LinkState): string {
  const params = new URLSearchParams();
  if (link.place.kind === "recorded") params.set("target", link.place.target);
  else if (link.place.kind === "position") {
    params.set("ra", String(link.place.ra));
    params.set("dec", String(link.place.dec));
  }
  if (link.fov !== DEFAULT_FOV) params.set("fov", String(link.fov));
  if (link.band !== null) params.set("band", link.band);
  if (link.view !== "blink") params.set("view", link.view);
  if (link.frame !== null) params.set("frame", String(link.frame + 1));
  if (link.partner !== null && link.partner !== link.frame) {
    params.set("partner", String(link.partner + 1));
  }
  if (link.ring && (link.ring.dx !== 0 || link.ring.dy !== 0)) {
    params.set("ring", `${link.ring.dx},${link.ring.dy}`);
  }
  if (link.spotlight) params.set("spot", "1");
  if (link.spectrum) params.set("spec", "1");
  const query = params.toString().replaceAll("%2C", ",");
  return query ? `?${query}` : "";
}

/**
 * The link of the screen as it is: the place asked for (also while the archive does not answer
 * and a recorded field stands in for it) and the band, view, pair, ring and spotlight in force.
 */
export function linkFromState(state: ViewState, features: Features = FEATURES): LinkState {
  const asked = state.request?.place ?? { kind: "none" };
  const place: Place =
    asked.kind === "position"
      ? { kind: "position", ra: asked.ra, dec: asked.dec, name: null }
      : asked;
  const standIn = state.load.phase === "ready" && state.load.fallback;
  const r = standIn ? null : resolve(state, features);
  const ringOff = state.ring.dx !== 0 || state.ring.dy !== 0;
  return {
    place,
    fov: state.fov,
    band: r ? r.band : state.band,
    view: r ? r.view : viewBuilt(state.view, features) ? state.view : "blink",
    frame: r ? r.pair.frame : state.frame,
    partner: r ? r.pair.partner : state.partner,
    ring: ringOff ? state.ring : null,
    spotlight: state.spotlight,
    spectrum: features.spectrum && state.spectrum,
  };
}

/**
 * The action that opens a link: a position at 6′ on a recorded centre opens the recorded copy. A
 * recorded target at another size (`?target=wise0855&fov=10`) means the same sky at that size: a
 * build of its centre, still that target's (its band), never the 6′ copy under a 10′ label.
 */
export function goFromLink(link: LinkState): Extract<Action, { type: "go" }> {
  let place: Place = link.place;
  let target: TargetId | null = null;
  if (link.place.kind === "position") {
    place = placeAt(link.place.ra, link.place.dec, link.fov, null);
  } else if (link.place.kind === "recorded" && link.fov !== RECORDED_FOV) {
    const own = targetOfRecorded(link.place.target);
    const centre = RECORDED_CENTRES[link.place.target];
    place = placeAt(centre.ra, centre.dec, link.fov, own.name);
    target = own.id;
  }
  return {
    type: "go",
    place,
    fov: link.fov,
    text: searchTextFor(place),
    band: link.band,
    frame: link.frame,
    partner: link.partner,
    ring: link.ring ?? undefined,
    spotlight: link.spotlight,
    spectrum: link.spectrum,
    ...(target ? { target } : {}),
  };
}
