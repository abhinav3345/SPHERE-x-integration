# Wordmark

The product name set as plain text, with no logo mark.

Markup: `<a class="bc-wordmark" href="/">Tombaugh</a>`

| | |
|---|---|
| Type | Source Sans 3 semibold (`weight-strong`), `text-body` (16px), `leading-body` |
| Colour | `color-text` on `color-bg` or `color-surface` |
| Case | Sentence case. No tracking, no all-caps. |
| Clear space | `space-4` on every side |
| States | Default; hover underlines; keyboard focus shows the focus ring |

**The consumer provides** the name as one string. "Tombaugh" is a working name: keep it in one constant or one template slot so a rename is a single edit. Never bake the name into an image, an icon or a class name. The class prefix is `bc-` (blink comparator) for that reason.

**Do not** add a symbol, a star, an orbit or any mark beside it. Do not use NASA or SPHEREx logos, insignia or mission patches anywhere in the product: this is an independent project, and data sources are credited in words under Provenance.
