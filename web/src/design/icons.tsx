/**
 * The sixteen line icons of the Tombaugh design system: 20px grid, 1.5px stroke, square ends,
 * drawn in currentColor (docs/design/system/components/Icons/README.md). Styled by `.bc-icon`
 * in components.css. No other icon set and no emoji.
 */
import type { ReactNode } from "react";

export type IconName =
  | "play"
  | "pause"
  | "previous"
  | "next"
  | "flip"
  | "side-by-side"
  | "difference"
  | "invert"
  | "contrast"
  | "zoom"
  | "recentre"
  | "copy-link"
  | "information"
  | "warning"
  | "external-link"
  | "close";

const solid = "bc-icon__solid";

const PATHS: Record<IconName, ReactNode> = {
  play: <path d="M6.5 4.5v11l9-5.5z" />,
  pause: <path d="M6 4.5h2.5v11H6zM11.5 4.5H14v11h-2.5z" />,
  previous: (
    <>
      <path d="M5 4.5v11" />
      <path d="M15 4.5v11L7.5 10z" />
    </>
  ),
  next: (
    <>
      <path d="M15 4.5v11" />
      <path d="M5 4.5v11l7.5-5.5z" />
    </>
  ),
  flip: (
    <>
      <path d="M3.5 7h12" />
      <path d="M12.5 4l3 3-3 3" />
      <path d="M16.5 13h-12" />
      <path d="M7.5 10l-3 3 3 3" />
    </>
  ),
  "side-by-side": <path d="M3 4.5h6v11H3zM11 4.5h6v11h-6z" />,
  difference: (
    <>
      <circle cx="7.5" cy="10" r="5" />
      <circle cx="12.5" cy="10" r="5" />
    </>
  ),
  invert: (
    <>
      <path d="M3.5 3.5h13v13h-13z" />
      <path className={solid} d="M16.5 3.5v13h-13z" />
    </>
  ),
  contrast: (
    <>
      <circle cx="10" cy="10" r="6.5" />
      <path className={solid} d="M10 3.5a6.5 6.5 0 0 1 0 13z" />
    </>
  ),
  zoom: (
    <>
      <circle cx="8.5" cy="8.5" r="5" />
      <path d="M12.5 12.5l4.5 4.5" />
    </>
  ),
  recentre: (
    <>
      <circle cx="10" cy="10" r="4.5" />
      <path d="M10 2v3.5M10 14.5V18M2 10h3.5M14.5 10H18" />
      <circle className={solid} cx="10" cy="10" r="1" />
    </>
  ),
  "copy-link": (
    <>
      <path d="M8.6 11.4a3 3 0 0 0 4.2 0l2.6-2.6a3 3 0 0 0-4.2-4.2l-1 1" />
      <path d="M11.4 8.6a3 3 0 0 0-4.2 0l-2.6 2.6a3 3 0 0 0 4.2 4.2l1-1" />
    </>
  ),
  information: (
    <>
      <circle cx="10" cy="10" r="7" />
      <path d="M10 9v5" />
      <circle className={solid} cx="10" cy="6.3" r="0.9" />
    </>
  ),
  warning: (
    <>
      <path d="M10 3l7.5 13.5h-15z" />
      <path d="M10 8v4" />
      <circle className={solid} cx="10" cy="14.2" r="0.9" />
    </>
  ),
  "external-link": (
    <>
      <path d="M8 4.5H4.5v11h11V12" />
      <path d="M11 3.5h5.5V9" />
      <path d="M16.5 3.5l-7 7" />
    </>
  ),
  close: <path d="M5 5l10 10M15 5L5 15" />,
};

/** One icon. With `label` it is an image with that name; without, it is hidden from assistive tech. */
export function Icon({ name, label }: { name: IconName; label?: string }) {
  return label ? (
    <svg className="bc-icon" viewBox="0 0 20 20" focusable="false" role="img" aria-label={label}>
      {PATHS[name]}
    </svg>
  ) : (
    <svg className="bc-icon" viewBox="0 0 20 20" focusable="false" aria-hidden="true">
      {PATHS[name]}
    </svg>
  );
}
