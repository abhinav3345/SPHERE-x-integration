/**
 * ImageFrame (LANE: image): the square, its canvas(es) and what is drawn over them.
 *
 * PORTS: Main.dc.html 163–232 (one frame: plate, ring, was, cursor, spotlight; the building,
 *        no-coverage, busy and no-position states in the square) and 234–261 (two squares);
 *        Phone.dc.html 67–173 (two squares one above the other, frame A's label between).
 *        Geometry: Handoff-images; the ring, cursor and spotlight: Handoff-components.
 * FLAGS: spotlight (vm.image.spotlight), sideBySide and thenAndNow (two squares),
 *        difference (later minus earlier on the diff-* scale in units of σ), threeColour (the
 *        frame from its three channels, vm.extras.threeColour), catalogueMarkers (the dashed
 *        square, the Gaia cross, the CatWISE diamond and their tracks, vm.extras.markers).
 * STATES: vm.image.state: image | loading (empty square) | building (BuildProgress, polite
 *         status) | busy (countdown, Try again aria-disabled until 0) | empty | none | failed.
 *         Then and now with no older image: the square says why (vm.extras.thenAndNow.note).
 *         The square never changes size: bc-frame is width 100%, aspect-ratio 1.
 * DRAWING: image/Plate.tsx: whole device pixels per image pixel, smoothing off, pixelated; every
 *         frame of a sequence on one scale; NaN hatched at 45° in nodata-a/nodata-b; Invert for
 *         every frame, never the hatch. The spotlight repaints the 39 × 39 pixels around the ring
 *         from the data at three times the scale, in the same square.
 * INPUT: the square (or the pair) is one Tab stop: role="group", aria-label, data-own-keys,
 *        onKeyDown = vm.handlers.frameKeyDown (arrows move the pixel cursor, Shift ten, Enter
 *        moves the ring). A click or a tap on a plate moves the ring and does nothing else.
 * IDS: "See the targets" links to #tb-targets.
 */
import "../image/image.css";
import type { KeyboardEvent } from "react";
import type { PlateCrop } from "../../player/screen";
import type { Fit } from "../geometry";
import { PairLabel, SurveyLabel } from "../image/labels";
import { Plate } from "../image/Plate";
import { cropOf, fitInUse, isTwoUp, type SquareModel, squaresOf } from "../image/scene";
import { FrameStateBlock, SquareNote } from "../image/states";
import type { ViewModel } from "../vm";

interface Focus {
  tabIndex: 0;
  "data-own-keys": "";
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
}

function Square({
  vm,
  square,
  fit,
  crop,
  focus,
}: {
  vm: ViewModel;
  square: SquareModel;
  fit: Fit;
  crop: PlateCrop;
  focus: Focus | null;
}) {
  return (
    // biome-ignore lint/a11y/useSemanticElements: the design's frame is a labelled group
    <div
      className={square.survey ? "bc-frame bc-frame--survey" : "bc-frame"}
      role="group"
      aria-label={square.aria}
      data-square={square.id}
      {...focus}
    >
      {square.note !== null ? (
        <SquareNote text={square.note} />
      ) : (
        <div className="bc-frame__stage">
          <Plate vm={vm} square={square} fit={fit} crop={crop} />
        </div>
      )}
    </div>
  );
}

export function ImageFrame({ vm }: { vm: ViewModel }) {
  const focus: Focus = {
    tabIndex: 0,
    "data-own-keys": "",
    onKeyDown: vm.handlers.frameKeyDown,
  };

  if (vm.image.state !== "image" || !vm.field) {
    return (
      // biome-ignore lint/a11y/useSemanticElements: the design's frame is a labelled group
      <div className="bc-frame" role="group" aria-label={vm.image.aria} {...focus}>
        <FrameStateBlock vm={vm} />
      </div>
    );
  }

  const squares = squaresOf(vm);
  const fit = fitInUse(vm);
  const crop = cropOf(vm, fit);

  if (!isTwoUp(vm) || squares.length !== 2) {
    const [one] = squares;
    return one ? <Square vm={vm} square={one} fit={fit} crop={crop} focus={focus} /> : null;
  }

  const [a, b] = squares;
  const phoneLike = vm.layout === "phone" || vm.layout === "rail";
  const tail = phoneLike
    ? "Tap to move the ring."
    : "Arrow keys move the readout by one pixel. Enter moves the ring there.";
  const field = vm.field;
  const then = field.view === "then";
  return (
    // biome-ignore lint/a11y/useSemanticElements: one Tab stop for the pair, as for one frame
    <div
      className={phoneLike ? "img-two img-two--stack" : "img-two"}
      role="group"
      aria-label={`${a.aria}. ${b.aria}. ${tail}`}
      {...focus}
    >
      <Square vm={vm} square={a} fit={fit} crop={crop} focus={null} />
      {phoneLike &&
        (then ? (
          <SurveyLabel
            older={vm.extras.thenAndNow.status === "ready" ? vm.extras.thenAndNow.older : null}
          />
        ) : (
          <PairLabel which="A" label={field.labels[field.pair.a]} />
        ))}
      <Square vm={vm} square={b} fit={fit} crop={crop} focus={null} />
    </div>
  );
}
