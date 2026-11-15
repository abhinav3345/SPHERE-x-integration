# Contrast

Every text and background pair the system uses, with its WCAG 2 contrast ratio. Primary and secondary text clear 7:1 on every ground; control outlines, marks and focus rings clear 3:1. Ratios are computed from the token values, not measured from a screen.

| Foreground | Background | Used for | Ratio | Floor |
|---|---|---|---|---|
| `color-text` #f0f0f0 | `color-bg` #0e0e0e | Primary text | 16.9:1 | 7:1 |
| `color-text` #f0f0f0 | `color-surface` #1c1c1c | Primary text on panels | 15.0:1 | 7:1 |
| `color-text` #f0f0f0 | `color-surface-raised` #262626 | Tooltip text, hover label | 13.3:1 | 7:1 |
| `color-text` #f0f0f0 | `color-pressed` #3a3a3a | Label while pressed | 10.0:1 | 7:1 |
| `color-text-muted` #b4b4b4 | `color-bg` #0e0e0e | Secondary text | 9.3:1 | 7:1 |
| `color-text-muted` #b4b4b4 | `color-surface` #1c1c1c | Secondary text on panels | 8.2:1 | 7:1 |
| `color-text-muted` #b4b4b4 | `color-surface-raised` #262626 | Secondary text in a tooltip | 7.3:1 | 7:1 |
| `color-on-accent` #0e0e0e | `color-accent` #f0f0f0 | Label on a lit control | 16.9:1 | 7:1 |
| `color-on-accent` #0e0e0e | `color-accent-hover` #ffffff | Label on a lit control, hover | 19.3:1 | 7:1 |
| `color-on-accent` #0e0e0e | `color-accent-pressed` #c8c8c8 | Label on a lit control, pressed | 11.5:1 | 7:1 |
| `color-text-disabled` #767676 | `color-bg` #0e0e0e | Disabled label (exempt; still legible) | 4.3:1 | 3:1 |
| `color-text-disabled` #767676 | `color-surface` #1c1c1c | Disabled label on panels (exempt) | 3.8:1 | 3:1 |
| `color-line-strong` #767676 | `color-bg` #0e0e0e | Control outline, ticks | 4.3:1 | 3:1 |
| `color-line-strong` #767676 | `color-surface` #1c1c1c | Control outline on panels | 3.8:1 | 3:1 |
| `color-line-strong` #767676 | `color-surface-raised` #262626 | Tooltip outline | 3.3:1 | 3:1 |
| `color-accent` #f0f0f0 | `color-bg` #0e0e0e | Lit control against the page | 16.9:1 | 3:1 |
| `color-accent` #f0f0f0 | `color-surface` #1c1c1c | Lit control against a panel | 15.0:1 | 3:1 |
| `color-focus` #ffffff | `color-bg` #0e0e0e | Focus ring | 19.3:1 | 3:1 |
| `color-focus` #ffffff | `color-surface` #1c1c1c | Focus ring on panels | 17.0:1 | 3:1 |
| `epoch-a` #ff6600 | `color-bg` #0e0e0e | Epoch A swatch, series-1 marks | 6.6:1 | 3:1 |
| `epoch-b` #0099ff | `color-bg` #0e0e0e | Epoch B swatch, series-5 marks | 6.4:1 | 3:1 |
| `epoch-a` #ff6600 | `color-surface` #1c1c1c | Series-1 marks on a panel | 5.8:1 | 3:1 |
| `epoch-b` #0099ff | `color-surface` #1c1c1c | Series-5 marks on a panel | 5.7:1 | 3:1 |
| `series-2` #fea578 | `color-surface` #1c1c1c | Series-2 marks on a panel | 8.8:1 | 3:1 |
| `series-3` #d4d4d4 | `color-surface` #1c1c1c | Series-3 marks on a panel | 11.5:1 | 3:1 |
| `series-4` #8ac3fe | `color-surface` #1c1c1c | Series-4 marks on a panel | 9.2:1 | 3:1 |
| `nodata-b` #a3a3a3 | `nodata-a` #2b2b2b | Hatch stripes against each other | 5.6:1 | 3:1 |
| `nodata-b` #a3a3a3 | `ramp-black` #000000 | Light hatch stripe against black sky | 8.3:1 | 3:1 |
| `nodata-a` #2b2b2b | `ramp-white` #ffffff | Dark hatch stripe against a white core | 14.2:1 | 3:1 |
| `marker-position` #ffffff | `marker-casing` #000000 | Position ring against its casing | 21.0:1 | 3:1 |
| `marker-gaia` #3ce074 | `marker-casing` #000000 | Gaia marker against its casing | 12.1:1 | 3:1 |
| `marker-catwise` #fe6ec7 | `marker-casing` #000000 | CatWISE marker against its casing | 8.3:1 | 3:1 |
| `marker-was` #fce343 | `marker-casing` #000000 | Catalogue position against its casing | 16.2:1 | 3:1 |
| `marker-casing` #000000 | `ramp-white` #ffffff | Casing against a white star | 21.0:1 | 3:1 |

Notes

- Disabled labels are exempt from contrast rules but still reach 3.8:1 or better, and a disabled control always states its reason in `color-text-muted`.
- `color-line` (1.5:1) is decorative. It is never the only edge of something pressable.
- Pure `channel-b` blue is 2.2:1 on the page, so channel swatches always carry a `color-line-strong` outline and the colour's name.
- Markers are drawn over the image, which can be any grey. The black casing guarantees 8.3:1 or better between ink and casing, and 21:1 between casing and a white star.
