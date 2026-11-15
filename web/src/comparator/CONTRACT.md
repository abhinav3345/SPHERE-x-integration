# The comparator: contract for the three region lanes

`/look/` is `web/look/index.html` → `src/main.tsx` → `Comparator` (this folder). The page is
four layouts composed from 24 blocks, each built by its lane. A lane edits its own blocks and
folder and nothing else. The design sources are the specification:
`docs/design/comparator/*.dc.html` (Main, Phone, Plan-1280, Plan-390, Handoff-*) and
`docs/design/system/`.

## 1. Who owns what

| Owner                   | Files                                                                                                                                                                                                        |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Architect (do not edit) | `Comparator.tsx`, `comparator.css`, `useComparator.ts`, `model.ts`, `derive.ts`, `vm.ts`, `url.ts`, `features.ts`, `format.ts`, `geometry.ts`, their tests, this file                                        |
| Time lane               | `blocks/Search.tsx`, `ArchiveNotice.tsx`, `MovedBanner.tsx`, `Playback.tsx`, `Shortcuts.tsx`, `PairInfo.tsx`, `Timeline.tsx`, `Targets.tsx`, `Caveats.tsx`, `FlipDock.tsx`, and `web/src/comparator/time/**` |
| Image lane              | `blocks/ImageFrame.tsx`, `Margin.tsx`, `Readout.tsx`, `DiffScale.tsx`, `RingBar.tsx`, `FrameLabel.tsx`, `Legend.tsx`, and `web/src/comparator/image/**` (plus `player/render.ts`, `player/screen.ts`)        |
| View lane               | `blocks/Header.tsx`, `TitleStrip.tsx`, `ViewSwitch.tsx`, `BandSelector.tsx`, `FieldOfView.tsx`, `Display.tsx`, `Provenance.tsx`, and `web/src/comparator/view/**`                                            |
| Extras lane             | `blocks/SpectrumPanel.tsx` and `web/src/comparator/extras/**` (`types.ts` is the interface: change it only with the image and view lanes); the data behind `vm.extras` (section 8)                           |

Need something the ViewModel does not give? Derive it in your own folder from `vm.state`,
`vm.field` and the exported selectors of `model.ts` / `format.ts` / `geometry.ts`. If it truly
belongs in the shared model, say so in your report; do not edit the architect's files.

## 2. Rules every block follows

1. **Signature.** `export function Name({ vm }: { vm: ViewModel })`, same file, same export name.
   One root element, or `null` when there is nothing to show (the gap then closes by itself:
   every block sits in a `display: contents` slot, so an empty block takes no room and no gap).
2. **Reserved rows stay.** Three rows keep their height when empty, so nothing jumps later:
   the ring row (44 px), the legend line (18 px), the frame label's chip row (24 px).
3. **Data only from `vm`.** No fetch, no second copy of state, no timers that change frames.
   Real data only: a value the ViewModel does not have is left out or labelled, never invented.
4. **Changes only through `vm.handlers`.** Picture changes (step, pick, flip, play) MUST go
   through handlers: they pass the one gate that allows at most 6 changes a second.
   `vm.dispatch(action)` and `vm.patch(fields)` exist for anything else (see `model.ts` Action).
5. **Words.** Print the ViewModel's strings as they are. Static strings come word for word from
   `Handoff-copy.dc.html`. Sentence case, no exclamation marks, "candidate" never "discovery".
6. **Styles.** Use the `bc-` classes of `src/design/components.css` (vendored from
   `docs/design/system/components/bundle.css`) and tokens only: no hex values, no font names,
   sizes from tokens or `calc()` of tokens. A lane stylesheet lives at
   `web/src/comparator/<lane>/<lane>.css`, imported by that lane's blocks. Scope layout rules with
   the root's class: `.cmp--phone`, `.cmp--rail`, `.cmp--three`, `.cmp--wide` (also
   `data-layout` on `<main>`). Icons: `Icon` from `src/design/icons.tsx`. Port helpers from
   `components/bundle.js` to TypeScript in your folder; never load it.
7. **Motion.** No transitions, fades, spinners. Nothing around the image may move, resize or
   reflow when the frame changes: values that change with the frame sit in fixed fields
   (`bc-fixed`, Source Code Pro). Under reduced motion Play, Speed and the shortcut list are not
   rendered.
8. **Keyboard.** The global map (Space, ← →, Esc) is in `useComparator`. It ignores keys from
   text fields, `role="radiogroup"`/`role="radio"`, sliders, and any element with
   `data-own-keys`. So: radiogroups use `role="radiogroup"` with `role="radio"` options (one Tab
   stop, arrows move and select, skipping `aria-disabled`, wrapping, Home/End); the image frame
   carries `data-own-keys`; the flip key spreads `vm.handlers.flipKey`. Every target is ≥ 44 px.
   Visible focus everywhere (`:focus-visible` comes from components.css).
9. **Fixed ids** (other blocks link to them): `tb-q` and `tb-q-msg` (Search), `tb-targets`
   (Targets), `tb-frames` (Timeline label), `tb-view`, `tb-band`, `tb-fov` (group labels),
   `tb-contrast`, `tb-speed` (sliders). `tb-go` is Comparator's "Go to another position" section.
10. **Tests.** Vitest runs in node (no DOM): put pure helpers and their tests in your lane folder
    (`*.test.ts`). Check with `npx vitest run src/comparator`, `npx biome check src/comparator`,
    `npx tsc --noEmit`. Biome flags `<div role="group">` (useSemanticElements): keep the design's
    markup with `// biome-ignore lint/a11y/useSemanticElements: <why>`.
11. **Header comments.** Every block keeps its header comment's PORTS/FLAGS/STATES lines up to
    date. (`Stub.tsx`, the placeholder the blocks started from, and its CSS are deleted.)

## 3. The layouts (Comparator.tsx)

Chosen with `matchMedia`, so the DOM order is the tab order of the layout on screen.

| Layout  | Window       | Order                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ------- | ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `wide`  | ≥ 1440 × 900 | as `three`, plus Shortcuts after Playback; columns 382 · 595 · 383                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `three` | ≥ 1280 wide  | (With the spectrum open, SpectrumPanel takes the place of BandSelector, FieldOfView and Display in the view rail; at `wide` BandSelector stays above it.) **time rail**: Search, ArchiveNotice, MovedBanner, Playback, PairInfo, Timeline (or Targets when no frame is on screen: `vm.targetsInRail`), Caveats · **image column** (`<section aria-label="Image">`): ImageFrame, Margin, DiffScale, RingBar, FrameLabel, Legend · **view rail**: Header, ViewSwitch, BandSelector, FieldOfView, Display, Provenance. Columns 362 · 476 · 362, 24 px gaps, 16 px around. From 1280 × 720 the page does not scroll. In the time rail the Timeline (or Targets) slot gives up height first: its list scrolls and keeps the current row in view, down to its label, two rows (one for a field of one frame) and its key line (`time/time.css`). Only a rail fuller still makes the caveat notice give up height second: its sentences scroll inside it, at least two lines stay in view, and "More caveats below: scroll the list." shows while some are out of view. The view rail scrolls inside itself only if it must. Under 720 px tall the page scrolls as a whole. |
| `rail`  | 720–1279     | **column** (≤ 430 px, measured): the phone order without View, Band, Field of view, Display, Provenance · **rail** (320 px): ViewSwitch, BandSelector, FieldOfView, Display, Provenance                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `phone` | < 720        | Header (app bar), TitleStrip, ArchiveNotice, MovedBanner (only while it carries its button) · **image section**: ImageFrame, Margin, DiffScale, Legend, RingBar, Readout, FrameLabel, FlipDock (last child: it sticks within the section) · **rest** (16 px gutters, 24 px gaps): Playback, PairInfo, SpectrumPanel (also in the `rail` column), notices (MovedBanner after the jump, Caveats), Timeline, ViewSwitch, BandSelector, FieldOfView, Display, Provenance, then `#tb-go` "Go to another position" with Search and Targets                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |

On a phone the image square runs edge to edge (`bc-frame` is `width: 100%; aspect-ratio: 1`);
every other block brings its own 16 px gutter (the `bc-` components already do: `bc-framefoot`,
`bc-readout`, `bc-framelabel`). At 1280 the design zeroes those paddings (Main.dc.html sets
`padding: 0` on them): do that in your lane stylesheet under `.cmp--three, .cmp--wide`.

## 4. The ViewModel (vm.ts, documented field by field)

| Field                                                                          | What                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `state`, `dispatch`, `patch`, `features`                                       | the raw state, the reducer, the flags                                                                                                                                                                                                                                                                                                                                                                                      |
| `layout`, `geometry`, `reducedMotion`, `engine`                                | layout name; image sizes; prefers-reduced-motion; `"unknown" \| "up" \| "down"`                                                                                                                                                                                                                                                                                                                                            |
| `field`                                                                        | null, or the field on screen: `manifest`, `synth`, `grid` (for pixelToSky/skyToPixel), `source`, `recorded`, `standIn`, `band` and `view` in force, `sequence` (SeqFrame[], oldest first), `pair` (`frame`, `partner`, `shown`, `a` earlier, `b` later), `shown`, `limits` and **`displayLimits` (draw every frame with these)**, `difference` (B − A with σ), `labels` (one FrameLabel per frame, one width), `anyNoData` |
| `image`                                                                        | `state` (image, loading, building, busy, empty, none, failed), `aria`, `pairAria`, `build` (three steps + bar + sentence), `busy` (`secondsLeft`, `canRetry`), `failure`, `ring`, `cursor`, `markers`, `spotlight`, `invert`, `was`                                                                                                                                                                                        |
| `chip`, `copyStatus`, `title`                                                  | header chip, Copy link status, title strip                                                                                                                                                                                                                                                                                                                                                                                 |
| `search`                                                                       | `text`, `message` (always present), `error`, `busy`, `disabled`, `button`                                                                                                                                                                                                                                                                                                                                                  |
| `notices`                                                                      | `archive`, `mover` (`sentence`, `canJump`), `caveats` (sentences, by date)                                                                                                                                                                                                                                                                                                                                                 |
| `playback`                                                                     | `enabled`, `why`, `playing`, `speed`, `speedLabel`, `counter`, `reduced`, `reducedNote`, `held`, `shortcuts`                                                                                                                                                                                                                                                                                                               |
| `pairInfo`                                                                     | A and B dates, fixed and short form (Side by side, Difference)                                                                                                                                                                                                                                                                                                                                                             |
| `timeline`                                                                     | `rows` (when, count, partial, thin, hasData, qualified, disabled, current, tag), `key`, `newest`                                                                                                                                                                                                                                                                                                                           |
| `targets`, `targetsInRail`                                                     | the five rows (current, available, unavailable reason, loading caption)                                                                                                                                                                                                                                                                                                                                                    |
| `frameLabel`                                                                   | `kind` (one, diff, two, state), `one`, `a`, `b`, `diff`, `pixels`, `showPixels`                                                                                                                                                                                                                                                                                                                                            |
| `readout`, `readoutAt(offset)`                                                 | RA, Dec, value at the cursor (else the ring); at any pixel (the pointer's, kept in the image lane)                                                                                                                                                                                                                                                                                                                         |
| `ringBar`, `legend`                                                            | show, canRecentre, spotlight; position, was, noData, rgb                                                                                                                                                                                                                                                                                                                                                                   |
| `views`, `viewNote`, `bands`, `bandNote`, `rule`, `fovs`, `fovNote`, `display` | options with `checked` and `disabled`, notes saying why something is greyed                                                                                                                                                                                                                                                                                                                                                |
| `provenance`, `loadingLine`                                                    | used, release, DOIs, pipeline, notes, pixels, stretch, warnings; "Reading 120 of 258"                                                                                                                                                                                                                                                                                                                                      |
| `announcement`                                                                 | the polite live region (rendered by Comparator)                                                                                                                                                                                                                                                                                                                                                                            |
| `extras`                                                                       | three-colour, catalogue markers, Then and now, the spectrum, and their handlers (`extras/types.ts`; section 8)                                                                                                                                                                                                                                                                                                             |
| `handlers`                                                                     | `setQuery`, `submitSearch`, `openTarget`, `retry`, `jump`, `step`, `togglePlay`, `setSpeed`, `pickFrame`, `flipDown`, `flipUp`, `flipKey`, `setRing`, `frameKeyDown`, `clearCursor`, `toggleSpotlight`, `recentre`, `setView`, `setBand`, `setFov`, `setContrast`, `setInvert`, `setMarkers`, `copyLink`, `measureColumn`                                                                                                  |

Offsets (`ring`, `cursor`, `setRing`, `readoutAt`) are image pixels from the field's centre
pixel: `dx` grows west (right on screen), `dy` south (down). Column = `grid.cx + dx`.

## 5. The blocks

### Time lane

| Block         | Ports (Main / Phone)   | Flags                  | Notes                                                                                                                                                                                                                                                                                                                                                |
| ------------- | ---------------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Search        | 24–31 / 534–541        | nameSearch             | inline form with hidden label at 1280; visible label on a phone. Message line two lines high. Busy: read-only, "Searching…", aria-busy. Error: aria-invalid, warning icon, role="alert".                                                                                                                                                             |
| ArchiveNotice | 33–41 / 41–51          | —                      | only while `vm.notices.archive`; "Try again" → `retry`                                                                                                                                                                                                                                                                                               |
| MovedBanner   | 43–51 / 53–63, 389–393 | movedBanner            | sentence + "Go to where it is now" (primary) while `canJump`; Comparator places it                                                                                                                                                                                                                                                                   |
| Playback      | 53–75 / 261–282        | holdToFlip             | Blink only. 1280: flip key first (spread `flipKey`), then transport, speed, notes; min-height 160 px. Phone/rail: no flip key (FlipDock). Reduced: no Play, no Speed, the note.                                                                                                                                                                      |
| Shortcuts     | 77–83 / —              | spotlight              | only when `vm.playback.shortcuts` (1440 × 900)                                                                                                                                                                                                                                                                                                       |
| PairInfo      | 85–102 / 284–300       | sideBySide, difference | min-height 160 px at 1280                                                                                                                                                                                                                                                                                                                            |
| Timeline      | 113–127 / 411–425      | sideBySide, difference | newest chip only when `vm.timeline.newest`; rows greyed when qualified; aria-current on `current`; A/B tags; disabled rows in Difference; the key line                                                                                                                                                                                               |
| Targets       | 129–140 / 542–551      | —                      | links: a recorded field `?target=…`; the other three `?ra=…&dec=…`, their catalogue position moved to the frames' epoch (`targetPosition`), opened as a build: they need the engine, not name lookup. A row that cannot open (engine down) shows `unavailable` instead and is not a link; current mark; "Building this image…" caption while loading |
| Caveats       | 142–156 / 394–407      | —                      | one warning notice; a list when several; phone adds "Details are under Provenance."                                                                                                                                                                                                                                                                  |
| FlipDock      | — / 250–255            | holdToFlip             | phone and rail only, Blink only; `position: sticky; bottom: 0`; not pinned under 560 px tall                                                                                                                                                                                                                                                         |

### Image lane

| Block      | Ports (Main / Phone) | Flags                                               | Notes                                                                                                                                                                                                                                                                                                                                                                                    |
| ---------- | -------------------- | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ImageFrame | 163–261 / 67–173     | spotlight, sideBySide, difference, catalogueMarkers | the square, canvas(es), ring, pixel cursor, spotlight crop, state blocks (build, empty, busy with countdown, none, failed). Draw with `vm.geometry` (one/two/spot/spotTwo: whole device pixels, smoothing off, `image-rendering: pixelated`) and `vm.field.displayLimits`; hatch NaN; Invert for every frame. Click/tap → `setRing`; keys → `frameKeyDown`; `data-own-keys`; tabIndex 0. |
| Margin     | 263–274 / 175–181    | —                                                   | scale bar (`geometry.scaleBar`), compass; the readout sits here only at 1280/1440                                                                                                                                                                                                                                                                                                        |
| Readout    | — / 208–212          | —                                                   | phone and rail only (Comparator places it)                                                                                                                                                                                                                                                                                                                                               |
| DiffScale  | 276–283 / 183–190    | difference                                          | Difference only                                                                                                                                                                                                                                                                                                                                                                          |
| RingBar    | 285–293 / 199–206    | spotlight, spectrum (off)                           | always 44 px; Recentre when `canRecentre`, with its tooltip                                                                                                                                                                                                                                                                                                                              |
| FrameLabel | 295–339 / 214–248    | sideBySide, difference                              | chip row reserved; `aria-live="off"`                                                                                                                                                                                                                                                                                                                                                     |
| Legend     | 341–346 / 192–197    | catalogueMarkers, threeColour                       | keeps 18 px when empty                                                                                                                                                                                                                                                                                                                                                                   |

### View lane

| Block        | Ports (Main / Phone) | Flags                              | Notes                                                                                                                         |
| ------------ | -------------------- | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Header       | 353–361 / 21–29      | copyLink                           | chip "Recorded field" (dashed, empty mark) or "Live data" (solid, full mark); `SITE_NAME` from `src/site.ts`; tooltip at 1280 |
| TitleStrip   | — / 31–38            | —                                  | phone and rail; "Change" → `#tb-go`                                                                                           |
| ViewSwitch   | 363–372 / 427–436    | sideBySide, difference, thenAndNow | only built views are listed; not rendered with Blink alone                                                                    |
| BandSelector | 374–422 / 438–484    | threeColour                        | the wavelength rule (port `rule()` at Main 597–644), 3 × 3 options; Cold objects spans two cells without three-colour         |
| FieldOfView  | 500–512 / 486–496    | —                                  | greyed sizes with `vm.fovNote`                                                                                                |
| Display      | 514–527 / 498–509    | contrast, invert                   | the note always stays, so does Markers                                                                                        |
| Provenance   | 529 / 511–529        | —                                  | 1280: one paragraph, both DOIs as links; 1440 adds the brightness scale; phone: the line, then Details                        |

## 6. Feature flags (features.ts)

All twelve parts are built and on: holdToFlip, contrast, invert, spotlight, copyLink,
sideBySide, difference, thenAndNow, threeColour, spectrum, catalogueMarkers and movedBanner
(always on: its known movers, WISE 0855 at the brief's coordinates, need no network, and
`findMover` answers null when it has nothing, so the banner simply does not appear). Only
nameSearch follows the search lane: it is on when `NAME_LOOKUP_AVAILABLE` (a team backend is
configured). The five targets open without it. A flag switched off is the last resort; the
ViewModel then lists only built views and bands, and a link naming an unbuilt part opens Blink or
the default band. Tests check both states through `withFeatures`.

## 7. Behaviour already in the hook (do not rebuild it)

- Loading: recorded fields by target (bundled copy when the engine does not answer), any
  position through the engine with build progress (throttled to once a second), no coverage,
  busy (countdown, Try again after it), failures with the loader's sentence. A position the
  engine or the archive cannot build shows the nearest recorded field instead, with the archive
  notice, search off and the asked place kept in the address bar.
- Search: the name of one of the five targets opens it at once; anything else goes through
  `resolveQuery`, then `findMover` (overlays). A position on a recorded centre at 6′ opens the
  recorded copy at once; a recorded target at another size (`?target=wise0855&fov=10`) builds
  its centre at that size, in the target's band.
- Playback: never starts by itself; one gate caps every picture change at 6 a second; reduced
  motion pauses; hold to flip is one change down, one change up, key repeat ignored.
- The pair: opens on the newest full frame, partner the oldest full one; choosing a row makes the
  frame you came from the partner; stepping and playing never change the partner; Difference
  uses full frames only.
- Address bar: `?target=…` or `?ra=…&dec=…`, `fov`, `band`, `view`, `frame`, `partner`, `ring`,
  `spot`, `spec` (url.ts), written with `replaceState` a moment after a change, never while
  playing. Copy link writes the address first, then copies it.
- Extras: the catalogue overlays of the field on screen while Markers is on, and the spectrum at
  the ring while its panel is open, each aborted when what it was asked for changes; a recorded
  field's recorded answers, read only when no live answer can be had (section 8).

## 8. The four extras (vm.extras; extras/types.ts, extras/derive.ts)

Every value is real: from the field's planes, or from the engine's answer. Nothing is drawn
without a real position; a missing value is left out with a plain sentence.

| Part              | What `vm.extras` gives                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Drawn by                                                         |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| Three-colour      | `threeColour.frames`: one `{ r, g, b }` per frame of `vm.field.sequence` (band "rgb" only, else null), each channel by the contract's frame formula (presets.json: red D5 + D6, green D3 + D4, blue D1 + D2). `limits` are pooled per channel over the whole sequence, BEFORE the Contrast step: apply `displayLimits(limits, vm.state.contrast)` (model.ts) to each, as for one band. `ranges` are the legend's words. The sequence's own facts in "rgb" are the three channels together: the whole range, all exposures, partial when any channel lacks a wave bin it has at another visit; a pixel is "no data" when any channel has none there.                                                                                                                                                                                                                                                                                                                                                                                                      | image lane (frame, legend)                                       |
| Catalogue markers | `markers.status` "off" (Markers toggle), "loading", "ready", "unavailable" with `note` (no engine, the route is missing, the catalogues are down: never a marker without a position). `gaia` (open cross) and `catwise` (diamond): `xy` has one plane pixel per frame of the sequence (null off the image), projected with player/grid.ts; a moving source follows the engine's `track` and is null in a frame the track does not reach; `fast` when its track spans at least one pixel (draw the track), `label` its proper motion then. Only the ring's neighbours are listed: sources within 15″ of the ring (`NEIGHBOUR_ARCSEC`, extras/derive.ts `neighboursOf`) plus every `fast` source; a source with a proper motion but no track is not drawn on a frame where its own motion has carried it a pixel or more since its catalogue epoch (`staleWithoutTrack`). The legend keys a catalogue while its overlay is on, so it never changes when the ring moves. `was`: the moved-object hint's position as a pixel, with its year (dashed square). | image lane (frame, legend)                                       |
| Then and now      | `thenAndNow.status` "none" with "No older survey image is stored for this field yet." when the field has no legacy plane; else "ready": `older` (the legacy plane paired with the band on screen, else the field's first, in presets.json `legacy_pairs` order; its own scale; title "WISE W2, 2010"; the real span of its images) and `sphx` (one stack of the paired band over every visit, its own scale). `note` names the pairing when it is not the band on screen; PairInfo prints it, once, in Then and now (`vm.viewNote` says only why a view is greyed, and the view switch prints one sentence per greyed view). Both limits are before the Contrast step.                                                                                                                                                                                                                                                                                                                                                                                   | image lane (two squares, labels); view lane (switch)             |
| Spectrum          | `spectrum.open` (state `spectrum`, link `spec=1`), `status` "closed", "loading" ("Measuring…", "Measuring 120 of 258"), "ready", "saturated", "unavailable"; `messages` in the design's words; `visits` (time order, the five latest, labels "7–14 Nov 2025"); `points` (one per exposure, `flagged` hollow) and `binned`; `mode` "chart" or "table". Handlers: `toggleSpectrum` (the ring row's Spectrum button, aria-pressed = `open`), `setSpectrumMode`, `downloadCsv` (exactly the points shown).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | SpectrumPanel (extras lane); RingBar (image lane) for the button |

State added for these: `spectrum` (panel open; kept by Recentre, a new field of view and the
jump; closed by any other `go`) and `spectrumMode`, with the actions `setSpectrum` and
`setSpectrumMode`. Env added: `overlays`, `spectrum` and `recorded` (what the hook has loaded).

SpectrumPanel: Main.dc.html 424–498 and Phone.dc.html 310–384. At 1280 it takes the place of
Band, Field of view and Display in the view rail; at 1440 Band stays; on a phone and in the rail
layout's column it sits under the playback. The chart is extras/chart.ts (bundle.js `spectrum`,
ported): flux in µJy against 0.75 to 5.0 µm, one series colour and shape per visit, larger binned
points, hollow flagged points; the flux axis follows the data and always includes zero. No
example values are ever drawn.

### Recorded answers (markers and spectrum with no engine)

A recorded field may carry real answers of the engine's two routes, recorded beside it:
`cache/fixtures/<name>/overlays.json` and `spectrum.json` (both optional; one envelope each:
`contract`, `kind` "recorded_answer", `route`, `field`, `key`, `pipeline_version`, `recorded_at`,
`request`, `response`; the type is `RecordedAnswer` in `src/api.ts`, kept out of the shared
`src/contract.ts` until the contract's owner takes the envelope in). `scripts/sync-contract.mjs`
copies them to `public/fixtures/<name>/`; `loadRecordedOverlays` and `loadRecordedSpectrum`
(`src/api.ts`) read them from the page's own origin and give `null` for anything that fails R1.
The rules are in `extras/derive.ts` ("Recorded answers"); the hook asks for a file only when
`recordedNeeded` says the rules call for it.

- **R1** An answer is used only for the recorded field of its name whose manifest key is its key,
  with contract 1.x, kind, route and field as expected and a response that passes the live
  loader's checks. Those checks hold every field of 7.1 and 7.3 with its type, as the engine's
  models write them (a target with its position, method, neighbours, a time span or null, every
  point and binned value; every source with its id, position and epoch, every track point, both
  upstream states): an answer missing any of them is refused whole, live ("bad_response") or
  recorded (null). A recorded spectrum is used only when its `request` is the manifest's request
  position, as the format says it is.
- **R2** Live answers win. A recorded answer is used only when no live one can be had: the field
  is the bundled copy (a live answer the hook still holds for its key, from before the engine went
  away, does not count), the engine's request failed (network error, timeout, 404, 429, 5xx; not
  a 400 or an answer that breaks the contract), or, for the overlays only, the live answer marks a
  catalogue "unavailable" (then only when the recorded answer has every catalogue the live one
  has, and more). And only for a recorded field opened for itself (`answersField`): a recorded
  field shown instead of the place asked for ("Showing the recorded field instead.") uses none, as
  before recorded answers, so its markers and spectrum never read as those of the place asked for
  (and the caveat that would label them cannot fall below the 1280 rail's edge under that notice
  and a mover banner).
- **R3** The recorded spectrum is used only while the ring is on the pixel of the envelope's
  `request` position (a recorded field's default ring). One pixel away the panel says what it
  says today ("The spectrum cannot be measured while the archive is not responding." for the
  bundled copy); Recentre opens the recorded field again and brings it back.
- **R4** Whatever comes from a recorded answer is labelled, with the UTC date of `recorded_at` in
  the page's one-date form (`shortDate`, "15 Nov 2026"): `vm.extras.markers.recorded`, one caveat
  sentence in place of "Catalogue markers are off while the archive is not responding." (the
  Caveats block lists it, `time/rail.ts` caveatList; the legend does not repeat it), and
  `vm.extras.spectrum.recorded`, the qualifier chip (dashed, empty mark, as the header's
  "Recorded field") at the end of the Download CSV row, the one place in the panel where it costs
  no height (the 1280 × 720 view rail stays 688 of 688 px with the chart open). The CSV holds
  exactly the rows shown, as for a live answer; its file name ends in `-recorded-<date>`.
- **R5** No file, or an envelope that fails R1: the page behaves as it does without recorded
  answers. While a needed file is on its way the markers are "loading" and the panel shows no
  sentence (nothing is being measured). A file the site did not serve this time (no answer after
  three attempts, 429 or 5xx) counts as none too, and is asked for again the next time the rules
  call for it (markers on again, the ring back, the field opened again). On a phone and in the
  rail layout the caveat block is mounted whenever its list has a sentence
  (`time/rail.ts` columnHasNotices), so the R4 sentence shows even for a field with no caveat of
  its own.

New copy (no board has it). [date] is a slot, as in Handoff-copy: the UTC date of the file's
`recorded_at`, written as the page writes one date (15 Nov 2026 for the recordings of that day).

| String                                     | Where and when                                                                          |
| ------------------------------------------ | --------------------------------------------------------------------------------------- |
| Catalogue markers were recorded on [date]. | Caveat list, while markers from a recorded answer are drawn                             |
| Recorded [date]                            | Chip at the end of the spectrum panel's Download CSV row, while it shows such an answer |
