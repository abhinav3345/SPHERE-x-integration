# SearchField

One field that takes a sky position or an object name and says how it was understood.

**Anatomy.** Label "Sky position or name", input in Source Code Pro at 16px (so phones do not zoom), a Search button, and a message line that is always present: hint, interpretation, status or error.

**Layout.** On a phone the input takes the full width, so a whole coordinate such as `08h55m10.831s -07d14m42.53s` is visible, and the button sits beside the message. From 26rem of width the button moves up beside the input. In a wide app bar use `bc-field--inline` with a visually hidden label.

**Accepts**

- Decimal degrees: `133.7599 -7.2418`
- Hours and degrees: `08h55m10.831s -07d14m42.53s`
- A name: `Barnard's Star`

| State | Look and message |
|---|---|
| Default | 1px `color-line-strong`. Hint: "Try 133.7599 -7.2418, 08h55m10.831s -07d14m42.53s or Barnard's Star." |
| Hover | outline `color-text` |
| Keyboard focus | focus ring |
| Filled | message says how the entry was read: "Read as RA 133.79513°, Dec −7.24515°." |
| Error | 2px `color-text` outline, `aria-invalid="true"`, warning icon, `role="alert"`: "Declination must be between −90 and +90 degrees." |
| Loading | input read-only, button "Searching…" with `aria-busy`, message "Looking up the name." |
| Disabled | `color-line` outline, `color-text-disabled` text, and the reason in the message line |

**Keyboard.** Enter in the field searches. Tab moves from field to button. Global shortcuts (Space, arrows) are off while the field has focus.

**Rules.** Never clear or rewrite what the reader typed, including on error. An error names the value that is wrong and the allowed range. A name that resolves to a catalogue position with known motion is followed by the moved-object banner, not by a silent jump. The message line is two lines high even when short, so the page below does not move.

**The consumer provides** the parser, the resolver, and the interpretation string. The parser accepts the true minus (−, U+2212) as well as the keyboard hyphen, because displayed coordinates use it and readers paste them back. Set `autocomplete="off"`, `autocapitalize="off"`, `spellcheck="false"` and `enterkeyhint="search"`.
