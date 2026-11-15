# TargetCard

A named starting point with one honest sentence about what the image shows.

**Anatomy.** A list (`bc-targets`), not a grid of cards. Each row is a link (`bc-target`): the name in `text-body` semibold, an optional qualifier chip after it, and a caption in `text-label` and `color-text-muted`. Rows are divided by `color-line` hairlines; there are no thumbnails, no shadows and no rounded boxes.

**The five targets**

| Name | Caption | Chip |
|---|---|---|
| WISE 0855 | Visible only at 4 to 5 µm. Moved 4.4″ in six months. | |
| Barnard's Star | Moves 10.25″ a year. Its centre is saturated. | Saturated core |
| Epsilon Indi B | An unresolved pair of brown dwarfs. Motion not yet measured. | |
| RW Aurigae | Brighter at 1.2 µm, fainter at 4.6 µm across three visits. | |
| R Draconis | Saturated in almost every exposure. | Saturated core |

| State | Look |
|---|---|
| Default | name and caption |
| Hover | `color-surface-raised` |
| Keyboard focus | focus ring around the row |
| Pressed | `color-pressed` |
| Current | an 8px filled mark before the name, `aria-current="true"` |
| Loading | the caption reads "Building this image…" |

**Keyboard.** Each row is a link: Tab to it, Enter follows it.

**Writing a caption.** One or two short sentences. Say what can be seen and what cannot. Give the number and its unit. If something is not known, say "not yet measured". Never "discovery", never "stunning", never an exclamation mark.
