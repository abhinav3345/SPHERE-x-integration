# ImageFrame

The square that holds the image, its overlay of markers, and the margin annotations under it.

**Anatomy**

1. Frame (`bc-frame`): a square in `color-surround`. Its size depends only on the layout, never on the image, so it does not change when the field of view or the frame changes.
2. Image (`canvas.bc-frame__image`), centred, with a 1px `color-line` outline. A frame from another survey has a dashed outline (`bc-frame--survey`).
3. Overlay (`svg.bc-frame__overlay`) in screen pixels: markers, track, spotlight. See Markers.
4. Margin (`bc-framefoot`): scale bar on the left, compass on the right, 44px high. They sit under the image, not on it, so they cover no sky.
5. Readout (`bc-readout`): three fixed fields, for example `RA 133.75977°  Dec −7.24183°  0.142 MJy/sr`.

**Scaling. This is the rule that protects the science.**

- Draw every image pixel as a whole number of device pixels: `scale = floor(frameWidth × devicePixelRatio / imageWidth)`. `Comparator.displayScale()` and `paintFrame()` do this.
- No smoothing: `imageSmoothingEnabled = false` on the canvas and `image-rendering: pixelated` in CSS.
- A 119px frame comes out 357px wide (3×) on most phones from 360 to 414px, and up to 408px on the widest or densest ones. A 197px frame takes the largest whole scale that fits. The rest of the square is neutral surround.
- Every frame in a sequence uses the same scale, the same position and the same brightness scale.

**Sizes.** Phone: full column width, edge to edge. Laptop and projector at 1280 × 720: 476px (4×), with at least `space-4` of `color-surround` on every side and nothing lit within 16px of the image.

| State | Look |
|---|---|
| Default | image, overlay, margin, readout |
| Pointer over the image | readout shows the pixel under the cursor |
| No pixel under the cursor | each readout field holds a dash and keeps its width |
| Keyboard focus | focus ring drawn just inside the frame edge |
| Spotlight on | everything outside the circle dimmed by `spotlight-dim` |
| Building, empty, error | the frame keeps its square and shows a Notice or a progress block. See States. |

**Keyboard.** The frame is one Tab stop with a label that names the frame on screen. Arrow keys move the readout one image pixel; Shift with an arrow moves ten. Enter sets the chosen position. Plus and minus change the spotlight size. Esc closes the spotlight.

**Never** animate the image, cross-fade between frames, resize the frame with the data, draw anything decorative over the sky, or let a control with a lit fill touch the image edge.

**The consumer provides** pixel values already stretched to 0 to 255 with one stretch for the whole sequence, a mask of no-data pixels, and the world coordinates for the readout.
