import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { Manifest } from "../contract";
import { decodeFloat16 } from "../player/float16";
import { FieldSynth } from "../player/synth";
import { withFeatures } from "./features";
import { effectiveBand, INITIAL_STATE, type LoadedField, reduce, type ViewState } from "./model";
import { EMPTY_LINK, goFromLink, type LinkState, linkFromState, readLink, writeLink } from "./url";

describe("readLink", () => {
  it("reads a recorded target with its frame state", () => {
    expect(readLink("?target=wise0855&band=cold&frame=4&partner=2")).toEqual({
      ...EMPTY_LINK,
      place: { kind: "recorded", target: "wise0855" },
      band: "cold",
      frame: 3,
      partner: 1,
    });
  });

  it("reads a position with the four extras", () => {
    expect(
      readLink("ra=133.7598&dec=-7.2422&fov=8&view=difference&frame=3&partner=1&ring=-41,3&spot=1"),
    ).toEqual({
      place: { kind: "position", ra: 133.7598, dec: -7.2422, name: null },
      fov: 8,
      band: null,
      view: "difference",
      frame: 2,
      partner: 0,
      ring: { dx: -41, dy: 3 },
      spotlight: true,
      spectrum: false,
    });
  });

  it("reopens the spectrum panel, only when the part is built", () => {
    expect(readLink("?target=wise0855&spec=1").spectrum).toBe(true);
    expect(readLink("?target=wise0855&spec=yes").spectrum).toBe(false);
    expect(readLink("?target=wise0855&spec=1", withFeatures({ spectrum: false })).spectrum).toBe(
      false,
    );
  });

  it("opens Blink, or the field's default band, for a part that is not built", () => {
    const query = "?target=barnard&view=then&band=rgb&frame=2";
    const link = readLink(query, withFeatures({ thenAndNow: false, threeColour: false }));
    expect(link.view).toBe("blink");
    expect(link.band).toBeNull();
    expect(link.frame).toBe(1);
    expect(link.place).toEqual({ kind: "recorded", target: "barnard" });
    const built = readLink(query, withFeatures({ thenAndNow: true, threeColour: true }));
    expect(built).toMatchObject({ view: "then", band: "rgb", frame: 1 });
    expect(readLink("?target=barnard&view=side", withFeatures({ sideBySide: false })).view).toBe(
      "blink",
    );
    expect(readLink("?view=then", withFeatures({ thenAndNow: true })).view).toBe("then");
    expect(readLink("?spot=1", withFeatures({ spotlight: false })).spotlight).toBe(false);
  });

  it.each([
    ["?target=planetx", "unknown target"],
    ["?ra=360&dec=0", "RA out of range"],
    ["?ra=10&dec=-90.5", "Dec out of range"],
    ["?ra=1e2&dec=0", "not a decimal"],
    ["?ra=&dec=5", "empty"],
    ["?ra=10", "half a position"],
  ])("opens no position for %s (%s)", (query) => {
    expect(readLink(query).place).toEqual({ kind: "none" });
  });

  it("repairs everything else it cannot use", () => {
    const link = readLink("?target=wise0855&fov=7&band=x&view=zoom&frame=0&partner=abc&ring=1,2,3");
    expect(link).toEqual({ ...EMPTY_LINK, place: { kind: "recorded", target: "wise0855" } });
    expect(readLink("?frame=2&partner=2").partner).toBeNull();
    expect(readLink("?ring=0,0").ring).toBeNull();
    expect(readLink("?ring=120,0").ring).toBeNull();
  });
});

describe("writeLink", () => {
  it("writes nothing for nothing", () => {
    expect(writeLink(EMPTY_LINK)).toBe("");
  });

  it("leaves out what is at its default", () => {
    expect(
      writeLink({
        ...EMPTY_LINK,
        place: { kind: "recorded", target: "barnard" },
        frame: 4,
        partner: 0,
      }),
    ).toBe("?target=barnard&frame=5&partner=1");
  });

  it.each<LinkState>([
    {
      ...EMPTY_LINK,
      place: { kind: "recorded", target: "wise0855" },
      band: "cold",
      frame: 3,
      partner: 1,
    },
    {
      place: { kind: "position", ra: 269.4463, dec: 4.7682, name: null },
      fov: 10,
      band: "d3",
      view: "side",
      frame: 0,
      partner: 4,
      ring: { dx: 12, dy: -7 },
      spotlight: true,
      spectrum: true,
    },
    { ...EMPTY_LINK, place: { kind: "position", ra: 0, dec: -90, name: null }, view: "difference" },
    { ...EMPTY_LINK, fov: 3 },
  ])("round-trips %j", (link) => {
    expect(readLink(writeLink(link))).toEqual(link);
  });
});

const fixturesDir = fileURLToPath(new URL("../../public/fixtures/", import.meta.url));
const wiseDir = join(fixturesDir, "wise0855");

describe.skipIf(!existsSync(join(wiseDir, "manifest.json")))("the link of the screen", () => {
  const manifest: Manifest = JSON.parse(readFileSync(join(wiseDir, "manifest.json"), "utf8"));
  const bytes = readFileSync(join(wiseDir, "frames.bin"));
  const field: LoadedField = {
    manifest,
    synth: new FieldSynth(manifest, decodeFloat16(new Uint8Array(bytes).buffer)),
    source: "bundled",
    recorded: "wise0855",
  };

  function opened(): ViewState {
    const asked = reduce(INITIAL_STATE, goFromLink(readLink("?target=wise0855")));
    return reduce(asked, {
      type: "loaded",
      requestId: asked.request?.id ?? -1,
      field,
      fallback: false,
    });
  }

  it("writes the band, view, pair, ring, spotlight and spectrum in force", () => {
    const state = [
      { type: "setView", view: "side" } as const,
      { type: "setRing", ring: { dx: -41, dy: 3 } } as const,
      { type: "setSpotlight", on: true } as const,
      { type: "setSpectrum", open: true } as const,
    ].reduce(reduce, opened());
    expect(writeLink(linkFromState(state))).toBe(
      "?target=wise0855&band=cold&view=side&frame=4&partner=2&ring=-41,3&spot=1&spec=1",
    );
  });

  it("restores an open spectrum panel from its link", () => {
    const asked = reduce(INITIAL_STATE, goFromLink(readLink("?target=wise0855&spec=1")));
    expect(asked.spectrum).toBe(true);
    const closed = reduce(asked, { type: "setSpectrum", open: false });
    expect(writeLink(linkFromState(closed))).toBe("?target=wise0855");
  });

  it("restores the screen it was copied from", () => {
    const before = reduce(opened(), { type: "pickFrame", index: 0 });
    const link = readLink(writeLink(linkFromState(before)));
    const asked = reduce({ ...INITIAL_STATE, view: link.view }, goFromLink(link));
    const after = reduce(asked, {
      type: "loaded",
      requestId: asked.request?.id ?? -1,
      field,
      fallback: false,
    });
    expect(linkFromState(after)).toEqual(linkFromState(before));
  });

  it("keeps the place asked for while a recorded field stands in for it", () => {
    const asked = reduce(INITIAL_STATE, goFromLink(readLink("?ra=200&dec=10&fov=8")));
    const standIn = reduce(asked, { type: "loaded", requestId: 1, field, fallback: true });
    expect(writeLink(linkFromState(standIn))).toBe("?ra=200&dec=10&fov=8");
  });

  it("opens the recorded copy for a link to its centre at 6′", () => {
    expect(goFromLink(readLink("?ra=133.7598&dec=-7.2422")).place).toEqual({
      kind: "recorded",
      target: "wise0855",
    });
    expect(goFromLink(readLink("?ra=133.7598&dec=-7.2422&fov=8")).place).toMatchObject({
      kind: "position",
    });
  });

  it("opens a recorded target at another size as a build of its centre, never the 6′ copy", () => {
    const go = goFromLink(readLink("?target=wise0855&fov=10"));
    expect(go).toMatchObject({
      place: { kind: "position", ra: 133.7598, dec: -7.2422, name: "WISE 0855" },
      fov: 10,
      target: "wise0855",
    });
    const asked = reduce(INITIAL_STATE, go);
    expect(asked.request).toMatchObject({ fov: 10, target: "wise0855" });
    // Its own band carries to the build (WISE 0855 is visible only in Cold objects).
    expect(effectiveBand(asked)).toBe("cold");
    expect(writeLink(linkFromState(asked))).toBe("?ra=133.7598&dec=-7.2422&fov=10");
    // At 6′ the target opens its recorded copy as before.
    expect(goFromLink(readLink("?target=wise0855")).place).toEqual({
      kind: "recorded",
      target: "wise0855",
    });
  });
});
