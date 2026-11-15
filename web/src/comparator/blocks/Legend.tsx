/**
 * Legend (LANE: image): one line that keys whatever is drawn on or in the image.
 *
 * PORTS: Main.dc.html 341–346 (under the frame label); Phone.dc.html 192–197 (between the margin
 *        and the ring buttons).
 * FLAGS: catalogueMarkers (the dashed square with its year, the Gaia cross, the CatWISE diamond,
 *        a predicted track; or, when the catalogues could not be reached, the extras lane's
 *        sentence), threeColour (the three channels with their ranges).
 * STATES: the line keeps 18 px when empty. Items in order: "Your position" while the ring is
 *         drawn; "Where it was in {year}"; each catalogue overlay that is on, and the predicted
 *         track; "No data" whenever a hatched pixel can be on screen in ANY frame of the sequence;
 *         the three channels. Nothing in it depends on the frame on screen or on where the ring
 *         is, so it changes neither at a flip nor at a click on the sky.
 * USES: image/scene.ts legendOf (vm.image, vm.field, vm.extras).
 *         At 1280 and 1440 the catalogues' sentence is not repeated when the caveat list beside
 *         the image already carries it word for word.
 * FIT: the number of lines is measured (data-lines: "1", "2", or "3" for three or more), after
 *         every render and whenever the line's box changes size (a font arriving changes the
 *         wrap). At 1280 × 720 a second line takes the frame label's top margin and a third the
 *         16 px leading (image.css), so every item stays on screen with nothing dropped. It
 *         changes only with what is keyed, never at a flip.
 */
import "../image/image.css";
import { type RefObject, useLayoutEffect, useRef, useState } from "react";
import { legendOf } from "../image/scene";
import { caveatList } from "../time/rail";
import type { ViewModel } from "../vm";

/** True when the caveat list (beside the image at 1280 and 1440) already says this sentence. */
function listedBeside(vm: ViewModel, sentence: string): boolean {
  if (vm.layout !== "three" && vm.layout !== "wide") return false;
  return caveatList(vm.notices.caveats, vm.extras, {
    onScreen: vm.field !== null,
    catalogueMarkers: vm.features.catalogueMarkers,
  }).includes(sentence);
}

function Key({ kind, d }: { kind: string; d: string }) {
  return (
    <svg className="bc-key" viewBox="0 0 16 16" aria-hidden="true">
      <g className={`bc-mk bc-mk--${kind}`}>
        <path className="bc-mk__casing" d={d} />
        <path className="bc-mk__ink" d={d} />
      </g>
    </svg>
  );
}

/** Lines the items take: the distinct tops of the items, 1 to 3 ("3" stands for three or more). */
function linesOf(element: HTMLElement): number {
  const tops = new Set(
    [...element.children].map((child) => Math.round((child as HTMLElement).offsetTop)),
  );
  return Math.min(3, Math.max(1, tops.size));
}

/**
 * The legend's line count, measured after layout: after every render (the items changed) and
 * whenever the line's box changes size (a web font arriving or a wider column changes the wrap).
 * Never per frame: the items depend on the whole sequence.
 */
function useLines(ref: RefObject<HTMLDivElement | null>): number {
  const [lines, setLines] = useState(1);
  useLayoutEffect(() => {
    if (ref.current) setLines(linesOf(ref.current));
  });
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setLines(linesOf(element)));
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return lines;
}

export function Legend({ vm }: { vm: ViewModel }) {
  const legend = legendOf(vm);
  const markers = vm.features.catalogueMarkers;
  const note = legend.note && !listedBeside(vm, legend.note) ? legend.note : null;
  const ref = useRef<HTMLDivElement>(null);
  const lines = useLines(ref);

  return (
    <div ref={ref} className="bc-legend img-legend" data-lines={lines}>
      {legend.position && (
        <span className="bc-legend__item">
          <Key kind="position" d="M3 8a5 5 0 1 0 10 0a5 5 0 1 0 -10 0" />
          <span>Your position</span>
        </span>
      )}
      {markers && legend.was !== null && (
        <span className="bc-legend__item">
          <Key kind="was" d="M3 3H13V13H3Z" />
          <span>Where it was in {legend.was}</span>
        </span>
      )}
      {markers && legend.gaia && (
        <span className="bc-legend__item">
          <Key kind="gaia" d="M8 1.5V5.5M8 10.5V14.5M1.5 8H5.5M10.5 8H14.5" />
          <span>Gaia DR3</span>
        </span>
      )}
      {markers && legend.catwise && (
        <span className="bc-legend__item">
          <Key kind="catwise" d="M8 2L14 8L8 14L2 8Z" />
          <span>CatWISE</span>
        </span>
      )}
      {markers && legend.track && (
        <span className="bc-legend__item">
          <Key kind="track" d="M2 11L14 5M3.6 6.6L5.4 10.2M7.1 4.9L8.9 8.5M10.6 3.1L12.4 6.7" />
          <span>Predicted track</span>
        </span>
      )}
      {legend.noData && (
        <span className="bc-legend__item">
          <span className="bc-swatch bc-swatch--nodata" />
          <span>No data</span>
        </span>
      )}
      {vm.features.threeColour && legend.rgb && (
        <>
          <span className="bc-legend__item">
            <span className="bc-swatch bc-swatch--r" />
            <span>Red</span>
            <span className="bc-value">{legend.rgb.r}</span>
          </span>
          <span className="bc-legend__item">
            <span className="bc-swatch bc-swatch--g" />
            <span>Green</span>
            <span className="bc-value">{legend.rgb.g}</span>
          </span>
          <span className="bc-legend__item">
            <span className="bc-swatch bc-swatch--b3" />
            <span>Blue</span>
            <span className="bc-value">{legend.rgb.b}</span>
          </span>
        </>
      )}
      {markers && note && <span className="bc-legend__item img-legend__note">{note}</span>}
    </div>
  );
}
