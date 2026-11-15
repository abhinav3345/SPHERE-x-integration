# Segmented

One choice from a short set, shown as joined cells: field of view, view switch, band options, chart or table.

**Anatomy.** A `role="radiogroup"` with a visible label, holding `role="radio"` buttons. A cell has a name and, optionally, a second line in Source Code Pro (`bc-option__meta`) for a range.

```html
<span class="bc-group__label" id="fov">Field of view</span>
<div class="bc-segmented" role="radiogroup" aria-labelledby="fov">
  <button class="bc-option" type="button" role="radio" aria-checked="true">6′</button>
</div>
```

**Sizes.** Each cell is at least 44px high and takes an equal share of the width. One row by default. Add `bc-segmented--wrap` and `--bc-cols` to wrap into a grid: view switch is 2 × 2 on a phone and 4 × 1 on a laptop; band options are 3 × 3. Long labels wrap inside the cell and the whole row grows.

| State | Look |
|---|---|
| Default | 1px `color-line-strong` grid, no fill |
| Hover | `color-surface-raised` |
| Keyboard focus | focus ring on the cell |
| Pressed | `color-pressed` |
| Selected | lit: `color-accent` fill, `color-on-accent` text. Weight does not change. |
| Disabled | `aria-disabled="true"`, `color-text-disabled`, and a note under the group that says why |

**Keyboard.** One Tab stop for the group. Left and Right (or Up and Down) move and select, skipping disabled cells and wrapping at the ends. Home and End jump to the first and last. Space or Enter selects the focused cell.

**Content in this product**

- Field of view: 3′, 4′, 5′, 6′ (default), 8′, 10′
- View: Blink (default), Side by side, Difference, Then and now

**Do not** use it for more than nine options, for on and off (use Toggle), or for actions (use Button).
