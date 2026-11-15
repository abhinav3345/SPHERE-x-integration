# BandSelector

The wavelength rule: an engraved scale with one tick for each of SPHEREx's 102 channels, above the nine band choices.

This is the one bold idea in the system and it is spent here only. The 102 infrared colours cannot be seen, so they are drawn as 102 ticks and never as a rainbow.

**Anatomy**

1. Group label "Band".
2. The rule (`Comparator.wavelengthRule(el, selection)`): six detectors of equal length, 17 ticks each at a whole number of pixels apart, detector names above, edge wavelengths below (0.74, 1.11, 1.65, 2.42, 3.82, 4.42, 5.00 µm). The rule is graduated by channel, not by micrometre: within a detector the channels are evenly spaced in log wavelength, which is how the instrument samples.
3. A 3 × 3 Segmented group: D1 to D6, All, Cold objects, Three-colour. Each option shows its range in Source Code Pro.

| Option | Range | On the rule |
|---|---|---|
| D1 | 0.74–1.12 µm | its 17 ticks lit |
| D2 | 1.10–1.65 µm | |
| D3 | 1.64–2.42 µm | |
| D4 | 2.42–3.82 µm | |
| D5 | 3.81–4.42 µm | |
| D6 | 4.41–5.00 µm | |
| All | 0.74–5.00 µm | all 102 lit |
| Cold objects | 4.0–5.0 µm | channels from 4.0 µm up: part of D5 and all of D6 |
| Three-colour | red 3.8–5.0, green 1.6–3.8, blue 0.74–1.65 µm | all lit, with three bars under the rule in `channel-r`, `channel-g`, `channel-b` |

**Sizes.** The rule is 58px high (86px in three-colour) and always exactly 102 × n pixels long: n = 3 on a phone, 4 from 410px, and so on. It is centred in its column. Unlit ticks are 7px in `color-line-strong`; lit ticks are 18px in `color-text`; a 2px `color-accent` line runs under the lit span.

**States.** The options take every Segmented state. The rule has two: unlit and lit. A band with no image at this position is disabled (`aria-disabled="true"`) and a note under the group says so: "D2 is greyed: no D2 image covers this position yet."

**Keyboard.** The rule is a picture (`role="img"` with a text alternative that names the selection). The options are one Tab stop; arrows move and select.

**Rules.** No hue on the rule except the three channel bars, where hue is the data encoding. Do not animate the change. Do not make the rule the only way to choose a band: the ticks are 3px apart.

**The consumer provides** the selection, and the list of bands that have data at this position.
