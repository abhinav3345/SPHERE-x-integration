/**
 * One plate: the canvas with the image at a whole number of device pixels per image pixel, and
 * over it, in screen pixels, the spotlight, the catalogue marks, the ring and the pixel cursor.
 *
 * - The canvas is (crop × k) device pixels and exactly (crop × scale) CSS pixels, smoothing off,
 *   image-rendering: pixelated. The bytes are painted here (plate.ts), never resampled by CSS.
 * - It is repainted only when what it shows changes; a frame change touches nothing else.
 * - The plate is nudged by less than a device pixel so its corner lands on the device-pixel grid
 *   (a 357 px image centred in a 390 px square starts half a pixel in).
 * - A click or a tap moves the ring and does nothing else. Pointer movement (not touch) sets the
 *   pixel the readout shows.
 */
import { type MouseEvent, type PointerEvent, useLayoutEffect, useMemo, useRef } from "react";
import { type PlateCrop, pixelUnder, plateToPixel } from "../../player/screen";
import type { Fit } from "../geometry";
import type { ViewModel } from "../vm";
import { paintPlate } from "./device";
import {
  cursorPath,
  MARKER_PATHS,
  type MarkerKind,
  markerPoint,
  onPlate,
  type PlatePoint,
  spotlightPaths,
  trackPath,
} from "./overlay";
import { palette } from "./palette";
import { type Painted, type Picture, paintPicture } from "./picture";
import { setPointer } from "./pointer";
import { useSmoothDisplay } from "./SmoothDisplay";
import { type DrawnMarker, imageSize, marksOf, pixelOf, type SquareModel, wasOf } from "./scene";
import { paintPlateSmooth } from "./smooth";

/** What a picture shows, as eight fixed slots: its kind, arrays, limits and flags. */
function contentsOf(picture: Picture | null): readonly unknown[] {
  if (picture === null) return [null, null, null, null, null, null, null, null];
  if (picture.kind === "grey") {
    return [picture.kind, picture.data, picture.limits, picture.invert, null, null, null, null];
  }
  if (picture.kind === "rgb") {
    const { limits } = picture;
    return [
      picture.kind,
      picture.r,
      picture.g,
      picture.b,
      limits.r,
      limits.g,
      limits.b,
      picture.invert,
    ];
  }
  return [picture.kind, picture.data, picture.sigma, null, null, null, null, null];
}

/** Paint a picture once per change of what it shows. */
function usePainted(picture: Picture | null, nx: number): Painted | null {
  const [c0, c1, c2, c3, c4, c5, c6, c7] = contentsOf(picture);
  // biome-ignore lint/correctness/useExhaustiveDependencies: c0 to c7 ARE the picture's contents
  return useMemo(
    () => (picture ? paintPicture(picture, nx, palette().ramp) : null),
    [c0, c1, c2, c3, c4, c5, c6, c7, nx],
  );
}

function Mark({ kind, at }: { kind: MarkerKind; at: PlatePoint }) {
  const d = MARKER_PATHS[kind];
  return (
    <g className={`bc-mk bc-mk--${kind}`} transform={`translate(${at.x} ${at.y})`}>
      <path className="bc-mk__casing" d={d} />
      <path className="bc-mk__ink" d={d} />
    </g>
  );
}

function Track({ d, catwise }: { d: string; catwise: boolean }) {
  if (!d) return null;
  return (
    <g className={`bc-mk bc-mk--track${catwise ? " img-track--catwise" : ""}`}>
      <path className="bc-mk__casing" d={d} />
      <path className="bc-mk__ink" d={d} />
    </g>
  );
}

/** Everything over the image, in this plate's screen pixels. */
function Overlay({ vm, square, crop }: { vm: ViewModel; square: SquareModel; crop: PlateCrop }) {
  const side = crop.size * crop.scale;
  const ring = pixelOf(vm, vm.image.ring);
  const cursor = vm.image.cursor ? pixelOf(vm, vm.image.cursor) : null;
  const was = wasOf(vm);
  const wasAt = was ? markerPoint(crop, was.x, was.y) : null;
  const ringAt = markerPoint(crop, ring.x, ring.y);
  const { gaia, catwise } = marksOf(vm, square);
  const spot = vm.image.spotlight ? spotlightPaths(crop, ring.x, ring.y) : null;
  const marks = (list: DrawnMarker[], kind: "gaia" | "catwise") =>
    list.map((marker) => {
      const point = marker.point ? markerPoint(crop, marker.point.x, marker.point.y) : null;
      return point && onPlate(crop, point) ? <Mark key={marker.id} kind={kind} at={point} /> : null;
    });
  const tracks = (list: DrawnMarker[], catwiseTrack: boolean) =>
    list.map((marker) =>
      marker.track ? (
        <Track
          key={`track-${marker.id}`}
          catwise={catwiseTrack}
          d={trackPath(marker.track.map((p) => markerPoint(crop, p.x, p.y)))}
        />
      ) : null,
    );
  return (
    <svg className="bc-frame__overlay" viewBox={`0 0 ${side} ${side}`} aria-hidden="true">
      {spot && (
        <>
          <path className="bc-spotlight" fillRule="evenodd" d={spot.dim} />
          <path className="bc-spotlight__ring bc-spotlight__ring--casing" d={spot.ring} />
          <path className="bc-spotlight__ring" d={spot.ring} />
        </>
      )}
      {wasAt && onPlate(crop, wasAt) && <Mark kind="was" at={wasAt} />}
      {tracks(gaia, false)}
      {tracks(catwise, true)}
      {marks(gaia, "gaia")}
      {marks(catwise, "catwise")}
      {vm.image.markers && <Mark kind="position" at={ringAt} />}
      {cursor && (
        <g className="bc-mk bc-mk--position">
          <path className="bc-mk__casing" d={cursorPath(crop, cursor.x, cursor.y)} />
          <path className="bc-mk__ink" d={cursorPath(crop, cursor.x, cursor.y)} />
        </g>
      )}
    </svg>
  );
}

export interface PlateProps {
  vm: ViewModel;
  square: SquareModel;
  fit: Fit;
  crop: PlateCrop;
}

export function Plate({ vm, square, fit, crop }: PlateProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const plateRef = useRef<HTMLDivElement>(null);
  const nudge = useRef({ x: 0, y: 0 });
  const { nx, ny, cx, cy } = imageSize(vm);
  const k = fit.devicePerPixel;
  const side = crop.size * crop.scale;
  const painted = usePainted(square.picture, nx);
  const smooth = useSmoothDisplay();

  // The bytes, at device resolution. Runs before the browser paints, with the label's glyphs.
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    const pixels = crop.size * k;
    if (canvas.width !== pixels) canvas.width = pixels;
    if (canvas.height !== pixels) canvas.height = pixels;
    context.imageSmoothingEnabled = false;
    if (!painted) {
      context.clearRect(0, 0, pixels, pixels);
      return;
    }
    const crop2 = { x0: crop.x0, y0: crop.y0, size: crop.size };
    const painter = smooth ? paintPlateSmooth : paintPlate;
    const bytes = painter(painted.rgba, painted.noData, nx, ny, k, crop2, palette().hatch);
    context.putImageData(new ImageData(bytes, pixels, pixels), 0, 0);
  }, [painted, k, crop.x0, crop.y0, crop.size, nx, ny, smooth]);

  // Land the plate's corner on the device-pixel grid. Layout only: the plate's size, the screen's
  // density or the square's size changed; never on a frame change. The nudge is a layout offset
  // (left, top: the plate is position: relative), never a transform: a sub-pixel transform makes
  // the compositor resample the canvas.
  const layout = vm.layout;
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-snap when the layout or sizes change
  useLayoutEffect(() => {
    const plate = plateRef.current;
    if (!plate) return;
    const snap = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = plate.getBoundingClientRect();
      const baseX = rect.left - nudge.current.x;
      const baseY = rect.top - nudge.current.y;
      const x = Math.round(baseX * dpr) / dpr - baseX;
      const y = Math.round(baseY * dpr) / dpr - baseY;
      if (Math.abs(x - nudge.current.x) < 1e-3 && Math.abs(y - nudge.current.y) < 1e-3) return;
      nudge.current = { x, y };
      plate.style.left = Math.abs(x) < 1e-3 ? "" : `${x}px`;
      plate.style.top = Math.abs(y) < 1e-3 ? "" : `${y}px`;
    };
    snap();
    const observer = new ResizeObserver(snap);
    if (plate.parentElement) observer.observe(plate.parentElement);
    window.addEventListener("resize", snap);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", snap);
    };
  }, [side, k, layout]);

  // The pointer leaves with the plate.
  useLayoutEffect(() => () => setPointer(null), []);

  const pointAt = (event: MouseEvent<HTMLElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const zoom = rect.width > 0 ? side / rect.width : 1;
    return { x: (event.clientX - rect.left) * zoom, y: (event.clientY - rect.top) * zoom };
  };

  const onPointerMove = (event: PointerEvent<HTMLElement>) => {
    if (event.pointerType === "touch") return;
    const pixel = pixelUnder(crop, nx, ny, pointAt(event));
    setPointer(pixel ? { dx: pixel.x - cx, dy: pixel.y - cy } : null);
  };

  const onClick = (event: MouseEvent<HTMLElement>) => {
    const point = pointAt(event);
    const exact = pixelUnder(crop, nx, ny, point);
    const near = plateToPixel(crop, point);
    const x = exact?.x ?? Math.min(nx - 1, Math.max(0, Math.round(near.x)));
    const y = exact?.y ?? Math.min(ny - 1, Math.max(0, Math.round(near.y)));
    vm.handlers.setRing({ dx: x - cx, dy: y - cy });
  };

  return (
    // The keyboard reaches the same action through the frame: Enter moves the ring to the cursor.
    // biome-ignore lint/a11y/useKeyWithClickEvents: the frame (one Tab stop) owns the keys
    // biome-ignore lint/a11y/noStaticElementInteractions: a click on the sky moves the ring
    <div
      ref={plateRef}
      className="bc-frame__plate img-plate"
      style={{ width: side, height: side }}
      onClick={onClick}
      onPointerMove={onPointerMove}
      onPointerLeave={() => setPointer(null)}
    >
      <canvas ref={canvasRef} className="bc-frame__image" style={{ width: side, height: side }} />
      <Overlay vm={vm} square={square} crop={crop} />
    </div>
  );
}
