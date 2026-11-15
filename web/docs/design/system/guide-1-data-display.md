# Data display

One rule sits over everything here: **time has one colour axis.** Earlier is orange, later is blue, in the difference image, the two-epoch composite and the spectrum. Nothing else in the product is orange or blue.

| What is shown | Encoding | Tokens | Legend that must be on screen |
|---|---|---|---|
| A frame (Blink, Side by side, Then and now) | Linear grey ramp, one stretch for the whole sequence | `ramp-black`, `ramp-white` | The note "Same brightness scale for every frame" |
| Inverted frame | The same ramp reversed | the same | Invert reads "On" |
| Pixels with no data | 45° hatch in two greys, identical in every view | `nodata-a`, `nodata-b`, `hatch-stripe` | "No data" with the hatch swatch |
| Difference | Diverging scale through a dark neutral, later minus earlier, ±5σ | `diff-earlier-5` … `diff-zero` … `diff-later-5` | "Brighter earlier" to "Brighter later", in units of noise (σ) |
| Two-epoch composite | Earlier in orange, later in blue, unchanged in neutral | `epoch-a`, `epoch-b` | A and B with their swatches and dates |
| Three-colour | Three wavelength ranges as red, green, blue | `channel-r`, `channel-g`, `channel-b` | Red 3.8 to 5.0 µm, green 1.6 to 3.8 µm, blue 0.74 to 1.65 µm |
| Spectrum | One colour and one shape per visit, in time order | `series-1` … `series-5` | Visit dates, "Larger: binned", "Hollow: flagged" |
| Markers | Shape first, colour second, black casing under every stroke | `marker-position`, `marker-gaia`, `marker-catwise`, `marker-was`, `marker-casing` | The marker key |
| Spotlight | Everything outside a circle dimmed, still visible | `spotlight-dim` | None |
| Orientation and scale | Compass and scale bar in the margin under the image | `color-text` | N, E, and the length in arcseconds |

## Rules for every view

- Draw each image pixel as a whole number of device pixels, with smoothing off. Smoothing can fake motion.
- Use one brightness stretch for all frames in a sequence. A per-frame stretch makes steady sources appear to change.
- Never remove a legend to save space. If a view is on, its legend is on.
- Never tell two things apart by colour alone: visits have shapes, markers have shapes, channels have letters, A and B have letters.
- The image is 119 × 119 pixels by default and at most 197 × 197. Real frames go wherever the reference cards show a flat block labelled "real frame, 119 × 119 px". Do not draw, generate or borrow sky imagery for mock-ups.

## Colour-blind check

Colours were run through simulated protanopia, deuteranopia and tritanopia (Machado, Oliveira and Fernandes 2009) and compared in OKLab.

- The two difference arms stay apart at every step under all three: the closest pair is the 1σ step, as intended for noise.
- The five spectrum colours stay apart from each other under all three. Adjacent visits are the closest pairs, which is why each visit also has its own shape.
- The marker green and yellow come close under red-green colour blindness, as do marker pink and "later" blue. Their shapes differ (open cross, dashed square, diamond), so shape is the rule and colour the second cue.

See the cards in the Data display group for each legend and its exact markup.
