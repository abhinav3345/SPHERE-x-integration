/**
 * Whether a box that scrolls holds more than it shows (rail.ts isCut), kept up to date as the
 * box or its content changes size: the caveat list at 1280 uses it to say that a caveat is out
 * of view. It reads sizes only when a size changes or `content` changes, never on a timer and
 * never in step with a frame change (the caveat list does not change with the frame).
 */
import { useEffect, useState } from "react";
import { isCut } from "./rail";

/**
 * Returns the ref callback for the box and whether it is cut. `active` false (a layout where
 * the box never scrolls) answers false and observes nothing; `content` names what the box
 * holds, so a new list is measured even when the box keeps its size.
 */
export function useCut(
  active: boolean,
  content: string,
): [(element: HTMLElement | null) => void, boolean] {
  const [box, setBox] = useState<HTMLElement | null>(null);
  const [cut, setCut] = useState(false);

  useEffect(() => {
    if (!active || !box || typeof ResizeObserver === "undefined") {
      setCut(false);
      return;
    }
    // `content` is read so that a new list is measured again even when no size changes.
    void content;
    const check = () => setCut(isCut(box));
    const observer = new ResizeObserver(check);
    observer.observe(box);
    for (const child of box.children) observer.observe(child);
    check();
    return () => observer.disconnect();
  }, [active, box, content]);

  return [setBox, cut];
}
