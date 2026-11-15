# Chip

A short label that states a fact or a qualifier about the data, always visible without hovering.

| Kind | Class | Look |
|---|---|---|
| Qualifier | `bc-chip bc-chip--qualifier` | dashed outline, `color-text` label |
| Fact | `bc-chip` | solid outline |
| With a mark | add `<span class="bc-mark …">` | 8px square: full, half, empty or hatched |

**Sizes.** 24px high, padding `space-2`, radius `radius-1`, `text-micro` semibold. Chips do not wrap inside; a row of chips wraps as a whole (`bc-chips`).

**The qualifiers and exactly what they mean**

| Chip | Meaning | Where it appears |
|---|---|---|
| Live data | The image was built from the archive just now | App bar, with a full mark |
| Recorded field | The image is a stored copy, not a fresh build | App bar, dashed, with an empty mark |
| Partial frame | This frame has a different mix of wavelengths from the others | Frame label, timeline |
| Thin frame | Fewer than 8 exposures | Frame label, timeline |
| Saturated core | The centre of a star was too bright to measure | Frame label, target card, with the hatch mark |
| Indicative only | A number that shows direction, not a measurement | Spectrum panel |
| Unverified | Nobody has checked this against a second source | Beside a value, with an empty mark |
| Candidate | Something that may have moved or changed. The product never says "discovery". | Beside a detection |

Also: "Newest SPHEREx image: 5 Oct 2026" as a solid fact chip, with the date in Source Code Pro.

**Tags for where a number comes from:** Measured (full mark), From documents (half mark), Unverified (empty mark, dashed).

**Rules.** A qualifier reads as information: no warning icon, no colour, no exclamation mark. It is never hidden in a tooltip or behind a click. Chips are not buttons and have no hover state. Where a frame label can carry a chip, its row is reserved even when empty, so the label keeps its height from frame to frame.
