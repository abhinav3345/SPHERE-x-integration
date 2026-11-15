/**
 * Playback (LANE: time).
 *
 * PORTS: Main.dc.html 53–75 (flip key first, transport, speed, notes; min-height 160px);
 *        Phone.dc.html 261–282 (transport, labelled speed ticks, notes; the flip key is the dock).
 * FLAGS: holdToFlip — at 1280/1440 the flip key is first in the block; when off the transport is
 *        first. On a phone and in the rail layout the key is never here (see FlipDock).
 * STATES: rendered in Blink only (vm.field === null or vm.field.view === "blink"): not in Side by
 *         side, Difference or Then and now. Greyed (vm.playback.enabled false) with
 *         vm.playback.why, also with one frame only. Under reduced motion (vm.playback.reduced)
 *         Play and Speed are NOT rendered and vm.playback.reducedNote is shown. Playing: Pause
 *         icon, aria-pressed, lit; the button keeps the one name "Play" (a toggle's name never
 *         changes with its state). The counter vm.playback.counter sits in a 14ch fixed field,
 *         right-aligned, and the speed value in a 12ch one, so nothing moves with the frame.
 * USES: vm.playback.*, vm.handlers.{step,togglePlay,setSpeed,flipKey}, vm.layout.
 * IDS: speed slider #tb-speed (range 1–6, step 1); output for="tb-speed" "2 per second".
 * KEYS: the flip key spreads vm.handlers.flipKey (pointer, blur, Space/Enter held, no menu).
 */
import { Icon } from "../../design/icons";
import { FlipKey } from "../time/FlipKey";
import { playbackParts, SPEED_STOPS, speedFromInput } from "../time/rail";
import "../time/time.css";
import type { ViewModel } from "../vm";

export function Playback({ vm }: { vm: ViewModel }) {
  if (vm.field && vm.field.view !== "blink") return null;
  const p = vm.playback;
  const parts = playbackParts(vm.layout, vm.features.holdToFlip, p);
  const off = !p.enabled;
  return (
    <div className="bc-playback tl-block">
      {parts.flipKey && <FlipKey vm={vm} />}
      <div className="bc-transport">
        <button
          className="bc-button bc-button--icon"
          type="button"
          aria-label="Previous frame"
          disabled={off}
          onClick={() => vm.handlers.step(-1)}
        >
          <Icon name="previous" />
        </button>
        {parts.play && (
          // A toggle keeps one name (WAI-ARIA button pattern): "Play", pressed while playing. The
          // board's name switched to "Pause" as well, which a screen reader read as "Pause,
          // pressed". The Pause icon and the lit look (aria-pressed) stay as designed.
          <button
            className="bc-button bc-button--icon"
            type="button"
            aria-label="Play"
            aria-pressed={p.playing}
            disabled={off}
            onClick={() => vm.handlers.togglePlay()}
          >
            <Icon name={p.playing ? "pause" : "play"} />
          </button>
        )}
        <button
          className="bc-button bc-button--icon"
          type="button"
          aria-label="Next frame"
          disabled={off}
          onClick={() => vm.handlers.step(1)}
        >
          <Icon name="next" />
        </button>
        <span className="bc-transport__count bc-fixed bc-fixed--end tl-count">{p.counter}</span>
      </div>
      {parts.speed && (
        <div className="bc-speed">
          <label htmlFor="tb-speed">Speed</label>
          <div>
            <input
              className="bc-slider"
              id="tb-speed"
              type="range"
              min={SPEED_STOPS[0]}
              max={SPEED_STOPS[SPEED_STOPS.length - 1]}
              step={1}
              value={p.speed}
              disabled={off}
              onChange={(event) => {
                const speed = speedFromInput(event.target.value);
                if (speed !== null) vm.handlers.setSpeed(speed);
              }}
            />
            <div
              className={parts.labelledTicks ? "bc-ticks bc-ticks--labelled" : "bc-ticks"}
              aria-hidden="true"
            >
              {SPEED_STOPS.map((stop) => (
                <span key={stop}>{parts.labelledTicks && <i>{stop}</i>}</span>
              ))}
            </div>
          </div>
          <output className="bc-fixed tl-speedvalue" htmlFor="tb-speed">
            {p.speedLabel}
          </output>
        </div>
      )}
      {parts.notes.map((note) => (
        <p key={note} className="bc-note">
          {note}
        </p>
      ))}
    </div>
  );
}
