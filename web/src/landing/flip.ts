/**
 * The landing page's two flipping pictures (docs/design/landing/Main.dc.html): the hero pair that
 * flips on its own until the reader stops it, and the "Now a harder one" pair that flips while the
 * reader holds the key. Pure: no DOM and no clock. Landing.tsx feeds in events and runs the timer
 * that nextCut asks for.
 */

/** The two pictures of a pair: "a" is the earlier one, "b" the later one. */
export type Epoch = "a" | "b";

/** The other picture of the pair. */
export function other(epoch: Epoch): Epoch {
  return epoch === "a" ? "b" : "a";
}

/** The design's three speeds, each the time for one full cycle through the pair. */
export const FLIP_PERIOD_MS = { slow: 3600, steady: 2400, quick: 1600 } as const;

/** The hero flips at the design's default speed: 2.4 s for the pair, 1.2 s on each picture. */
export const HERO_PERIOD_MS: number = FLIP_PERIOD_MS.steady;

/** Nothing on this site changes a picture more than six times a second. */
export const MAX_CHANGES_PER_SECOND = 6;

/** The shortest time a picture may stay up. */
export const MIN_DWELL_MS = 1000 / MAX_CHANGES_PER_SECOND;

/** How long each picture stays up: half the period, and never less than MIN_DWELL_MS. */
export function dwellMs(periodMs: number): number {
  const half = periodMs / 2;
  return Number.isFinite(half) && half > MIN_DWELL_MS ? half : MIN_DWELL_MS;
}

/* The hero pair ------------------------------------------------------------------------------- */

/** What lights the hero when it is still: one picture's colour, or both (before anything ran). */
export type Light = Epoch | "both";

export interface HeroState {
  playing: boolean;
  /** The picture on screen. */
  frame: Epoch;
  /** The light while still. While playing, the light follows the frame (see heroLook). */
  still: Light;
}

export type HeroAction =
  /** The play button, or the page opening when it may flip on its own. */
  | { type: "play" }
  /** The pause button: stop on the picture that is showing. */
  | { type: "pause" }
  /** An epoch button: show that picture and stop. */
  | { type: "pick"; frame: Epoch }
  /** The flipping clock changes the picture. Ignored once the reader has stopped it. */
  | { type: "show"; frame: Epoch };

/** The hero as the page opens: flipping on its own, unless the reader asked for reduced motion. */
export function heroStart(autoplay: boolean): HeroState {
  return { playing: autoplay, frame: "a", still: "both" };
}

export function heroReducer(state: HeroState, action: HeroAction): HeroState {
  switch (action.type) {
    case "play":
      return state.playing ? state : { ...state, playing: true };
    case "pause":
      return state.playing ? { playing: false, frame: state.frame, still: state.frame } : state;
    case "pick":
      return { playing: false, frame: action.frame, still: action.frame };
    case "show":
      return state.playing && state.frame !== action.frame
        ? { ...state, frame: action.frame }
        : state;
  }
}

export interface Cut {
  /** The picture to show next. */
  frame: Epoch;
  /** How long the picture on screen stays up first. */
  afterMs: number;
}

/**
 * The next change of picture while the hero flips, or null while it is still. The timer for it
 * starts when the picture on screen appeared, so every picture stays up a full dwell and a late or
 * throttled timer can only slow the flipping, never bunch the changes up.
 */
export function nextCut(playing: boolean, frame: Epoch, periodMs: number): Cut | null {
  return playing ? { frame: other(frame), afterMs: dwellMs(periodMs) } : null;
}

export interface HeroLook {
  /** The picture on screen, and the lit mark under it. */
  frame: Epoch;
  /** The two-colour pixel after the headline. */
  pixel: Light;
  /** The light behind the picture. Under reduced motion it holds still while the pictures flip. */
  light: Light;
  /** The epoch button shown pressed: none while flipping. */
  pressed: Epoch | null;
}

export function heroLook(state: HeroState, reducedMotion: boolean): HeroLook {
  if (state.playing) {
    return {
      frame: state.frame,
      pixel: state.frame,
      light: reducedMotion ? "both" : state.frame,
      pressed: null,
    };
  }
  return { frame: state.frame, pixel: state.still, light: state.still, pressed: state.frame };
}

/* The hold-to-flip pair ----------------------------------------------------------------------- */

export interface HoldState {
  /** The resting picture, chosen with the epoch buttons. */
  base: Epoch;
  /** A pointer is down on the key. */
  pointer: boolean;
  /** Space or Enter is down on the key. */
  key: boolean;
}

export type HoldEvent =
  | { type: "choose"; frame: Epoch }
  | { type: "pointerdown"; button: number }
  | { type: "pointerup" }
  | { type: "pointerleave" }
  | { type: "pointercancel" }
  | { type: "keydown"; key: string; repeat: boolean }
  | { type: "keyup"; key: string }
  /** The key lost focus, or the window did. */
  | { type: "blur" };

export const holdStart: HoldState = { base: "a", pointer: false, key: false };

/** Space and Enter hold the key, as they press any button. */
export function isFlipKey(key: string): boolean {
  return key === " " || key === "Spacebar" || key === "Enter";
}

export function isHeld(state: HoldState): boolean {
  return state.pointer || state.key;
}

/** While the key is held the other picture shows; on release the resting one returns. */
export function holdShown(state: HoldState): Epoch {
  return isHeld(state) ? other(state.base) : state.base;
}

function release(state: HoldState, pointer: boolean, key: boolean): HoldState {
  const next = { base: state.base, pointer: state.pointer && !pointer, key: state.key && !key };
  return next.pointer === state.pointer && next.key === state.key ? state : next;
}

export function holdReducer(state: HoldState, event: HoldEvent): HoldState {
  switch (event.type) {
    case "choose":
      return { base: event.frame, pointer: false, key: false };
    case "pointerdown":
      // Only the main button (or a touch or pen contact) holds the key.
      return event.button === 0 && !state.pointer ? { ...state, pointer: true } : state;
    case "pointerup":
    case "pointerleave":
    case "pointercancel":
      return release(state, true, false);
    case "keydown":
      // Key repeat is not a new press.
      return isFlipKey(event.key) && !event.repeat && !state.key ? { ...state, key: true } : state;
    case "keyup":
      return isFlipKey(event.key) ? release(state, false, true) : state;
    case "blur":
      return release(state, true, true);
  }
}
