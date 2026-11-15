# Button

A pressable label: primary, secondary, quiet or icon-only, plus the text link.

**Anatomy.** Optional icon (20px), label, optional shortcut key. `gap: space-2`.

| Variant | Class | Use |
|---|---|---|
| Primary | `bc-button bc-button--primary` | The one next step on screen. At most one lit button per view. |
| Secondary | `bc-button` | Everything else. The default. |
| Quiet | `bc-button bc-button--quiet` | Low-priority actions in a bar, such as Copy link |
| Icon-only | `bc-button bc-button--icon` | Transport and tools. 44 × 44px. Needs `aria-label`. |
| Toggle | add `aria-pressed` | Play and pause. Lit while pressed in. |
| Text link | `bc-link` | Navigation and references. Always underlined, never coloured. Add `bc-link--target` when the link stands alone, so it is 44px high; a link inside a sentence stays inline. |

**Sizes.** Minimum height `size-control` (44px), minimum width `size-touch` (44px), padding `space-2` by `space-4`, radius `radius-1`, label `text-label` semibold. Height grows when the label wraps; labels never truncate. Allow 30% more length for translation.

| State | Secondary | Primary |
|---|---|---|
| Default | 1px `color-line-strong`, no fill | `color-accent` fill, `color-on-accent` label |
| Hover | `color-surface-raised` fill, `color-text` outline | `color-accent-hover` |
| Keyboard focus | focus ring | focus ring |
| Pressed | `color-pressed` fill, 2px outline | `color-accent-pressed` |
| Disabled | `color-line` outline, `color-text-disabled` label | the same as secondary disabled |
| Loading | `aria-busy="true"`, label changes to "Searching…" | the same |

**Keyboard.** Tab to reach; Enter or Space to press. A disabled button that explains itself stays focusable with `aria-disabled="true"` and its reason in `aria-describedby`.

**Words.** Start with a verb and say what happens: "Go to where it is now", "Download CSV", "Try again". Sentence case. No "OK", no "Submit".

**Do not** use a spinner for loading, colour a button, put two primaries in one view, or disable a button without saying why next to it.
