import { describe, expect, it } from "vitest";
import {
  HINT_WITH_NAMES,
  HINT_WITHOUT_NAMES,
  NAMES_DOWN,
  NAMES_OFF,
  NOT_FOUND,
  RA_RANGE,
} from "./messages";
import { resolveQuery, resolveQueryWith, searchHint } from "./resolve";
import { type TeamApi, teamApiBaseFrom, wakeTeamApi } from "./team-api";
import { type Resolved, SearchError } from "./types";

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

const noNetwork = (): { api: TeamApi; urls: URL[] } =>
  standIn(() => {
    throw new Error("the network must not be used");
  });

async function rejection(promise: Promise<Resolved>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error("resolved instead of rejecting");
}

async function searchError(promise: Promise<Resolved>): Promise<SearchError> {
  const error = await rejection(promise);
  if (!(error instanceof SearchError)) throw error;
  return error;
}

// Answers the local team backend gave on 14 Nov 2026 (src/backend, CDS Sesame behind it).
const BARNARD_ANSWER = { name: "Barnard's Star", ra: 269.4520769586187, dec: 4.69336496657667 };

describe("positions", () => {
  it("reads the brief's coordinates for WISE 0855 without the network", async () => {
    const { api, urls } = noNetwork();
    const r = await resolveQueryWith("08h55m10.831s, -07d14m42.53s", api);
    expect(r).toMatchObject({
      query: "08h55m10.831s, -07d14m42.53s",
      kind: "sexagesimal",
      readAs: "Read as RA 133.79513°, Dec −7.24515°.",
      name: null,
      source: "typed",
    });
    expect(urls).toHaveLength(0);
  });

  it("keeps the entry exactly as typed", async () => {
    const r = await resolveQueryWith("  133.7599 −7.2418 ", noNetwork().api);
    expect(r.query).toBe("  133.7599 −7.2418 ");
    expect(r.kind).toBe("degrees");
    expect(r.position).toEqual({ ra: 133.7599, dec: -7.2418 });
    expect(r.readAs).toBe("Read as RA 133.75990°, Dec −7.24180°.");
  });

  it("works through the exported resolveQuery, with no backend at all", async () => {
    const r = await resolveQuery("08:55:10.831 -07:14:42.53");
    expect(r.readAs).toBe("Read as RA 133.79513°, Dec −7.24515°.");
  });

  it("passes range errors on", async () => {
    const error = await searchError(resolveQueryWith("361 10", noNetwork().api));
    expect(error.code).toBe("range");
    expect(error.message).toBe(RA_RANGE);
  });

  it("answers an empty entry with the hint", async () => {
    const error = await searchError(resolveQueryWith("   ", noNetwork().api));
    expect(error.code).toBe("empty");
    expect(error.message).toBe(HINT_WITH_NAMES);
  });
});

describe("WISE 0855 from the known movers", () => {
  it.each(["WISE 0855", "WISE 0855-0714", "WISE 0855−0714", "wise0855", " WISE J0855-0714 "])(
    "%s resolves to its catalogue position, with or without a backend",
    async (text) => {
      for (const api of [noNetwork().api, { ...noNetwork().api, base: null }]) {
        const r = await resolveQueryWith(text, api);
        expect(r).toMatchObject({
          kind: "name",
          name: "WISE 0855-0714",
          source: "known-movers",
          readAs: "Read as RA 133.79513°, Dec −7.24515°.",
        });
      }
    },
  );
});

describe("names through the team backend", () => {
  it("looks a name up and reads its catalogue position", async () => {
    const { api, urls } = standIn(() => ({ status: 200, body: BARNARD_ANSWER }));
    const r = await resolveQueryWith("Barnard's Star", api);
    expect(r).toEqual({
      query: "Barnard's Star",
      kind: "name",
      position: { ra: BARNARD_ANSWER.ra, dec: BARNARD_ANSWER.dec },
      readAs: "Read as RA 269.45208°, Dec 4.69336°.",
      name: "Barnard's Star",
      source: "team-api",
    });
    expect(urls).toHaveLength(1);
    expect(urls[0]?.origin + (urls[0]?.pathname ?? "")).toBe(`${BASE}/resolve`);
    expect(urls[0]?.searchParams.get("q")).toBe("Barnard's Star");
  });

  it("sends a hyphen for a true minus and a straight apostrophe for a curly one", async () => {
    const { api, urls } = standIn(() => ({ status: 404, body: { error: "not found" } }));
    await rejection(resolveQueryWith("  2MASS J0415−0935 ", api));
    await rejection(resolveQueryWith("Barnard’s   Star", api));
    expect(urls.map((u) => u.searchParams.get("q"))).toEqual([
      "2MASS J0415-0935",
      "Barnard's Star",
    ]);
  });

  it("says when a name is not found, in the design's words", async () => {
    const { api } = standIn(() => ({ status: 404, body: { error: "Could not find" } }));
    const error = await searchError(resolveQueryWith("Planet X", api));
    expect(error.code).toBe("not_found");
    expect(error.message).toBe(NOT_FOUND);
    expect(error.message).toBe(
      "No object of that name was found. Try Barnard's Star, or a position such as 133.7599 -7.2418.",
    );
  });

  it.each([
    ["502", { status: 502, body: { error: "upstream" } }],
    ["503", { status: 503, body: { error: "busy" } }],
    ["500", { status: 500, body: { error: "Internal server error" } }],
    ["a network error", "network-error"],
    ["an answer without a position", { status: 200, body: { name: "x", ra: "1", dec: 2 } }],
    ["an answer that is not JSON", { status: 200 }],
  ] as [string, Reply][])("says names cannot be looked up right now after %s", async (_, reply) => {
    const { api } = standIn(() => reply);
    const error = await searchError(resolveQueryWith("Barnard's Star", api));
    expect(error.code).toBe("unavailable");
    expect(error.message).toBe(NAMES_DOWN);
  });

  it("gives up when no answer comes in time", async () => {
    const { api } = standIn(() => "hang");
    const error = await searchError(resolveQueryWith("Barnard's Star", api, { timeoutMs: 20 }));
    expect(error.code).toBe("unavailable");
  });

  it("rejects with the abort, not a SearchError, when the caller cancels", async () => {
    const { api } = standIn(() => "hang");
    const controller = new AbortController();
    const pending = rejection(
      resolveQueryWith("Barnard's Star", api, { signal: controller.signal }),
    );
    controller.abort();
    const error = await pending;
    expect(error).not.toBeInstanceOf(SearchError);
    expect((error as DOMException).name).toBe("AbortError");
    const already = await rejection(resolveQueryWith("M31", api, { signal: controller.signal }));
    expect(already).not.toBeInstanceOf(SearchError);
  });

  it("says names cannot be looked up on this site when no backend is configured", async () => {
    const { api, urls } = noNetwork();
    const error = await searchError(resolveQueryWith("Barnard's Star", { ...api, base: null }));
    expect(error.code).toBe("unavailable");
    expect(error.message).toBe(NAMES_OFF);
    expect(urls).toHaveLength(0);
  });
});

describe("solar-system names", () => {
  it.each([
    ["Pluto", "Pluto"],
    ["pluto", "Pluto"],
    ["134340 Pluto", "Pluto"],
    ["Mars", "Mars"],
    ["the Moon", "The Moon"],
    ["(433) Eros", "Eros"],
    ["3I/ATLAS", "3I/ATLAS"],
    ["1P/Halley", "1P/Halley"],
    ["67P", "67P"],
    ["C/2023 A3", "C/2023 A3"],
    ["2024 YR4", "2024 YR4"],
    ["comet Halley", "Comet Halley"],
  ])("%s gets its own sentence without a network call", async (text, subject) => {
    const { api, urls } = noNetwork();
    const error = await searchError(resolveQueryWith(text, api));
    expect(error.code).toBe("solar_system");
    expect(error.message).toBe(
      `${subject} moves too fast to stay in one patch of sky between visits. Try a star, such as Barnard's Star.`,
    );
    expect(urls).toHaveLength(0);
  });

  it("offers a position instead when names cannot be looked up", async () => {
    const error = await searchError(resolveQueryWith("Pluto", { ...noNetwork().api, base: null }));
    expect(error.message).toBe(
      "Pluto moves too fast to stay in one patch of sky between visits. Try a position such as 133.7599 -7.2418.",
    );
  });

  it.each(["61 Cyg", "3C 273", "Planet X", "Epsilon Indi B"])(
    "%s is not taken for one",
    async (text) => {
      const { api, urls } = standIn(() => ({ status: 404 }));
      const error = await searchError(resolveQueryWith(text, api));
      expect(error.code).toBe("not_found");
      expect(urls).toHaveLength(1);
    },
  );
});

describe("configuration", () => {
  it("offers only the forms that work", () => {
    expect(searchHint(true)).toBe(
      "Try 133.7599 -7.2418, 08h55m10.831s -07d14m42.53s or Barnard's Star.",
    );
    expect(searchHint(false)).toBe("Try 133.7599 -7.2418 or 08h55m10.831s -07d14m42.53s.");
    expect(searchHint(false)).toBe(HINT_WITHOUT_NAMES);
  });

  it("reads the team address without its trailing slash", () => {
    expect(teamApiBaseFrom("https://team.example/")).toBe("https://team.example");
    expect(teamApiBaseFrom(" https://team.example// ")).toBe("https://team.example");
    expect(teamApiBaseFrom("")).toBeNull();
    expect(teamApiBaseFrom("   ")).toBeNull();
    expect(teamApiBaseFrom(undefined)).toBeNull();
  });

  it("wakes a sleeping backend through /health, and never rejects", async () => {
    const awake = standIn(() => ({ status: 200, body: { status: "ok" } }));
    expect(await wakeTeamApi(awake.api)).toBe(true);
    expect(awake.urls.map((u) => u.href)).toEqual([`${BASE}/health`]);
    expect(await wakeTeamApi(standIn(() => "network-error").api)).toBe(false);
    const none = noNetwork();
    expect(await wakeTeamApi({ ...none.api, base: null })).toBe(false);
    expect(none.urls).toHaveLength(0);
  });
});
