/**
 * The landing page, ported from docs/design/landing/Main.dc.html (and Phone.dc.html, the same page
 * at 390 wide). Every picture is a real SPHEREx frame (see pictures.ts); the flip timing and the
 * hold-to-flip logic are in flip.ts.
 */
import {
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
  useEffect,
  useId,
  useReducer,
  useSyncExternalStore,
} from "react";
import { COMPARATOR_PATH, REPO_URL, SITE_NAME } from "../site";
import {
  type Epoch,
  HERO_PERIOD_MS,
  heroLook,
  heroReducer,
  heroStart,
  holdReducer,
  holdShown,
  holdStart,
  isFlipKey,
  isHeld,
  nextCut,
} from "./flip";
import { FRAME_PX, HERO_PAIR, type Pair, pictureUrl, TRY_PAIR } from "./pictures";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

function reducedMotionNow(): boolean {
  try {
    return window.matchMedia(REDUCED_MOTION).matches;
  } catch {
    return false;
  }
}

function subscribeReducedMotion(onChange: () => void): () => void {
  try {
    const query = window.matchMedia(REDUCED_MOTION);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  } catch {
    return () => {};
  }
}

function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribeReducedMotion, reducedMotionNow, () => false);
}

export function Landing() {
  return (
    <div className="tb-root">
      <div className="tb-page">
        <Header />
        <main>
          <Hero />
          <HowItWorks />
          <Story />
          <Try />
          <Limits />
          <Final />
        </main>
        <Footer />
      </div>
      <div className="tb-grain" aria-hidden="true" />
    </div>
  );
}

function Header() {
  return (
    <header className="tb-nav">
      <div className="tb-nav-start">
        <a className="tb-name" href="#top">
          <span className="tb-mark" aria-hidden="true">
            <span className="tb-mark-a" />
            <span className="tb-mark-b" />
          </span>
          <span>{SITE_NAME}</span>
        </a>
        <nav className="tb-navlinks" aria-label="On this page">
          <a className="tb-navlink" href="#how">
            How it works
          </a>
          <a className="tb-navlink" href="#story">
            The 1930 trick
          </a>
          <a className="tb-navlink" href="#limits">
            Its limits
          </a>
        </nav>
      </div>
      <a className="tb-btn-s" href={COMPARATOR_PATH}>
        Look at the sky
      </a>
    </header>
  );
}

function Hero() {
  const reducedMotion = useReducedMotion();
  const [state, dispatch] = useReducer(heroReducer, undefined, () =>
    heroStart(!reducedMotionNow()),
  );
  const { playing, frame } = state;
  const look = heroLook(state, reducedMotion);

  // One timer per picture: it starts when the picture appears and asks for the other one.
  useEffect(() => {
    const cut = nextCut(playing, frame, HERO_PERIOD_MS);
    if (!cut) return;
    const timer = window.setTimeout(
      () => dispatch({ type: "show", frame: cut.frame }),
      cut.afterMs,
    );
    return () => window.clearTimeout(timer);
  }, [playing, frame]);

  // If the reader turns on reduced motion while it flips, it stops.
  useEffect(() => {
    if (reducedMotion) dispatch({ type: "pause" });
  }, [reducedMotion]);

  const period = { "--d": `${HERO_PERIOD_MS}ms` } as CSSProperties;

  return (
    <section
      id="top"
      className="tb-hero"
      data-light={look.light}
      data-pixel={look.pixel}
      data-playing={playing ? "" : undefined}
      style={period}
    >
      <div className="tb-hero-a">
        <h1 className="tb-h1">
          <span className="tb-line">Spot the</span> <span className="tb-line">difference</span>{" "}
          <span className="tb-line">
            in the sky
            <span className="tb-px" aria-hidden="true">
              <span className="tb-px-a" />
              <span className="tb-px-b" />
            </span>
          </span>
        </h1>
        <p className="tb-lead">
          Pick a spot. Flip between real pictures of it, taken months apart by NASA's SPHEREx space
          telescope. Anything that moved or changed jumps out.
        </p>
      </div>

      <Unit
        pair={HERO_PAIR}
        frame={look.frame}
        pressed={look.pressed}
        onPick={(picked) => dispatch({ type: "pick", frame: picked })}
        aura={
          <div className="tb-aura" aria-hidden="true">
            <div className="tb-glow tb-glow-a" />
            <div className="tb-glow tb-glow-b" />
            <div className="tb-spike tb-spike-v" />
            <div className="tb-spike tb-spike-h" />
          </div>
        }
        control={
          <button
            type="button"
            className="tb-iconbtn"
            aria-label={playing ? "Stop the pictures flipping" : "Flip the pictures automatically"}
            onClick={() => dispatch({ type: playing ? "pause" : "play" })}
          >
            {playing ? <PauseGlyph /> : <PlayGlyph />}
          </button>
        }
      >
        <p className="tb-note">
          The bright star in the middle is Barnard's Star. No star crosses our sky faster. Between
          these two pictures it moved north, and nothing else did.
        </p>
      </Unit>

      <div className="tb-hero-b">
        <div className="tb-ctas">
          <a className="tb-btn" href={COMPARATOR_PATH}>
            <span>Look at the sky</span>
            <ArrowGlyph />
          </a>
          <a className="tb-link" href="#how">
            See how it works
          </a>
        </div>
        <p className="tb-small">Free. No login. Works on your phone.</p>
      </div>
    </section>
  );
}

interface UnitProps {
  pair: Pair;
  /** The picture on screen. */
  frame: Epoch;
  /** The epoch button shown pressed, if any. */
  pressed: Epoch | null;
  onPick: (frame: Epoch) => void;
  /** The light behind the plate. */
  aura: ReactNode;
  /** A control at the end of the bar (the hero's play button). */
  control?: ReactNode;
  /** What sits under the bar: the hero's note, or the hold key. */
  children: ReactNode;
}

/**
 * Two real frames on a neutral plate, with the bar that names them and picks between them. The
 * figure takes its name from the object's name alone; the caption around it also holds the
 * controls, whose labels would otherwise run into the figure's name.
 */
function Unit({ pair, frame, pressed, onPick, aura, control, children }: UnitProps) {
  const nameId = useId();
  return (
    <figure className="tb-unit" data-frame={frame} aria-labelledby={nameId}>
      {aura}
      <div className="tb-lightbox">
        <img
          className="tb-frame tb-frame-a"
          src={pictureUrl(pair.a)}
          width={FRAME_PX}
          height={FRAME_PX}
          alt={pair.a.alt}
          draggable={false}
        />
        <img
          className="tb-frame tb-frame-b"
          src={pictureUrl(pair.b)}
          width={FRAME_PX}
          height={FRAME_PX}
          alt={pair.b.alt}
          draggable={false}
        />
      </div>
      <figcaption className="tb-capt">
        <div className="tb-bar">
          <span className="tb-bar-name" id={nameId}>
            {pair.name}
          </span>
          {/* biome-ignore lint/a11y/useSemanticElements: the design's group of two toggle buttons, not a form */}
          <div className="tb-epochs" role="group" aria-label="Which picture is showing">
            <EpochButton
              epoch="a"
              date={pair.a.date}
              which="the earlier picture"
              pressed={pressed === "a"}
              onPick={onPick}
            />
            <EpochButton
              epoch="b"
              date={pair.b.date}
              which="the later picture"
              pressed={pressed === "b"}
              onPick={onPick}
            />
          </div>
          {control}
        </div>
        {children}
      </figcaption>
    </figure>
  );
}

interface EpochButtonProps {
  epoch: Epoch;
  date: string;
  which: string;
  pressed: boolean;
  onPick: (frame: Epoch) => void;
}

/**
 * The design names each button "<date>, the earlier picture". The name is given as a label: the
 * design's visually hidden span is a separate block inside the flex button, and Chrome then puts a
 * stray space before the comma ("Aug 2025 , the earlier picture").
 */
function EpochButton({ epoch, date, which, pressed, onPick }: EpochButtonProps) {
  return (
    <button
      type="button"
      className="tb-epoch"
      aria-pressed={pressed}
      aria-label={`${date}, ${which}`}
      onClick={() => onPick(epoch)}
    >
      <span className={`tb-sw tb-sw-${epoch}`} aria-hidden="true">
        <span />
      </span>
      <span className="tb-mono">{date}</span>
    </button>
  );
}

function HowItWorks() {
  return (
    <section id="how" className="tb-sec">
      <h2 className="tb-h2">How it works</h2>
      <ol className="tb-steps">
        <li className="tb-step">
          <svg
            className="tb-glyph"
            viewBox="0 0 96 96"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="square"
            aria-hidden="true"
          >
            <circle cx="48" cy="48" r="22" />
            <path d="M48 8v14" />
            <path d="M48 74v14" />
            <path d="M8 48h14" />
            <path d="M74 48h14" />
            <rect x="44" y="44" width="8" height="8" fill="currentColor" stroke="none" />
          </svg>
          <div>
            <p className="tb-mono tb-step-n" aria-hidden="true">
              1
            </p>
            <h3 className="tb-h3">Pick a spot</h3>
            <p className="tb-text">
              Type a place in the sky or a name. Or start with a famous object, like Barnard's Star.
            </p>
          </div>
        </li>
        <li className="tb-step">
          <svg
            className="tb-glyph tb-glyph-frames"
            viewBox="0 0 96 96"
            fill="none"
            strokeWidth="1.5"
            strokeLinecap="square"
            aria-hidden="true"
          >
            <rect className="ga" x="14.75" y="30.75" width="50.5" height="50.5" />
            <rect className="gb" x="30.75" y="14.75" width="50.5" height="50.5" />
          </svg>
          <div>
            <p className="tb-mono tb-step-n" aria-hidden="true">
              2
            </p>
            <h3 className="tb-h3">Flip</h3>
            <p className="tb-text">
              Hold one key. The picture switches between two dates, months apart.
            </p>
          </div>
        </li>
        <li className="tb-step">
          <svg
            className="tb-glyph tb-glyph-dots"
            viewBox="0 0 96 96"
            fill="currentColor"
            stroke="none"
            aria-hidden="true"
          >
            <rect x="14" y="20" width="6" height="6" />
            <rect x="70" y="12" width="6" height="6" />
            <rect x="80" y="60" width="6" height="6" />
            <rect x="22" y="74" width="6" height="6" />
            <rect x="60" y="82" width="4" height="4" />
            <rect x="8" y="48" width="4" height="4" />
            <rect x="86" y="32" width="4" height="4" />
            <rect className="ga" x="38" y="48" width="10" height="10" />
            <rect className="gb" x="48" y="38" width="10" height="10" />
          </svg>
          <div>
            <p className="tb-mono tb-step-n" aria-hidden="true">
              3
            </p>
            <h3 className="tb-h3">See what jumps</h3>
            <p className="tb-text">
              Whatever stayed put looks frozen. Anything that moved or changed catches your eye.
            </p>
          </div>
        </li>
      </ol>
    </section>
  );
}

function Story() {
  return (
    <section id="story" className="tb-sec">
      <h2 className="tb-h2">The same trick found Pluto</h2>
      <div className="tb-eras">
        <div className="tb-era">
          <div className="tb-bloom tb-bloom-a" aria-hidden="true" />
          <p className="tb-era-tag">
            <span className="tb-swatch tb-swatch-a" aria-hidden="true" />
            <span>Earlier</span>
          </p>
          <p className="tb-era-word tb-era-word-a">1930</p>
          <p className="tb-era-text">
            Clyde Tombaugh flipped back and forth between two photographs of the same patch of sky,
            taken six nights apart. One faint dot jumped. It was Pluto.
          </p>
        </div>
        <div className="tb-era">
          <div className="tb-bloom tb-bloom-b" aria-hidden="true" />
          <p className="tb-era-tag">
            <span className="tb-swatch tb-swatch-b" aria-hidden="true" />
            <span>Later</span>
          </p>
          <p className="tb-era-word tb-era-word-b">Now</p>
          <p className="tb-era-text">
            You flip between two pictures from a space telescope, taken months apart. It is the same
            trick, and it is where this site gets its name.
          </p>
        </div>
      </div>
    </section>
  );
}

function Try() {
  const [hold, dispatch] = useReducer(holdReducer, holdStart);
  const shown = holdShown(hold);
  const held = isHeld(hold);

  // A hold also ends when the window loses focus or the page is hidden, wherever focus was.
  useEffect(() => {
    if (!held) return;
    const release = () => dispatch({ type: "blur" });
    window.addEventListener("blur", release);
    document.addEventListener("visibilitychange", release);
    return () => {
      window.removeEventListener("blur", release);
      document.removeEventListener("visibilitychange", release);
    };
  }, [held]);

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!isFlipKey(event.key)) return;
    // Space would also scroll the page.
    if (event.key !== "Enter") event.preventDefault();
    dispatch({ type: "keydown", key: event.key, repeat: event.repeat });
  };

  return (
    <section id="try" className="tb-sec">
      <div className="tb-try" data-light={shown}>
        <div className="tb-try-a">
          <p className="tb-kicker">Your turn</p>
          <h2 className="tb-h2 tb-h2-tight">Now a harder one</h2>
          <p className="tb-prose">
            This is WISE 0855−0714. It is a brown dwarf, too small to shine like a star, and the
            coldest one known. It is also one of the Sun's nearest neighbours.
          </p>
          <p className="tb-prose">
            Hold the key and watch the faint dot in the very middle. In six months it slid a little
            to the west, which is to the right.
          </p>
        </div>
        <Unit
          pair={TRY_PAIR}
          frame={shown}
          pressed={shown}
          onPick={(picked) => dispatch({ type: "choose", frame: picked })}
          aura={
            <div className="tb-aura" aria-hidden="true">
              <div className="tb-glow tb-glow-a" />
              <div className="tb-glow tb-glow-b" />
            </div>
          }
        >
          <button
            type="button"
            className="tb-key"
            onPointerDown={(event: PointerEvent<HTMLButtonElement>) =>
              dispatch({ type: "pointerdown", button: event.button })
            }
            onPointerUp={() => dispatch({ type: "pointerup" })}
            onPointerLeave={() => dispatch({ type: "pointerleave" })}
            onPointerCancel={() => dispatch({ type: "pointercancel" })}
            onBlur={() => dispatch({ type: "blur" })}
            onKeyDown={onKeyDown}
            onKeyUp={(event) => dispatch({ type: "keyup", key: event.key })}
            onContextMenu={(event) => event.preventDefault()}
          >
            Hold to flip
          </button>
        </Unit>
        <div className="tb-try-b">
          <a className="tb-link" href={COMPARATOR_PATH}>
            <span>Pick your own spot</span>
            <ArrowGlyph />
          </a>
        </div>
      </div>
    </section>
  );
}

function Limits() {
  return (
    <section id="limits" className="tb-sec">
      <h2 className="tb-h2 tb-h2-limits">
        It will not find <span className="tb-nowrap">Planet X.</span>
      </h2>
      <div className="tb-facts">
        <div className="tb-fact">
          <h3 className="tb-h3">What it shows</h3>
          <p className="tb-text">
            Nearby stars that move or change from one picture to the next. That is all it claims.
          </p>
        </div>
        <div className="tb-fact">
          <h3 className="tb-h3">Real pictures</h3>
          <p className="tb-text">
            Every image comes from SPHEREx, a NASA space telescope that photographs the whole sky
            every six months. They look small and coarse because that is what the telescope really
            sees.
          </p>
        </div>
        <div className="tb-fact">
          <h3 className="tb-h3 tb-h3-chips">Good to know</h3>
          <ul className="tb-chips">
            <li className="tb-chip">Free</li>
            <li className="tb-chip">No login</li>
            <li className="tb-chip">Works on a phone</li>
            <li className="tb-chip">Open source</li>
            <li className="tb-chip tb-chip-q">Not an official NASA product</li>
          </ul>
        </div>
      </div>
    </section>
  );
}

function Final() {
  return (
    <section className="tb-final">
      <div className="tb-aura" aria-hidden="true">
        <div className="tb-glow tb-glow-a" />
        <div className="tb-glow tb-glow-b" />
      </div>
      <h2 className="tb-h1">Go and look.</h2>
      <p className="tb-final-lead">Free. No login. Works on your phone.</p>
      <div className="tb-final-cta">
        <a className="tb-btn" href={COMPARATOR_PATH}>
          <span>Look at the sky</span>
          <ArrowGlyph />
        </a>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="tb-foot">
      <div className="tb-foot-a">
        <p className="tb-foot-name">{SITE_NAME}</p>
        <p className="tb-foot-note">
          Made by students at NASA Space Apps 2026 in Athlone, Ireland. Not an official NASA
          product.
        </p>
      </div>
      <div className="tb-foot-b">
        <p className="tb-foot-credit">Images: NASA's SPHEREx space telescope.</p>
        <a className="tb-link" href={REPO_URL}>
          Source code
        </a>
      </div>
    </footer>
  );
}

/* The design's own glyphs: 20px grid, 1.5px stroke, square ends, in currentColor. */

function ArrowGlyph() {
  return (
    <svg
      className="tb-arrow"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="square"
      aria-hidden="true"
    >
      <path d="M3.5 10h12" />
      <path d="M11 5.5l4.5 4.5-4.5 4.5" />
    </svg>
  );
}

function PauseGlyph() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="square"
      aria-hidden="true"
    >
      <path d="M7 4.5v11" />
      <path d="M13 4.5v11" />
    </svg>
  );
}

function PlayGlyph() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinejoin="miter"
      aria-hidden="true"
    >
      <path d="M6.5 4.5l8.5 5.5-8.5 5.5z" />
    </svg>
  );
}
