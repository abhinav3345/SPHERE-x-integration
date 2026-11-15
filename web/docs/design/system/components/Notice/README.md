# Notice

A message in the flow of the page, with an icon and at most one action: the moved-object banner, warnings, and state messages.

**Anatomy.** Icon (20px), one or two sentences, optional muted second line, optional action row. Padding `space-3` by `space-4`, radius `radius-2`, `color-surface` fill.

| Variant | Class | Icon | Outline |
|---|---|---|---|
| Message | `bc-notice` | `information` | `color-line-strong` |
| Warning | `bc-notice bc-notice--warning` | `warning` | `color-text` |
| Inside the image frame | add `bc-notice--plain` | either | no fill |

**Roles.** Use `role="status"` for messages and warnings that arrive while the reader works, and `role="alert"` only for an error the reader must act on now.

**States.** The notice itself has none. Its action is a Button and takes focus in the normal tab order; focus never jumps to a notice when it appears.

**Words.** Say what is true, then what to do. Use the reader's terms.

- "WISE 0855-0714 was here in 2010. It is now 126″ to the west." Action: "Go to where it is now".
- "12 exposures could not be read."
- "The archive is not responding. Showing the recorded field instead." Action: "Try again".

**Do not** stack more than two notices, auto-dismiss one that carries a caveat, use a coloured stripe or background, or put a qualifier only in a notice that can be closed.
