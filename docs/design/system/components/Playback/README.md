# Playback

The controls that change the frame: hold to flip, step, play, and speed.

**Anatomy**

1. Flip key (`bc-flip`): full width, 56px high, the largest control on the page and the first under the image, where a thumb rests.
2. Transport: Previous, Play or Pause, Next (icon buttons, 44px), and a frame counter in a fixed field: `Frame 2 of 4`.
3. Speed: a Slider from 1 to 6 changes a second, default 2, with its value: `2 per second`.

**Behaviour**

- Nothing plays until the reader presses Play. Play is never on by default, on load, or after a search.
- Holding the flip key shows the other frame; releasing returns. One change down, one change up.
- Stepping, flipping or choosing a row in the timeline stops playback.
- The fastest rate is 6 changes a second (`blink-rate-max`). There is no faster setting.

| State | Look |
|---|---|
| At rest | Play icon, outlined |
| Playing | Pause icon, lit (`aria-pressed="true"`) |
| Flip key held | a 2px inset line in `color-accent`. No fill: a large fill appearing at the instant the image changes would read as a flash. |
| Hover, focus, pressed | as Button |
| Disabled | all controls greyed, with the reason: "Only one frame covers this position, so there is nothing to blink yet." |

**Reduced motion.** When the device asks for reduced motion, Play and Speed are not rendered. Previous, Next and the flip key stay, with the note "Reduced motion is on, so frames change only when you step or hold." Use `@media (prefers-reduced-motion: reduce)` or the helper classes `bc-motion-only` and `bc-reduced-only`.

**Keyboard**

| Key | Does |
|---|---|
| Space | Play or pause (when focus is not on another control) |
| ← → | Previous or next frame |
| Space or Enter on the flip key | Hold to flip; release to return |
| Esc | Stop playing |

**The consumer provides** the frame list and listens for `bc:flip` (`detail.held`). Announce a frame change to screen readers only on step and flip, never during play.
