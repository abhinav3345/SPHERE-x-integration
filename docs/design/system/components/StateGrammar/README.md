# StateGrammar

The eight visual signals the system uses, each with one meaning.

| Signal | Means | Built from |
|---|---|---|
| Lit fill | Selected, or the one primary action | `color-accent` with `color-on-accent` |
| Ring | Keyboard focus | 2px `color-focus`, 2px outside the control |
| Inset line | Pressed | 1px or 2px inset in `color-text` |
| Dashed outline | Qualified: true, with a caveat | `border-style: dashed` in `color-line-strong` |
| Hollow mark | Unverified, flagged, or not yet done | `.bc-mark` with no fill |
| Hatch | No data | `nodata-a` and `nodata-b` stripes |
| Orange to blue | Earlier to later | `epoch-a`, `epoch-b`, `series-1` to `series-5`, the difference scale |
| Greyed | Cannot be used now | `color-text-disabled`, with the reason written beside it |

**Rules**

- A signal never changes meaning. Dashed is never decoration; the hatch is never a texture; orange and blue are never interface colours.
- No signal is carried by colour alone. Every state also changes shape, position, outline or words.
- Hover is a one-step lighter fill (`color-surface-raised`). It exists only where there is a pointer.
- State changes are instant. Nothing fades, slides or scales.
