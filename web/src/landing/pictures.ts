/**
 * The four real SPHEREx frames on the landing page. They live in web/public/landing, one PNG pixel
 * per image pixel, and web/public/landing/frames.json records where each came from (field, band,
 * dates, exposures, the shared brightness scale). pictures.test.ts checks these labels against it.
 * Words are the design's own (docs/design/landing/Main.dc.html).
 */

/** Every landing frame is 119 by 119 image pixels, shown only at whole multiples of that. */
export const FRAME_PX = 119;

export interface Picture {
  /** File name in web/public/landing. */
  file: string;
  /** Month and year, as the epoch button shows it. */
  date: string;
  alt: string;
}

export interface Pair {
  /** The object in the middle of the pictures. */
  name: string;
  /** The earlier picture. */
  a: Picture;
  /** The later picture. */
  b: Picture;
}

export function pictureUrl(picture: Picture): string {
  return `/landing/${picture.file}`;
}

/** The hero: Barnard's Star, about a year apart. */
export const HERO_PAIR: Pair = {
  name: "Barnard's Star",
  a: {
    file: "barnard-2025-08.png",
    date: "Aug 2025",
    alt: "Infrared picture of the sky around Barnard's Star, August 2025. One bright star sits in the middle of a field of fainter ones.",
  },
  b: {
    file: "barnard-2026-09.png",
    date: "Sep 2026",
    alt: "The same patch of sky in September 2026. The bright star in the middle sits a little further north.",
  },
};

/** "Now a harder one": WISE 0855−0714, six months apart, in the 4 to 5 µm band. */
export const TRY_PAIR: Pair = {
  name: "WISE 0855−0714",
  a: {
    file: "wise0855-2025-11.png",
    date: "Nov 2025",
    alt: "Infrared picture of the sky around WISE 0855−0714, November 2025. A field of faint stars with one faint dot in the very middle.",
  },
  b: {
    file: "wise0855-2026-05.png",
    date: "May 2026",
    alt: "The same patch of sky in May 2026. The faint dot in the middle sits slightly further west.",
  },
};
