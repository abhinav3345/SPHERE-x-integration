# FrameLabel

The plate annotation under the image: which frame this is, set in fixed fields so that nothing moves when the frame changes.

**Anatomy, top to bottom**

1. A 2px rule in `color-text`. Dashed in `color-line-strong` for an image from another survey.
2. Chip row, 24px, reserved even when empty: Thin frame, Partial frame, Saturated core.
3. Date range in Source Code Pro at `text-readout` (18px): `31 Oct to 14 Nov 2025`. Days are two digits (`05 May`), so the field is always 21 characters.
4. Facts in Source Code Pro at `text-label`: wavelength range first (fixed length), then the exposure count right-aligned in three characters: `4.41 to 5.00 µm    19 exposures`.
5. Note in `text-caption`: "Resampled to 3.075″ per pixel; native pixel 6.15″".

**Why this order.** The caveat is read before the date. The fixed-length field comes first on its line so the left edge never changes. The count is the only field whose digits come and go, and it is right-aligned.

**What changes between frames:** the glyphs in the date, the count, and which chips are present. Nothing else: no height, no width, no line breaks.

| State | Look |
|---|---|
| Full frame | no chips |
| Thin frame | chip "Thin frame" |
| Partial frame | chip "Partial frame", and the wavelength field shows the mix this frame really has |
| Building | the date field reads "Building this image" |
| No frames | the date field reads "No frames here" |

**Survey label (Then and now).** Two labels side by side. The older survey: dashed rule, "WISE W2, 2010", chip "Its own brightness scale". SPHEREx: solid rule, "SPHEREx 4.0–5.0 µm", "82 exposures", "May 2025 to May 2026". The two images are never described as comparable in brightness.

**Keyboard.** Not interactive. Mark the container `aria-live="off"`: screen-reader users hear the frame from the timeline and the transport buttons, not at six changes a second.

**The consumer provides** the date range, exposure count, wavelength range and qualifiers of the frame on screen.
