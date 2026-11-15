import { describe, expect, it } from "vitest";
import { EMPTY_EXTRAS } from "../extras/empty";
import type { ExtrasVM, ThenAndNowVM } from "../extras/types";
import { targetById, targetPosition } from "../model";
import { readLink, writeLink } from "../url";
import {
  CAVEATS_CUT,
  caveatList,
  columnHasNotices,
  isColumn,
  isCut,
  isThreeColumns,
  listContext,
  opensInPlace,
  playbackParts,
  rowToKeep,
  SPEED_STOPS,
  scrollToShow,
  speedFromInput,
  targetHref,
  thenAndNowLines,
} from "./rail";

const BUILDING = "Frames can be flipped once the first one is built.";
const REDUCED = "Reduced motion is on, so frames change only when you step or hold.";
const ONE = "Only one frame covers this position, so there is nothing to blink yet.";

describe("layouts", () => {
  it("names the three-column layouts and the column layouts", () => {
    expect(isThreeColumns("three")).toBe(true);
    expect(isThreeColumns("wide")).toBe(true);
    expect(isThreeColumns("rail")).toBe(false);
    expect(isThreeColumns("phone")).toBe(false);
    expect(isColumn("phone")).toBe(true);
    expect(isColumn("rail")).toBe(true);
    expect(isColumn("three")).toBe(false);
    expect(isColumn("wide")).toBe(false);
  });
});

describe("playbackParts", () => {
  const ready = { enabled: true, why: null, reduced: false, reducedNote: null };

  it("puts the flip key first at 1280 and 1440 only, and never when hold to flip is off", () => {
    expect(playbackParts("three", true, ready).flipKey).toBe(true);
    expect(playbackParts("wide", true, ready).flipKey).toBe(true);
    expect(playbackParts("phone", true, ready).flipKey).toBe(false);
    expect(playbackParts("rail", true, ready).flipKey).toBe(false);
    expect(playbackParts("three", false, ready).flipKey).toBe(false);
  });

  it("numbers the speed ticks in the column only", () => {
    expect(playbackParts("phone", true, ready).labelledTicks).toBe(true);
    expect(playbackParts("rail", true, ready).labelledTicks).toBe(true);
    expect(playbackParts("three", true, ready).labelledTicks).toBe(false);
  });

  it("drops Play and Speed under reduced motion and shows the system's note", () => {
    const parts = playbackParts("three", true, {
      enabled: true,
      why: null,
      reduced: true,
      reducedNote: REDUCED,
    });
    expect(parts.play).toBe(false);
    expect(parts.speed).toBe(false);
    expect(parts.flipKey).toBe(true);
    expect(parts.notes).toEqual([REDUCED]);
  });

  it("gives the reason when the controls are greyed, after the reduced-motion note", () => {
    expect(playbackParts("phone", true, { ...ready, enabled: false, why: ONE }).notes).toEqual([
      ONE,
    ]);
    expect(
      playbackParts("phone", true, {
        enabled: false,
        why: BUILDING,
        reduced: true,
        reducedNote: REDUCED,
      }).notes,
    ).toEqual([REDUCED, BUILDING]);
  });

  it("never shows a stale reason while the controls work", () => {
    expect(playbackParts("three", true, { ...ready, why: ONE }).notes).toEqual([]);
  });
});

describe("speedFromInput", () => {
  it("accepts the six stops and nothing else", () => {
    expect(SPEED_STOPS).toEqual([1, 2, 3, 4, 5, 6]);
    expect(speedFromInput("1")).toBe(1);
    expect(speedFromInput("6")).toBe(6);
    expect(speedFromInput("0")).toBeNull();
    expect(speedFromInput("7")).toBeNull();
    expect(speedFromInput("2.5")).toBeNull();
    expect(speedFromInput("")).toBeNull();
    expect(speedFromInput("abc")).toBeNull();
  });
});

describe("rowToKeep", () => {
  const rows = [0, 1, 2, 3].map((index) => ({ index, current: index === 0 }));

  it("keeps the chosen frame, not the partner shown while the flip key is held", () => {
    // Held: the current row is the partner (0); the list stays on the chosen frame (2).
    expect(rowToKeep(rows, 2)).toBe(2);
  });

  it("counts positions in the list, not frame numbers", () => {
    const tail = rows.slice(2);
    expect(rowToKeep(tail, 3)).toBe(1);
  });

  it("keeps nothing without rows or a frame", () => {
    expect(rowToKeep([], 0)).toBeNull();
    expect(rowToKeep(rows, null)).toBeNull();
    expect(rowToKeep(rows, 9)).toBeNull();
  });
});

describe("listContext", () => {
  const base = { key: "abc", band: "all", view: "blink", rows: 5, playing: false };

  it("stays the same when only the frame changes", () => {
    expect(listContext(base)).toBe(listContext({ ...base }));
  });

  it("changes with the build, the band, the view, the rows and playback", () => {
    const one = listContext(base);
    expect(listContext({ ...base, key: "def" })).not.toBe(one);
    expect(listContext({ ...base, band: "cold" })).not.toBe(one);
    expect(listContext({ ...base, view: "side" })).not.toBe(one);
    expect(listContext({ ...base, rows: 4 })).not.toBe(one);
    expect(listContext({ ...base, playing: true })).not.toBe(one);
  });

  it("reads a missing field as empty", () => {
    expect(listContext({ key: null, band: null, view: null, rows: 0, playing: false })).toBe(
      "|||0|still",
    );
  });
});

describe("scrollToShow", () => {
  const view = { scrollTop: 100, height: 132 };

  it("leaves a row that is already in view where it is", () => {
    expect(scrollToShow(view, { top: 100, height: 44 })).toBeNull();
    expect(scrollToShow(view, { top: 188, height: 44 })).toBeNull();
  });

  it("ignores half a pixel of rounding", () => {
    expect(scrollToShow(view, { top: 99.6, height: 44 })).toBeNull();
    expect(scrollToShow(view, { top: 188.4, height: 44 })).toBeNull();
  });

  it("brings a row above the view to its top edge", () => {
    expect(scrollToShow(view, { top: 44, height: 44 })).toBe(44);
    expect(scrollToShow(view, { top: -3, height: 44 })).toBe(0);
  });

  it("brings a row below the view to its bottom edge, moving as little as possible", () => {
    expect(scrollToShow(view, { top: 220, height: 44 })).toBe(220 + 44 - 132);
  });

  it("shows the top of a row taller than the view", () => {
    expect(scrollToShow({ scrollTop: 0, height: 30 }, { top: 88, height: 44 })).toBe(88);
  });

  it("does nothing for a list with no height or a row it cannot measure", () => {
    expect(scrollToShow({ scrollTop: 0, height: 0 }, { top: 88, height: 44 })).toBeNull();
    expect(scrollToShow(view, { top: Number.NaN, height: 44 })).toBeNull();
  });
});

describe("targets", () => {
  it("links a recorded field to its own address and the others to where they are now", () => {
    expect(targetHref("wise0855")).toBe("?target=wise0855");
    expect(targetHref("barnard")).toBe("?target=barnard");
    // Before: "#tb-targets", so a click with a modifier opened nothing (fix-core, 14 Nov).
    expect(targetHref("epsindi")).toBe("?ra=331.0967&dec=-56.8007");
    for (const id of ["epsindi", "rwaur", "rdra"] as const) {
      const at = targetPosition(targetById(id));
      expect(at).not.toBeNull();
      expect(targetHref(id)).toBe(`?ra=${at?.ra}&dec=${at?.dec}`);
    }
  });

  it("opens in a new tab the same position the row opens in place", () => {
    for (const id of ["epsindi", "rwaur", "rdra"] as const) {
      const link = readLink(targetHref(id));
      const at = targetPosition(targetById(id));
      expect(link.place).toEqual({ kind: "position", ra: at?.ra, dec: at?.dec, name: null });
      expect(writeLink(link)).toBe(targetHref(id));
    }
  });

  it("opens in place on a plain primary click only", () => {
    const plain = { button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false };
    expect(opensInPlace(plain)).toBe(true);
    expect(opensInPlace({ ...plain, metaKey: true })).toBe(false);
    expect(opensInPlace({ ...plain, ctrlKey: true })).toBe(false);
    expect(opensInPlace({ ...plain, shiftKey: true })).toBe(false);
    expect(opensInPlace({ ...plain, altKey: true })).toBe(false);
    expect(opensInPlace({ ...plain, button: 1 })).toBe(false);
  });
});

describe("caveatList", () => {
  // The caveats of the recorded Barnard's Star field, as the model writes them.
  const barnard = [
    "2 exposures could not be used.",
    "Saturated core within 15″ of the centre in 359 of 360 exposures.",
    "The visit of 30 Sep–1 Oct 2025 has only 9 exposures.",
  ];
  const on = { onScreen: true, catalogueMarkers: true };
  const withExtras = (
    markers: Partial<ExtrasVM["markers"]>,
    spectrum: Partial<ExtrasVM["spectrum"]>,
  ): ExtrasVM => ({
    ...EMPTY_EXTRAS,
    markers: { ...EMPTY_EXTRAS.markers, ...markers },
    spectrum: { ...EMPTY_EXTRAS.spectrum, ...spectrum },
  });

  it("keeps the field's caveats in their order when the extras have nothing", () => {
    expect(caveatList(barnard, EMPTY_EXTRAS, on)).toEqual(barnard);
    expect(caveatList([], EMPTY_EXTRAS, on)).toEqual([]);
  });

  it("adds why the catalogue markers are missing", () => {
    const extras = withExtras({ status: "unavailable", note: "Gaia could not be reached." }, {});
    expect(caveatList(barnard, extras, on)).toEqual([...barnard, "Gaia could not be reached."]);
  });

  it("says once that the markers drawn were recorded, only while they are drawn", () => {
    // The extras lane writes the sentence with the recording's date; this one is a stand-in.
    const synthetic_recorded = "Catalogue markers were recorded on 1 Jan 2000.";
    const drawn = withExtras({ status: "ready", note: null, recorded: synthetic_recorded }, {});
    expect(caveatList(barnard, drawn, on)).toEqual([...barnard, synthetic_recorded]);
    const withNote = withExtras(
      { status: "ready", note: "Gaia could not be reached.", recorded: synthetic_recorded },
      {},
    );
    expect(caveatList(barnard, withNote, on)).toEqual([
      ...barnard,
      synthetic_recorded,
      "Gaia could not be reached.",
    ]);
    for (const status of ["off", "loading", "unavailable"] as const) {
      const notDrawn = withExtras({ status, note: null, recorded: synthetic_recorded }, {});
      expect(caveatList(barnard, notDrawn, on)).toEqual(barnard);
    }
    expect(caveatList(barnard, drawn, { ...on, catalogueMarkers: false })).toEqual(barnard);
    expect(caveatList(barnard, drawn, { ...on, onScreen: false })).toEqual(barnard);
  });

  it("holds the phone's notices for a field with no caveat of its own but its markers' sentence", () => {
    // Comparator's Column mounts the caveat list only when this says so: the recorded markers'
    // sentence (R4), or why markers are missing, must not be lost with no caveat of the field's.
    const synthetic_recorded = "Catalogue markers were recorded on 1 Jan 2000.";
    const drawn = withExtras({ status: "ready", note: null, recorded: synthetic_recorded }, {});
    const missing = withExtras({ status: "unavailable", note: "Gaia could not be reached." }, {});
    const quiet = withExtras({ status: "ready", note: null }, {});
    const none = { mover: null, caveats: [] };
    expect(columnHasNotices(none, drawn, on)).toBe(true);
    expect(columnHasNotices(none, missing, on)).toBe(true);
    expect(columnHasNotices(none, quiet, on)).toBe(false);
    expect(columnHasNotices(none, drawn, { ...on, catalogueMarkers: false })).toBe(false);
    expect(columnHasNotices({ mover: null, caveats: barnard }, quiet, on)).toBe(true);
    const stays = { sentence: "Moved.", canJump: false };
    expect(columnHasNotices({ mover: stays, caveats: [] }, quiet, on)).toBe(true);
    expect(columnHasNotices({ mover: { ...stays, canJump: true }, caveats: [] }, quiet, on)).toBe(
      false,
    );
  });

  it("leaves out markers the reader hid, markers still loading, and the flag's absence", () => {
    const hidden = withExtras({ status: "off", note: "Markers are off." }, {});
    const loading = withExtras({ status: "loading", note: "Loading Gaia." }, {});
    const unavailable = withExtras(
      { status: "unavailable", note: "Gaia could not be reached." },
      {},
    );
    expect(caveatList(barnard, hidden, on)).toEqual(barnard);
    expect(caveatList(barnard, loading, on)).toEqual(barnard);
    expect(caveatList(barnard, unavailable, { ...on, catalogueMarkers: false })).toEqual(barnard);
  });

  it("never repeats the spectrum panel's sentences: the panel prints them", () => {
    // Before: a live region in the rail that repeated the panel and was read out again each
    // time the ring moved with the panel open (verify-visual and review-code, 14 Nov).
    const messages = [
      "Indicative only: the star's centre overflowed",
      "The spectrum cannot be measured while the archive is not responding.",
    ];
    for (const status of ["ready", "saturated", "unavailable", "loading"] as const) {
      const open = withExtras({}, { open: true, status, messages });
      expect(caveatList(barnard, open, on)).toEqual(barnard);
    }
  });

  it("says nothing about the extras without a frame on screen", () => {
    const extras = withExtras({ status: "unavailable", note: "Gaia could not be reached." }, {});
    expect(caveatList([], extras, { ...on, onScreen: false })).toEqual([]);
  });

  it("says a scrolled list is cut only when a line is out of view, not for rounding", () => {
    expect(isCut({ scrollHeight: 288, clientHeight: 231 })).toBe(true);
    expect(isCut({ scrollHeight: 233, clientHeight: 231 })).toBe(true);
    expect(isCut({ scrollHeight: 232, clientHeight: 231 })).toBe(false);
    expect(isCut({ scrollHeight: 231, clientHeight: 231 })).toBe(false);
    // Not laid out (display: none, a test without layout): never cut.
    expect(isCut({ scrollHeight: 120, clientHeight: 0 })).toBe(false);
    expect(CAVEATS_CUT).toBe("More caveats below: scroll the list.");
  });

  it("lists every sentence once and drops empty ones", () => {
    const extras = withExtras({ status: "ready", note: barnard[0] }, {});
    expect(caveatList([...barnard, "  ", barnard[1]], extras, on)).toEqual(barnard);
  });
});

describe("thenAndNowLines", () => {
  const data = new Float32Array(0);
  const ready: ThenAndNowVM = {
    status: "ready",
    note: null,
    older: { data, limits: null, title: "WISE W2, 2010", dates: "May to Nov 2010" },
    sphx: {
      data,
      limits: null,
      title: "SPHEREx 4.0–5.0 µm",
      exposures: "82 exposures",
      dates: "May 2025 to May 2026",
    },
  };

  it("names the other survey and the SPHEREx stack", () => {
    expect(thenAndNowLines(ready)).toEqual({
      older: "Then: WISE W2, 2010",
      sphx: "Now: SPHEREx 4.0–5.0 µm, May 2025 to May 2026",
      why: null,
    });
  });

  it("invents nothing while the older image is missing, and passes on why", () => {
    expect(thenAndNowLines(EMPTY_EXTRAS.thenAndNow)).toEqual({
      older: null,
      sphx: null,
      why: null,
    });
    expect(
      thenAndNowLines({
        status: "none",
        note: "No older survey image covers this band.",
        older: null,
        sphx: null,
      }),
    ).toEqual({ older: null, sphx: null, why: "No older survey image covers this band." });
  });

  it("leaves out a part with no words", () => {
    const blank = {
      ...ready,
      older: ready.older ? { ...ready.older, title: " " } : null,
      sphx: ready.sphx ? { ...ready.sphx, dates: "" } : null,
    };
    expect(thenAndNowLines(blank)).toEqual({
      older: null,
      sphx: "Now: SPHEREx 4.0–5.0 µm",
      why: null,
    });
  });
});
