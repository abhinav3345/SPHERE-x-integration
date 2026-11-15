/**
 * Keeps one row of a scrolling list in view (Timeline card: "It keeps the frame on screen in
 * view"). It scrolls only the list itself, never the page, at once and without animation, and
 * only when the row would otherwise be hidden: a list that is not cut short never moves.
 *
 * When it does that: whenever the list's context changes (another field, band or view, playback
 * starting or stopping: see `listContext` in rail.ts), and whenever the list itself changes
 * height (a notice above or below it came or went). Never in step with a frame change: then the
 * 8px mark is the only thing in the timeline that changes, so nothing beside the image moves
 * while the reader steps, holds or plays (rule 4 of the comparator).
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { scrollToShow } from "./rail";

/**
 * Returns the ref callback for the list. `position` is the row to keep in view, counted among the
 * list's children (null: none); `context` names what the list shows.
 */
export function useKeepInView(
  position: number | null,
  context: string,
): (element: HTMLElement | null) => void {
  const [list, setList] = useState<HTMLElement | null>(null);
  const positionRef = useRef(position);
  positionRef.current = position;
  const shownFor = useRef<{ list: HTMLElement; context: string } | null>(null);

  const show = useCallback(() => {
    const at = positionRef.current;
    if (!list || at === null) return;
    const row = list.children.item(at);
    if (!(row instanceof HTMLElement)) return;
    const listBox = list.getBoundingClientRect();
    const rowBox = row.getBoundingClientRect();
    const top = rowBox.top - listBox.top - list.clientTop + list.scrollTop;
    const next = scrollToShow(
      { scrollTop: list.scrollTop, height: list.clientHeight },
      { top, height: rowBox.height },
    );
    if (next !== null) list.scrollTop = next;
  }, [list]);

  // After a render with a new list or a new context, before the browser paints. A render caused
  // only by a frame change keeps the same context and scrolls nothing.
  useLayoutEffect(() => {
    if (!list) return;
    const last = shownFor.current;
    if (last !== null && last.list === list && last.context === context) return;
    shownFor.current = { list, context };
    show();
  });

  // Whenever the list changes height.
  useEffect(() => {
    if (!list || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => show());
    observer.observe(list);
    return () => observer.disconnect();
  }, [list, show]);

  return setList;
}
