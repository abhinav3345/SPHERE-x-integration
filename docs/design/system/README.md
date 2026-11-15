A blink comparator for the infrared sky: type a position or a name and flip between images of that patch taken months apart. This system makes it feel like a precision instrument. It is one dark theme, two typefaces, and no interface colour at all.

## The rules that come from the science

These outrank taste. Check every screen against them.

1. **Nothing around the image moves when the frame changes.** Set every value that changes with the frame in Source Code Pro inside a fixed field (`bc-fixed`, `--bc-ch`), pad it to its longest form, and keep `font-variant-numeric: var(--numeric)` on `body`. Never change `font-weight` with state. The only things that change with a frame are the image, glyphs inside the frame label, one digit of the frame counter, and one 8px mark in the timeline.
2. **The surround is a true neutral.** The image sits on `color-surround` (the same value as `color-bg`, R = G = B) with at least `space-4` of it on every side. No tint, gradient, glow, texture or shadow anywhere near it. Keep lit fills small and never against the image edge.
3. **If it has a hue, it is data.** The interface uses only neutral tokens (`color-*`). Orange and blue mean earlier and later (`epoch-a`, `epoch-b`, `diff-*`, `series-*`). Green, pink and yellow are markers (`marker-*`). Red, green and blue are the three-colour channels (`channel-*`). Never use any of these for a button, link, chip, focus ring or error.
4. **Only the image flashes, and only when the reader starts it.** At most `blink-rate-max` (6) changes a second. No transitions, entrance effects, spinners, shimmer or parallax. State changes are instant (`feedback-duration` is 0ms). Under `prefers-reduced-motion`, frames change only by stepping or holding.
5. **Honesty is visible.** Every qualifier is a dashed chip that is on screen without hovering (see Chip). No-data pixels are hatched, never filled. A warning is never only behind a click. The product says "candidate", never "discovery".

## Colour

- Page and surround: `color-bg`. Panels and the rail: `color-surface`. Tooltips and hover: `color-surface-raised`.
- Text: `color-text` for anything the reader must read (16.9:1 on `color-bg`); `color-text-muted` for labels, notes and units (9.3:1). Both pass 7:1 on every ground. `color-text-disabled` is for disabled labels only.
- Lines: `color-line-strong` for anything that marks a control (4.3:1); `color-line` for dividers only.
- The accent is light itself: `color-accent` fills the one primary button and the selected option, with `color-on-accent` text. Do not introduce an accent hue. Amber in particular would sit beside "earlier" orange.
- Links are `color-text`, underlined.
- Errors and warnings use the `warning` icon, a `color-text` outline and words. There is no error colour.
- In a lit room, turn on Invert rather than switching theme: dark sources on a light field survive a projector better, and the surround stays the same.

## Type

- Interface: Source Sans 3 (`font-ui`), regular and semibold only. Sentence case everywhere. No all-caps labels, no letter-spacing, no italics.
- Values: Source Code Pro (`font-mono`), regular only, and only where a value changes between frames or aligns in a column: frame label, readout, coordinates, table cells, DOIs, axis numbers.
- Sizes: `text-title` 22, `text-body` 16, `text-readout` 18 (mono), `text-label` 14, `text-caption` 13, `text-micro` 12. Nothing is smaller than 12px. Inputs are 16px so phones do not zoom.
- Use the real glyphs: ′ and ″ for arcminutes and arcseconds, µ, ±, σ, λ, ×, and the true minus (−) in displayed numbers.
- Leave room for text about 30% longer: labels wrap, buttons and options grow in height, nothing truncates.

## Space, shape, edges

- Spacing: the 4px steps `space-1` to `space-7`, plus `space-half`. Gutter `size-gutter` (16px). Between groups `space-5`; between a label and its control `space-2`.
- Radii: `radius-0` for the image and anything that measures it; `radius-1` (2px) for controls; `radius-2` (4px) for panels and notices. Nothing is a pill or a circle except the position ring and the spotlight.
- Borders: 1px (`border-hair`). 2px (`border-strong`) means pressed, error, or the rule above a frame label.
- Focus: `outline: var(--focus-width) solid var(--color-focus)` with `outline-offset: var(--focus-gap)` on `:focus-visible`. On the image frame the ring is drawn just inside the edge.
- Elevation: none. Nothing casts a shadow. The two things that sit above the page (tooltip, copy confirmation) use `color-surface-raised` and a 1px `color-line-strong` outline.
- Targets: nothing pressable is smaller than `size-touch` (44px) in either direction.

## Layout

- Phone, 360 to 430px: one column. The image frame runs edge to edge; everything else keeps the 16px gutter. Under the image, in order: margin (scale bar, compass), readout, frame label, the flip key, transport, then the rest.
- Laptop: the same column, up to `size-column-max`, with an optional rail of `size-rail`.
- Projector, 1280 × 720: image at 476px (4×) with its label beneath, and two rails. See the two Proof cards.
- The image is always a whole number of device pixels per image pixel, never smoothed (see ImageFrame).

## Words

- Write from the reader's side, in plain sentence case: "Go to where it is now", "Hold to flip", "Same brightness scale for every frame".
- A message says what is true, then what to do: "The archive is not responding. Showing the recorded field instead."
- An error names the value and the allowed range: "Declination must be between −90 and +90 degrees."
- Give numbers with their units and no more precision than the data has: "Moved 4.4″ in six months."
- Say what is not known: "Motion not yet measured."
- No exclamation marks, no emoji, no "discovery", "stunning" or "explore the cosmos". Credit data sources in words; never use NASA or SPHEREx logos, insignia or patches.
- The name is plain text (see Wordmark) and lives in one place.

## Icons

Sixteen line icons on a 20px grid, 1.5px stroke (`icon-stroke`), square ends, drawn in `currentColor`. They are in the Icons asset group and in `Comparator.icons`. An icon-only button always has an accessible name. No other icon set, no emoji.

## The one bold idea

SPHEREx sees 102 infrared colours that no eye can see. The band selector shows them as an engraved rule of 102 ticks, 17 to a detector, with the chosen band lit (see BandSelector). It is the only expressive element in the system. Do not repeat it elsewhere, and do not ever colour it as a rainbow.

## What to build

The component list is long, but it comes down to thirteen things.

| Build this | It covers |
|---|---|
| Button | primary, secondary, quiet, icon-only, toggle, text link |
| Segmented | field of view, view switch, band options, chart or table |
| Toggle | invert |
| Slider | contrast, speed |
| Chip | the seven qualifiers, facts, tags |
| Notice | moved-object banner, warnings, state messages, progress |
| Tooltip, ShortcutHint, CopyLink | small helpers |
| DataTable | spectrum table, visits |
| SearchField | position or name |
| ImageFrame with FrameLabel | image, overlay, margin, readout, plate annotation |
| Timeline with Playback | frames, flip, step, play, speed |
| BandSelector | the wavelength rule |
| SpectrumPanel and TargetCard | spectrum, starting points |

Styles are in `components/bundle.css` (class prefix `bc-`), drawing helpers in `components/bundle.js` (`window.Comparator`, plain script, no dependencies). Both use tokens only. On this reference page Source Sans 3 loads from Google Fonts; the product must self-host its fonts, as set out under Hand-off.
