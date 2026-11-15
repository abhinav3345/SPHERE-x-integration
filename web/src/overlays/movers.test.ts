import { describe, expect, it } from "vitest";
import { findMover, findMoverWith, gaiaTracks, yearOfApproach } from "./movers";
import { resolveQueryWith } from "./resolve";
import { separationArcsec } from "./sky";
import { type GaiaStar, readStarsBody, type TeamApi } from "./team-api";
import type { MoverHint, Resolved } from "./types";

const BASE = "https://team.example";

type Reply = { status: number; body?: unknown } | "network-error" | "hang";

/** A stand-in for fetch: answers from `reply`, records every URL, honours the abort signal. */
function standIn(reply: (url: URL) => Reply): { api: TeamApi; urls: URL[] } {
  const urls: URL[] = [];
  const api: TeamApi = {
    base: BASE,
    fetch: (url, init) => {
      urls.push(new URL(url));
      const r = reply(new URL(url));
      if (r === "network-error") return Promise.reject(new TypeError("Failed to fetch"));
      if (r === "hang") {
        return new Promise<Response>((_, reject) => {
          init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
        });
      }
      const body = r.body === undefined ? null : JSON.stringify(r.body);
      return Promise.resolve(new Response(body, { status: r.status }));
    },
  };
  return { api, urls };
}

// Rows the local team backend's /stars (Gaia DR3, epoch 2016.0) returned on 14 Nov 2026, size 8,
// around each target's catalogue position. Only the rows the tests need; order kept.
const BARNARD_FIELD: GaiaStar[] = [
  {
    id: "4472832130942575872",
    ra: 269.44850252543836,
    dec: 4.739420051112412,
    pmra: -801.5509783684709,
    pmdec: 10362.394206546573,
    mag: 8.193974494934082,
  },
  {
    id: "4472832165289153024",
    ra: 269.4664606871366,
    dec: 4.705572810663312,
    pmra: 0.578470389706761,
    pmdec: -8.67125381236081,
    mag: 11.451173782348633,
  },
  {
    id: "4472795640887274368",
    ra: 269.4657166080078,
    dec: 4.606230904551042,
    pmra: -9.42520722892476,
    pmdec: -59.656228022068376,
    mag: 11.783349990844727,
  },
];
const EPS_INDI_FIELD: GaiaStar[] = [
  {
    id: "6412596458823395328",
    ra: 331.12955733329204,
    dec: -56.774753379007024,
    pmra: -26.603905346571707,
    pmdec: -18.587487854395548,
    mag: 12.953572273254395,
  },
  {
    id: "6412595290591430784",
    ra: 330.88312311835193,
    dec: -56.803080831887236,
    pmra: null,
    pmdec: null,
    mag: 20.542539596557617,
  },
  {
    id: "6412596012146801152",
    ra: 331.07645259656397,
    dec: -56.79381206688221,
    pmra: 3981.97666296105,
    pmdec: -2466.8318147663504,
    mag: 18.030664443969727,
  },
];
const RW_AUR_FIELD: GaiaStar[] = [
  {
    id: "156336779511773440",
    ra: 76.86366110019404,
    dec: 30.38329152893434,
    pmra: -4.123505355600266,
    pmdec: -1.2506120405073604,
    mag: 9.899928092956543,
  },
  {
    id: "156288950755956864",
    ra: 76.99382177464557,
    dec: 30.33173213735283,
    pmra: -39.51778479773462,
    pmdec: 9.523467303197966,
    mag: 10.954176902770996,
  },
  {
    id: "156430615957866368",
    ra: 76.99834776704031,
    dec: 30.43070785477714,
    pmra: null,
    pmdec: null,
    mag: 16.77659797668457,
  },
];

// /resolve answers from the same backend (CDS Sesame: catalogue positions at J2000).
const NAMES: Record<string, { name: string; ra: number; dec: number }> = {
  "Barnard's Star": { name: "Barnard's Star", ra: 269.4520769586187, dec: 4.69336496657667 },
  "Epsilon Indi B": { name: "Epsilon Indi B", ra: 331.04414658852124, dec: -56.78284419511611 },
  "RW Aurigae": { name: "RW Aurigae", ra: 76.95652603458, dec: 30.40143817389 },
};

/** A backend that knows the three names above and answers /stars with `field`. */
function backend(field: GaiaStar[] | Reply): { api: TeamApi; urls: URL[] } {
  return standIn((url) => {
    if (url.pathname === "/resolve") {
      const found = NAMES[url.searchParams.get("q") ?? ""];
      return found ? { status: 200, body: found } : { status: 404, body: { error: "unknown" } };
    }
    return Array.isArray(field) ? { status: 200, body: { stars: field } } : field;
  });
}

async function hintFor(text: string, field: GaiaStar[] | Reply = []): Promise<MoverHint | null> {
  const { api } = backend(field);
  return findMoverWith(await resolveQueryWith(text, api), api);
}

describe("WISE 0855 from the known movers", () => {
  it("finds it at the challenge coordinates without the network", async () => {
    const { api, urls } = backend("network-error");
    const resolved = await resolveQueryWith("08h55m10.831s, -07d14m42.53s", api);
    const hint = await findMoverWith(resolved, api);
    expect(urls).toHaveLength(0);
    expect(hint?.name).toBe("WISE 0855-0714");
    expect(hint?.wasHereYear).toBe(2010);
    expect(hint?.direction).toBe("west");
    expect(hint?.offsetArcsec).toBeGreaterThan(126);
    expect(hint?.offsetArcsec).toBeLessThan(127);
    expect(
      separationArcsec(hint?.now ?? { ra: 0, dec: 0 }, { ra: 133.75977, dec: -7.24218 }),
    ).toBeLessThan(0.5);
    expect(hint?.sentence).toBe("WISE 0855-0714 was here in 2010. It is now 127″ to the west.");
    expect(hint?.source).toContain("Kirkpatrick et al. 2021");
  });

  it("gives the same banner for the name", async () => {
    for (const text of ["WISE 0855", "WISE 0855−0714"]) {
      const hint = await hintFor(text, "network-error");
      expect(hint?.sentence).toBe("WISE 0855-0714 was here in 2010. It is now 127″ to the west.");
    }
  });

  it("is quiet where WISE 0855 is now", async () => {
    expect(await hintFor("133.7598 -7.2422", [])).toBeNull();
  });
});

describe("Gaia DR3 movers through /stars", () => {
  it("names Barnard's Star when the entry was its name", async () => {
    const { api, urls } = backend(BARNARD_FIELD);
    const hint = await findMoverWith(await resolveQueryWith("Barnard's Star", api), api);
    const stars = urls.find((u) => u.pathname === "/stars");
    expect(stars?.searchParams.get("ra")).toBe("269.4520769586187");
    expect(stars?.searchParams.get("dec")).toBe("4.69336496657667");
    expect(stars?.searchParams.get("size")).toBe("8");
    expect(hint?.name).toBe("Barnard's Star");
    expect(hint?.wasHereYear).toBe(2000);
    expect(hint?.direction).toBe("north");
    expect(hint?.offsetArcsec).toBeGreaterThan(269);
    expect(hint?.offsetArcsec).toBeLessThan(271);
    expect(
      separationArcsec(hint?.now ?? { ra: 0, dec: 0 }, { ra: 269.44627, dec: 4.7682 }),
    ).toBeLessThan(0.2);
    expect(hint?.sentence).toBe("Barnard's Star was here in 2000. It is now 270″ to the north.");
    expect(hint?.source).toBe(
      "Gaia DR3 4472832130942575872: position at epoch 2016.0 and proper motion",
    );
  });

  it("calls a typed position's mover a fast-moving star", async () => {
    const hint = await hintFor("269.45208 4.69336", BARNARD_FIELD);
    expect(hint?.name).toBe("Gaia DR3 4472832130942575872");
    expect(hint?.sentence).toBe(
      "A fast-moving star (Gaia DR3 4472832130942575872) was here in 2000. It is now 270″ to the north.",
    );
  });

  it("finds Epsilon Indi B, which Gaia DR3 holds", async () => {
    const hint = await hintFor("Epsilon Indi B", EPS_INDI_FIELD);
    expect(hint?.sentence).toBe(
      "Epsilon Indi B was here in 2000. It is now 122″ to the south-east.",
    );
  });

  it("is quiet at Barnard's Star's position in 2026, and around RW Aurigae", async () => {
    expect(await hintFor("269.4463 4.7682", BARNARD_FIELD)).toBeNull();
    expect(await hintFor("RW Aurigae", RW_AUR_FIELD)).toBeNull();
  });

  it("does not give a typed name to a fast star that only passed nearby", async () => {
    // A name whose catalogue position is 5″ east of Barnard's Star's track in 2000 (synthetic).
    const synthetic: Resolved = {
      query: "synthetic name",
      kind: "name",
      position: {
        ra: 269.4520769586187 + 5 / 3600 / Math.cos((4.69336 * Math.PI) / 180),
        dec: 4.69336496657667,
      },
      readAs: "",
      name: "Synthetic galaxy",
      source: "team-api",
    };
    const hint = await findMoverWith(synthetic, backend(BARNARD_FIELD).api);
    expect(
      hint?.sentence.startsWith("A fast-moving star (Gaia DR3 4472832130942575872) was here in"),
    ).toBe(true);
  });

  it("keeps only stars of 300 mas/yr or more with a proper motion", () => {
    const tracks = gaiaTracks([...BARNARD_FIELD, ...EPS_INDI_FIELD, ...RW_AUR_FIELD]);
    expect(tracks.map((t) => t.catalogueName)).toEqual([
      "Gaia DR3 4472832130942575872",
      "Gaia DR3 6412596012146801152",
    ]);
  });
});

describe("when the catalogue cannot be reached it resolves to null", () => {
  it.each([
    ["502", { status: 502, body: { error: "Gaia query failed" } }],
    ["a network error", "network-error"],
    ["a malformed answer", { status: 200, body: { stars: "none" } }],
    ["an answer that is not JSON", { status: 200 }],
  ] as [string, Reply][])("after %s", async (_, reply) => {
    expect(await hintFor("269.45208 4.69336", reply)).toBeNull();
  });

  it("after the deadline", async () => {
    const { api } = backend("hang");
    const resolved = await resolveQueryWith("269.45208 4.69336", api);
    expect(await findMoverWith(resolved, api, { timeoutMs: 20 })).toBeNull();
  });

  it("when the caller aborts", async () => {
    const { api } = backend("hang");
    const controller = new AbortController();
    const pending = findMoverWith(await resolveQueryWith("269.45208 4.69336", api), api, {
      signal: controller.signal,
    });
    controller.abort();
    expect(await pending).toBeNull();
  });

  it("without a configured backend, asking nothing", async () => {
    const { api, urls } = backend(BARNARD_FIELD);
    const resolved = await resolveQueryWith("269.45208 4.69336", api);
    expect(await findMoverWith(resolved, { ...api, base: null })).toBeNull();
    expect(urls).toHaveLength(0);
  });

  it("through the exported findMover for a position no table entry covers", async () => {
    const resolved = await resolveQueryWith("76.95653 30.40144", {
      ...backend([]).api,
      base: null,
    });
    // With no backend configured in the test build this asks nothing; with one, a failure is null.
    const hint = await findMover(resolved, { signal: AbortSignal.abort() });
    expect(hint).toBeNull();
  });
});

describe("yearOfApproach", () => {
  it("counts an approach within days of a catalogue epoch as that year", () => {
    expect(yearOfApproach(1999.998)).toBe(2000);
    expect(yearOfApproach(2000.004)).toBe(2000);
    expect(yearOfApproach(2010.45)).toBe(2010);
    expect(yearOfApproach(2010.98)).toBe(2010);
    expect(yearOfApproach(1990.0)).toBe(1990);
  });
});

describe("readStarsBody", () => {
  it("drops rows without a position and keeps null proper motions", () => {
    const stars = readStarsBody({
      stars: [
        { id: 1, ra: 10, dec: 20, pmra: null, pmdec: 5, mag: null },
        { id: "2", ra: null, dec: 20, pmra: 1, pmdec: 1, mag: 3 },
        "row",
      ],
    });
    expect(stars).toEqual([{ id: "1", ra: 10, dec: 20, pmra: null, pmdec: 5, mag: null }]);
  });
});
