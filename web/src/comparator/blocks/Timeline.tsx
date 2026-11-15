/**
 * Timeline (LANE: time).
 *
 * PORTS: Main.dc.html 113–127 (header with the chip, the list, the key line);
 *        Phone.dc.html 411–425.
 * FLAGS: sideBySide/difference — rows carry the A and B epoch tags (row.tag) in those views.
 *        thenAndNow — nothing: the timeline holds SPHEREx visits only (Handoff-behaviour, where
 *        this design departs: another survey appears only in Then and now).
 * STATES: rows (vm.timeline.rows), oldest first: when (short form), count with qualifiers, greyed
 *         and labelled when row.qualified (bc-visit--qualified), aria-current on row.current
 *         (Blink only: only the 8px mark changes with the frame), disabled when row.disabled
 *         (Difference). Newest chip "Newest SPHEREx image: <vm.timeline.newest>" only when
 *         non-null. Key line vm.timeline.key. Choosing a row shows that frame, stops playback and
 *         makes the replaced frame the flip partner (vm.handlers.pickFrame, through the gate).
 *         At 1280 this is the part of the time rail that shrinks first and scrolls (time.css),
 *         never below two rows (one when the field has a single frame: tl-list--one), and it
 *         keeps the chosen frame's row in view (time/useKeepInView.ts): the list scrolls only
 *         when that row would be hidden, and only when the list itself changes (field, band,
 *         view, its height, playback starting or stopping), never in step with a frame change,
 *         so the 8px mark stays the only thing that changes with the frame. No rows (nothing on
 *         screen): not rendered. The visits found while building are not in the ViewModel, so
 *         they are not drawn.
 * USES: vm.timeline.*, vm.field.pair, vm.handlers.pickFrame(index).
 * IDS: label #tb-frames (aria-labelledby of the list).
 */
import "../time/time.css";
import { listContext, rowToKeep } from "../time/rail";
import { useKeepInView } from "../time/useKeepInView";
import type { ViewModel } from "../vm";

export function Timeline({ vm }: { vm: ViewModel }) {
  const { rows, key, newest } = vm.timeline;
  const field = vm.field;
  const listRef = useKeepInView(
    rowToKeep(rows, field?.pair.frame ?? null),
    listContext({
      key: field?.manifest.key ?? null,
      band: field?.band ?? null,
      view: field?.view ?? null,
      rows: rows.length,
      playing: vm.playback.playing,
    }),
  );
  if (rows.length === 0) return null;
  return (
    <div className="tl-frames">
      <div className="tl-frames__head">
        <span className="bc-group__label" id="tb-frames">
          Frames
        </span>
        {newest !== null && (
          <span className="bc-chip">
            Newest SPHEREx image: <span className="bc-value">{newest}</span>
          </span>
        )}
      </div>
      <ol
        className={rows.length < 2 ? "bc-timeline tl-list--one" : "bc-timeline"}
        aria-labelledby="tb-frames"
        ref={listRef}
      >
        {rows.map((row) => (
          <li key={row.index}>
            <button
              className={row.qualified ? "bc-visit bc-visit--qualified" : "bc-visit"}
              type="button"
              aria-current={row.current ? "true" : undefined}
              disabled={row.disabled}
              onClick={() => vm.handlers.pickFrame(row.index)}
            >
              <span className="bc-mark" />
              <span className="bc-visit__when">
                {row.tag !== null && (
                  <span className="bc-epochtag tl-tag">
                    <span
                      className={
                        row.tag === "A" ? "bc-swatch bc-swatch--a" : "bc-swatch bc-swatch--b"
                      }
                    />
                    {row.tag}
                  </span>
                )}
                <span className="tl-when">{row.when}</span>
              </span>
              <span className="bc-visit__count">{row.count}</span>
            </button>
          </li>
        ))}
      </ol>
      {key !== "" && <p className="bc-note">{key}</p>}
    </div>
  );
}
