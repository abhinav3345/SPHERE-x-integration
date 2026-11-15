# Tombaugh web app

One static site built with Vite (React, TypeScript), with two pages:

- `/`, the landing page: `index.html` loads `src/landing/main.tsx`.
- `/look/`, the comparator: `look/index.html` loads `src/main.tsx`, which renders the designed
  comparator in `src/comparator/` (its own contract: `src/comparator/CONTRACT.md`).

The designs are the specification: `../docs/design/system/` (rules, tokens, components),
`../docs/design/landing/` and `../docs/design/comparator/` (layouts, states, and the hand-off boards for
behaviour, copy, images and the removable parts). Their rules outrank taste: real data only, whole-pixel
images with smoothing off, one brightness scale per sequence, hatched no-data pixels, nothing plays until the
reader starts it, nothing around the image moves, tokens and `bc-` classes only.

## Folders in `src/`

- `landing/`: the landing page.
- `comparator/`: the comparator screen, built from the designs. A removable part that is not finished
  is switched off in `comparator/features.ts`, never left half done (today all twelve are on).
- `overlays/`: search (names and coordinates, through the team backend) and the hint for objects that have
  moved away from their catalogue position. `overlays/types.ts` is the interface with the comparator.
- `player/`: the frame maths, with tests: float16 decoding, sky grid, playback, presets, rendering, screen
  mapping, band synthesis, and small React helpers (`hooks.ts`; the comparator uses
  `usePrefersReducedMotion`). The first viewer (`App.tsx`, `Player.tsx`, `Viewport.tsx`) is deleted.
- `design/`: `tokens.css`, `components.css` (the `bc-` classes, copied from the design system's bundle),
  `icons.tsx`.
- `api.ts` loads a field from the frames engine and falls back to the bundled recorded fields, and
  reads their recorded answers (below, type `RecordedAnswer`); `contract.ts` holds the types of the
  engine's contract (`../docs/CONTRACT_FIELDS.md`); `site.ts` holds the name, the comparator path and the
  repository address.

Also here: `functions/api/[[path]].ts` (a Cloudflare Pages Function that forwards `/api` to the engine),
`vercel.example.json` (the same for Vercel), `public/fonts/` (self-hosted fonts with their licences).

## Without the engine

With no engine answering (none configured, or it does not respond), the page still shows the two
recorded fields, WISE 0855 and Barnard's Star, from the copies bundled with the site: every frame,
band and view (Blink, Side by side, Difference, Then and now, three-colour). Each recorded field also
carries real answers of the engine's catalogue and spectrum routes, recorded beside it
(`overlays.json`, `spectrum.json`; both optional). They stand in only where no live answer can be
had, and are always labelled with the date they were recorded ([date] below: the UTC date of the
file's `recorded_at`, written as the page writes one date, such as 15 Nov 2026):

- Catalogue markers (Gaia DR3 and CatWISE, with WISE 0855's track): drawn from the recorded answer,
  with the caveat "Catalogue markers were recorded on [date]."
- The spectrum: at the field's own position only, the default ring (WISE 0855 measured; Barnard's
  Star "Saturated: no reliable brightness"), with the chip "Recorded [date]". Anywhere else in the
  field the panel says the spectrum cannot be measured while the archive is not responding.

Everything else needs the engine: any other position, field of view or spectrum. A recorded field
shown instead of another position that was asked for ("Showing the recorded field instead.") uses
no recorded answer, so nothing it shows reads as an answer for that position. With the engine
answering, the live answers are shown and the recorded files are not even requested; they also
stand in when one of its requests fails. The rules are in `src/comparator/CONTRACT.md`, section 8.

## Generated folders: never edit or commit

`src/generated/` and `public/fixtures/` are written by `scripts/sync-contract.mjs` from
`../docs/contract/presets.json` and `../cache/fixtures/` (each recorded field's manifest, frame file
and recorded answers), before every `npm run dev`, `npm run build` and `npm test`. Change the sources
instead and run `npm run sync`. `dist/` is the build output.

## Commands

```bash
npm install
npm run dev      # http://localhost:5173/ and http://localhost:5173/look/
npm test         # Vitest in the node environment (no DOM)
npm run lint     # Biome; npm run format applies its fixes
npm run build    # tsc --noEmit, then vite build into dist/
```

## Environment variables

Copy `.env.example` to `.env.local`.

- `VITE_TEAM_API_URL`: the team backend (`../src/backend`), for `/resolve` and `/stars`. In development
  `http://localhost:8000`.
- `VITE_ENGINE_URL`: the frames engine (`../api`). Empty: the same origin, with `/api` proxied.
- `TOMBAUGH_API_URL`: read by the development server only, not by the page: where it sends `/api`. Default
  `http://localhost:8080`; set it when the engine runs on another port.

Values that start with `VITE_` are compiled into the page, so nothing secret goes in them. The page makes no
request to any other origin: no CDN, no web fonts from elsewhere.
