import { describe, expect, it } from "vitest";
import type { Provenance } from "../model";
import { PRODUCT_RELEASES, releaseNames, releasesOf, separator, stretchShown } from "./provenance";

const DR1 = { doi: "10.26131/IRSA678", release: "DR1", href: "https://doi.org/10.26131/IRSA678" };
const QR3 = { doi: "10.26131/IRSA662", release: "QR3", href: "https://doi.org/10.26131/IRSA662" };

function provenance(release: string, dois: Provenance["dois"]): Provenance {
  return {
    used: "348 of 364",
    sampled: false,
    release,
    dois,
    pipeline: "0.2.0",
    builtAt: "2026-11-14T16:18:07Z",
    notes: [],
    pixels: "Resampled to 3.075″ per pixel; native pixel 6.15″",
    stretch: "−0.0180 to 0.440 MJy/sr",
    warnings: ["None"],
  };
}

describe("release names", () => {
  it("reads the ViewModel's sentence back into release names", () => {
    expect(releaseNames("SPHEREx Spectral Images, DR1 and QR3")).toEqual(["DR1", "QR3"]);
    expect(releaseNames("SPHEREx Spectral Images, DR1")).toEqual(["DR1"]);
    expect(releaseNames("SPHEREx Spectral Images, DR1, DR1 deep and QR3")).toEqual([
      "DR1",
      "DR1 deep",
      "QR3",
    ]);
    expect(releaseNames("SPHEREx Spectral Images")).toEqual([]);
    expect(releaseNames("Something else")).toBeNull();
  });

  it("joins with commas and a final and", () => {
    expect(["a", "b", "c"].map((n, i) => separator(i, 3) + n).join("")).toBe("a, b and c");
    expect(["a", "b"].map((n, i) => separator(i, 2) + n).join("")).toBe("a and b");
  });
});

describe("releases with their DOIs", () => {
  it("pairs each release of the field with its DOI (Barnard's Star: DR1 and QR3)", () => {
    const r = releasesOf(provenance("SPHEREx Spectral Images, DR1 and QR3", [DR1, QR3]));
    expect(r.parts).toEqual([
      { name: "DR1", doi: { doi: DR1.doi, href: DR1.href } },
      { name: "QR3", doi: { doi: QR3.doi, href: QR3.href } },
    ]);
    expect(r.others).toEqual([]);
    expect(r.text).toBe("SPHEREx Spectral Images, DR1 and QR3");
  });

  it("cites only the release a field was built from (WISE 0855: DR1 alone)", () => {
    const r = releasesOf(provenance("SPHEREx Spectral Images, DR1", [DR1]));
    expect(r.parts).toEqual([{ name: "DR1", doi: { doi: DR1.doi, href: DR1.href } }]);
    expect(r.text).toBe("SPHEREx Spectral Images, DR1");
  });

  it("keeps a release without a DOI, and a DOI that names no release", () => {
    const unknown = { doi: "10.0000/X", release: null, href: "https://doi.org/10.0000/X" };
    const r = releasesOf(provenance("SPHEREx Spectral Images, DR1 deep and QR3", [QR3, unknown]));
    expect(r.parts).toEqual([
      { name: "DR1 deep", doi: null },
      { name: "QR3", doi: { doi: QR3.doi, href: QR3.href } },
    ]);
    expect(r.others).toEqual([{ doi: unknown.doi, href: unknown.href }]);
  });

  it("names the product's two releases and their DOIs before a field is open", () => {
    const r = releasesOf(null);
    expect(r.parts.map((p) => [p.name, p.doi?.doi])).toEqual([
      ["DR1", "10.26131/IRSA678"],
      ["QR3", "10.26131/IRSA662"],
    ]);
    expect(r.text).toBe("SPHEREx Spectral Images, DR1 and QR3");
    expect(PRODUCT_RELEASES.every((p) => p.doi.href === `https://doi.org/${p.doi.doi}`)).toBe(true);
  });
});

describe("brightness scale line", () => {
  const p = provenance("SPHEREx Spectral Images, DR1", [DR1]);
  it("is written where one grey scale is on screen", () => {
    expect(stretchShown(p, "cold", "blink")).toBe(true);
    expect(stretchShown(p, "all", "side")).toBe(true);
  });
  it("is left out for three-colour, the difference, then and now, and without a scale", () => {
    expect(stretchShown(p, "rgb", "blink")).toBe(false);
    expect(stretchShown(p, "cold", "difference")).toBe(false);
    expect(stretchShown(p, "cold", "then")).toBe(false);
    expect(stretchShown({ ...p, stretch: null }, "cold", "blink")).toBe(false);
    expect(stretchShown(null, "cold", "blink")).toBe(false);
  });
});
