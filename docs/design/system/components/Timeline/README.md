# Timeline

The list of frames at this position, oldest first, with the one on screen marked.

**Anatomy.** An ordered list of buttons (`bc-visit`). Each row: an 8px mark, the date range in Source Code Pro, and the exposure count, right-aligned. Rows are 44px high and divided by `color-line` hairlines.

| Row | Look |
|---|---|
| SPHEREx visit | `31 Oct–14 Nov 2025` · `19 exposures` |
| Current | the mark is filled, and `aria-current="true"`. Nothing else about the row changes. |
| Thin or partial | date in `color-text-muted`, and the word after the count: `4 exposures, thin` |
| Other survey | dashed divider, dashed mark, name in Source Sans 3 semibold (`WISE, 2010`, `2MASS, 1999`), and the words "Other survey" |

| State | Look |
|---|---|
| Default | as above |
| Hover | `color-surface-raised` |
| Keyboard focus | focus ring |
| Pressed | `color-pressed` |
| Disabled | `color-text-disabled`: a frame that failed to build, with the reason after the count |

**Why only the mark changes.** At up to six changes a second, a row that lit up would flash beside the image. The mark is 8 × 8px.

**Keyboard.** Each row is a button: Tab to it, Enter or Space shows that frame and stops playback. Left and Right arrows step frames from anywhere outside a text field.

**Rules.** Thin and partial frames stay in the sequence; they are labelled, not removed. Other surveys are never mixed into the SPHEREx blink without their label, and their brightness is never compared. Dates here use the short form (`5–6 May 2025`) because rows do not change in place; the frame label uses the fixed form.

**Example content.** 2MASS, 1999 · WISE, 2010 · 5–6 May 2025 (4 exposures, thin) · 31 Oct–14 Nov 2025 (19) · 11–13 Dec 2025 (3, thin) · 21 Apr–14 May 2026 (21).
