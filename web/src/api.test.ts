import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  checkFrames,
  checkRequest,
  engineUrl,
  FieldError,
  type FieldErrorCode,
  type FieldRequest,
  fieldUrl,
  isEngineOrigin,
  type LoadProgress,
  loadBundledField,
  loadField,
  loadOverlays,
  loadRecordedOverlays,
  loadRecordedSpectrum,
  loadSpectrum,
  loadStatus,
  type MeasureProgress,
  type RecordedAnswer,
  spectrumUrl,
} from "./api";
import type { Manifest } from "./contract";

// A minimal manifest for exercising the loader: a 2 x 2 grid and one plane, so the frame file
// is 8 bytes. It describes no real sky; only lengths and statuses matter here.
const synthetic_manifest: Manifest = {
  contract: "1.0",
  status: "ready",
  key: "0123456789abcdef",
  request: { ra: 10, dec: 20, fov_arcmin: 6 },
  centre: { ra: 10, dec: 20 },
  epoch_ref: 2026.0,
  grid: {
    nx: 2,
    ny: 2,
    cx: 0.5,
    cy: 0.5,
    pixscale_arcsec: 3.075,
    projection: "TAN",
    row0: "north",
    col0: "east",
  },
  time_binning: { gap_days: 20, max_span_days: 60, sub_span_days: 30 },
  time_bins: [
    {
      id: 0,
      mjd_start: 60979,
      mjd_end: 60993,
      mjd_mid: 60986,
      date_start: "2025-10-31",
      date_end: "2025-11-14",
      n_exposures: 9,
      detectors: [6],
    },
  ],
  wave_bins: [],
  planes: [
    {
      index: 0,
      kind: "sci",
      mission: "SPHEREx",
      time_bin: 0,
      wave_bin: 20,
      band: null,
      lam_min: 4.412,
      lam_max: 4.5595,
      lam_eff: 4.49,
      n_exposures: 9,
      sigma: 0.02,
      mjd_mid: 60986,
      date_start: "2025-10-31",
      date_end: "2025-11-14",
      offset: 0,
    },
  ],
  frames: {
    url: "/api/fields/0123456789abcdef/frames.bin",
    dtype: "float16",
    byteorder: "little",
    nbytes: 8,
    sha256: "",
  },
  exposures: {
    found: 9,
    used: 9,
    sampled: false,
    collections: { spherex_dr1: 9 },
    newest_mjd: 60993,
    newest_date: "2025-11-14",
  },
  provenance: { pipeline_version: "test", built_at: "", data_dois: [], notes: [] },
  warnings: [],
};

const synthetic_frames = () => new ArrayBuffer(8);

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

const binary = (buffer: ArrayBuffer) =>
  new Response(buffer, { headers: { "Content-Type": "application/octet-stream" } });

const html = (status = 200) =>
  new Response("<!doctype html><title>Not the API</title>", {
    status,
    headers: { "Content-Type": "text/html" },
  });

const building = (stage: string, done: number, total: number, retryAfterS = 1) =>
  json(
    {
      contract: "1.0",
      status: "building",
      progress: { stage, done, total },
      retry_after_s: retryAfterS,
    },
    202,
  );

const apiError = (status: number, code: string, message: string, headers = {}) =>
  json({ contract: "1.0", status: "error", code, message }, status, headers);

/** What web/functions/api answers when it cannot reach the API: the contract's 503, flagged. */
const proxyError = (reason: string) =>
  apiError(503, "upstream_unavailable", "The API cannot be reached right now.", {
    "x-tombaugh-proxy-error": reason,
  });

type Handler = (url: string, call: number) => Response | Promise<Response>;

/** A stand-in for fetch that records the URLs asked for, plus a sleep that returns at once. */
function harness(handler: Handler) {
  const urls: string[] = [];
  const sleeps: number[] = [];
  const progress: LoadProgress[] = [];
  const fetchImpl: typeof fetch = async (input) => {
    const url = String(input);
    urls.push(url);
    return handler(url, urls.length);
  };
  const options = {
    fetchImpl,
    // The page and the engine share one origin unless a test says otherwise.
    engine: "",
    sleep: async (ms: number) => {
      sleeps.push(ms);
    },
    onProgress: (step: LoadProgress) => {
      progress.push(step);
    },
  };
  return { urls, sleeps, progress, options };
}

const offline: Handler = () => {
  throw new TypeError("fetch failed");
};

async function failure(promise: Promise<unknown>): Promise<FieldError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(FieldError);
    return error as FieldError;
  }
  throw new Error("expected the load to fail");
}

describe("fieldUrl", () => {
  it("asks for a position with ra, dec and fov", () => {
    expect(fieldUrl({ ra: 133.7599, dec: -7.2418, fov: 6 })).toBe(
      "/api/fields?ra=133.7599&dec=-7.2418&fov=6",
    );
  });

  it("asks for a recorded field by name", () => {
    expect(fieldUrl({ fixture: "wise0855" })).toBe("/api/fields?fixture=wise0855");
  });
});

describe("checkRequest", () => {
  it("accepts the whole sky and every allowed field of view", () => {
    for (const fov of [3, 4, 5, 6, 8, 10]) {
      expect(() => checkRequest({ ra: 0, dec: -90, fov })).not.toThrow();
      expect(() => checkRequest({ ra: 359.9999, dec: 90, fov })).not.toThrow();
    }
    expect(() => checkRequest({ fixture: "barnard" })).not.toThrow();
  });

  it.each<[FieldRequest, string]>([
    [{ ra: -0.1, dec: 0, fov: 6 }, "Right ascension"],
    [{ ra: 360.5, dec: 0, fov: 6 }, "Right ascension"],
    [{ ra: Number.NaN, dec: 0, fov: 6 }, "Right ascension"],
    [{ ra: 10, dec: 90.01, fov: 6 }, "Declination"],
    [{ ra: 10, dec: Number.NaN, fov: 6 }, "Declination"],
    [{ ra: 10, dec: 0, fov: 7 }, "Field of view"],
    [{ ra: 10, dec: 0, fov: 60 }, "Field of view"],
    [{ fixture: "../secrets" }, "recorded field"],
    [{ fixture: "" }, "recorded field"],
  ])("rejects %j", (request, what) => {
    expect(() => checkRequest(request)).toThrow(FieldError);
    expect(() => checkRequest(request)).toThrow(what);
  });

  it("stops a bad request before any network call", async () => {
    const { urls, options } = harness(offline);
    const error = await failure(loadField({ ra: 400, dec: 0, fov: 6 }, options));
    expect(error.code).toBe("bad_request");
    expect(urls).toEqual([]);
  });
});

describe("loadField from the API", () => {
  it("polls the same URL while the API answers 202, reporting progress", async () => {
    const { urls, sleeps, progress, options } = harness((url, call) => {
      if (url.endsWith("frames.bin")) return binary(synthetic_frames());
      if (call === 1) return building("discover", 0, 0);
      if (call === 2) return building("fetch", 120, 258, 2);
      if (call === 3) return building("stack", 258, 258, 0.5);
      return json(synthetic_manifest);
    });
    const field = await loadField({ ra: 10, dec: 20, fov: 6 }, options);

    const fields = "/api/fields?ra=10&dec=20&fov=6";
    expect(urls).toEqual([
      fields,
      fields,
      fields,
      fields,
      "/api/fields/0123456789abcdef/frames.bin",
    ]);
    expect(sleeps).toEqual([1000, 2000, 500]);
    expect(progress).toEqual([
      { stage: "discover", done: 0, total: 0 },
      { stage: "fetch", done: 120, total: 258 },
      { stage: "stack", done: 258, total: 258 },
      { stage: "frames", done: null, total: 8 },
    ]);
    expect(field.source).toBe("api");
    expect(field.manifest.key).toBe("0123456789abcdef");
    expect(field.frames?.byteLength).toBe(8);
  });

  it("fetches the frame file at the manifest's URL as it is, version query included", async () => {
    // The API writes the first 16 hex characters of the file's SHA-256 into the URL: the file is
    // cached as immutable, so other bytes must have another address.
    const { frames } = synthetic_manifest;
    if (!frames) throw new Error("the synthetic manifest has a frame file");
    const versioned = `${frames.url}?v=00112233445566ff`;
    const manifest: Manifest = { ...synthetic_manifest, frames: { ...frames, url: versioned } };
    const { urls, options } = harness((url) =>
      url.startsWith("/api/fields/") ? binary(synthetic_frames()) : json(manifest),
    );
    const field = await loadField({ fixture: "wise0855" }, options);
    expect(urls).toEqual(["/api/fields?fixture=wise0855", versioned]);
    expect(field.frames?.byteLength).toBe(8);
  });

  it("keeps the poll interval within sensible bounds", async () => {
    const { sleeps, options } = harness((url, call) => {
      if (url.endsWith("frames.bin")) return binary(synthetic_frames());
      if (call === 1) return building("fetch", 1, 9, 600);
      if (call === 2) return building("fetch", 2, 9, 0);
      if (call === 3) return building("fetch", 3, 9, 0.001);
      return json(synthetic_manifest);
    });
    await loadField({ ra: 10, dec: 20, fov: 6 }, options);
    expect(sleeps).toEqual([5000, 1000, 200]);
  });

  it("gives up when a build never finishes", async () => {
    let clock = 0;
    const { options } = harness(() => building("fetch", 1, 9));
    const error = await failure(
      loadField(
        { ra: 10, dec: 20, fov: 6 },
        {
          ...options,
          now: () => clock,
          sleep: async (ms) => {
            clock += ms;
          },
        },
      ),
    );
    expect(error.code).toBe("timeout");
    expect(clock).toBeGreaterThan(180_000);
  });

  it("returns an empty field as a normal answer, without asking for frames", async () => {
    const empty = {
      ...synthetic_manifest,
      status: "empty",
      planes: [],
      time_bins: [],
      frames: null,
    };
    const { urls, options } = harness(() => json(empty));
    const field = await loadField({ ra: 10, dec: 20, fov: 6 }, options);
    expect(field.manifest.status).toBe("empty");
    expect(field.frames).toBeNull();
    expect(urls).toHaveLength(1);
  });

  it("passes a partial field through with its warnings", async () => {
    const partial = { ...synthetic_manifest, status: "partial", warnings: ["detector 3 missing"] };
    const { options } = harness((url) =>
      url.endsWith("frames.bin") ? binary(synthetic_frames()) : json(partial),
    );
    const field = await loadField({ ra: 10, dec: 20, fov: 6 }, options);
    expect(field.manifest.status).toBe("partial");
    expect(field.manifest.warnings).toEqual(["detector 3 missing"]);
    expect(field.frames?.byteLength).toBe(8);
  });

  it.each<[number, FieldErrorCode]>([
    [400, "bad_request"],
    [404, "not_found"],
    [429, "busy"],
    [503, "upstream_unavailable"],
    [500, "internal"],
  ])("turns HTTP %i into a FieldError with code %s", async (status, code) => {
    const { options } = harness(() => apiError(status, code, `the API said ${code}`));
    const error = await failure(loadField({ ra: 10, dec: 20, fov: 6 }, options));
    expect(error.code).toBe(code);
    expect(error.message).toBe(`the API said ${code}`);
  });

  it("reports how long to wait when the API is busy", async () => {
    const { options } = harness(() => apiError(429, "busy", "queue full", { "Retry-After": "7" }));
    const error = await failure(loadField({ ra: 10, dec: 20, fov: 6 }, options));
    expect(error.code).toBe("busy");
    expect(error.retryAfterS).toBe(7);
  });

  it("falls back on the HTTP status when the error body has no known code", async () => {
    const { options } = harness(() => json({ contract: "1.0", status: "error" }, 503));
    const error = await failure(loadField({ ra: 10, dec: 20, fov: 6 }, options));
    expect(error.code).toBe("upstream_unavailable");
    expect(error.message).toMatch(/archive/);
  });

  it("rejects a frame file whose length differs from the manifest", async () => {
    const { options } = harness((url) =>
      url.endsWith("frames.bin") ? binary(new ArrayBuffer(6)) : json(synthetic_manifest),
    );
    const error = await failure(loadField({ ra: 10, dec: 20, fov: 6 }, options));
    expect(error.code).toBe("bad_frames");
    expect(error.message).toMatch(/6 bytes/);
  });

  it("rejects a manifest from a contract it does not understand", async () => {
    const { options } = harness(() => json({ ...synthetic_manifest, contract: "2.0" }));
    const error = await failure(loadField({ ra: 10, dec: 20, fov: 6 }, options));
    expect(error.code).toBe("bad_response");
  });

  it("rejects a grid that is not north-up and east-left", async () => {
    const flipped = { ...synthetic_manifest, grid: { ...synthetic_manifest.grid, row0: "south" } };
    const { options } = harness(() => json(flipped));
    const error = await failure(loadField({ ra: 10, dec: 20, fov: 6 }, options));
    expect(error.code).toBe("bad_response");
  });

  it("says the API is unreachable for a position, after three attempts", async () => {
    const { urls, sleeps, options } = harness(offline);
    const error = await failure(loadField({ ra: 10, dec: 20, fov: 6 }, options));
    expect(error.code).toBe("unreachable");
    expect(urls).toHaveLength(3);
    expect(sleeps).toEqual([300, 900]);
  });

  it("tells the site proxy's own 503 from the API's: the first means unreachable", async () => {
    const viaProxy = harness(() => proxyError("origin_unreachable"));
    const proxyFailure = await failure(loadField({ ra: 10, dec: 20, fov: 6 }, viaProxy.options));
    expect(proxyFailure.code).toBe("unreachable");

    const fromApi = harness(() => apiError(503, "upstream_unavailable", "IRSA is down"));
    const apiFailure = await failure(loadField({ ra: 10, dec: 20, fov: 6 }, fromApi.options));
    expect(apiFailure.code).toBe("upstream_unavailable");
    expect(apiFailure.message).toBe("IRSA is down");
  });

  it("recovers when only the first attempt fails to connect", async () => {
    const { urls, options } = harness((url, call) => {
      if (call === 1) throw new TypeError("connection reset");
      return url.endsWith("frames.bin") ? binary(synthetic_frames()) : json(synthetic_manifest);
    });
    const field = await loadField({ ra: 10, dec: 20, fov: 6 }, options);
    expect(field.source).toBe("api");
    expect(urls).toHaveLength(3);
  });

  it("stops at once when aborted, without falling back", async () => {
    const controller = new AbortController();
    const { urls, options } = harness(() => {
      controller.abort();
      throw new DOMException("The operation was aborted.", "AbortError");
    });
    await expect(
      loadField({ fixture: "wise0855" }, { ...options, signal: controller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(urls).toHaveLength(1);
  });
});

describe("loadField for a recorded field", () => {
  const bundledManifest = "/fixtures/wise0855/manifest.json";
  const bundledFrames = "/fixtures/wise0855/frames.bin";

  it("uses the API when it answers", async () => {
    const { urls, options } = harness((url) =>
      url.endsWith("frames.bin") ? binary(synthetic_frames()) : json(synthetic_manifest),
    );
    const field = await loadField({ fixture: "wise0855" }, options);
    expect(field.source).toBe("api");
    expect(urls).toEqual([
      "/api/fields?fixture=wise0855",
      "/api/fields/0123456789abcdef/frames.bin",
    ]);
  });

  it("falls back to the bundled copy when the API cannot be reached", async () => {
    const { urls, options } = harness((url) => {
      if (url.startsWith("/api/")) throw new TypeError("fetch failed");
      return url === bundledManifest ? json(synthetic_manifest) : binary(synthetic_frames());
    });
    const field = await loadField({ fixture: "wise0855" }, options);
    expect(field.source).toBe("bundled");
    expect(field.frames?.byteLength).toBe(8);
    // Three attempts at the API, then the bundled manifest and the bundled frame file,
    // not the API URL written inside the recorded manifest.
    expect(urls.slice(3)).toEqual([bundledManifest, bundledFrames]);
  });

  it.each<[string, () => Response]>([
    ["an HTML page with status 200 (static host)", () => html(200)],
    ["a 404 page (static host)", () => html(404)],
    ["a proxy error (no back end running)", () => new Response("ECONNREFUSED", { status: 500 })],
    ["the site's own proxy saying the API does not answer", () => proxyError("origin_unreachable")],
    ["the site's own proxy with no API address", () => proxyError("origin_not_configured")],
  ])("treats %s on /api as an unreachable API", async (_what, answer) => {
    const { options } = harness((url) => {
      if (url.startsWith("/api/")) return answer();
      return url === bundledManifest ? json(synthetic_manifest) : binary(synthetic_frames());
    });
    const field = await loadField({ fixture: "wise0855" }, options);
    expect(field.source).toBe("bundled");
  });

  it("says so when the recorded field is not bundled either", async () => {
    const { options } = harness((url) => (url.startsWith("/api/") ? html(404) : html(200)));
    const error = await failure(loadField({ fixture: "barnard" }, options));
    expect(error.code).toBe("fixture_missing");
    expect(error.message).toMatch(/barnard/);
  });

  it("says so when nothing answers at all", async () => {
    const { options } = harness(offline);
    const error = await failure(loadField({ fixture: "barnard" }, options));
    expect(error.code).toBe("fixture_missing");
  });

  it("does not fall back when the API itself says the fixture is unknown", async () => {
    const { urls, options } = harness(() => apiError(404, "not_found", "unknown fixture"));
    const error = await failure(loadField({ fixture: "nosuchfield" }, options));
    expect(error.code).toBe("not_found");
    expect(urls).toEqual(["/api/fields?fixture=nosuchfield"]);
  });

  it("checks the bundled frame file against its manifest too", async () => {
    const { options } = harness((url) => {
      if (url.startsWith("/api/")) return html(404);
      return url === bundledManifest ? json(synthetic_manifest) : binary(new ArrayBuffer(4));
    });
    const error = await failure(loadField({ fixture: "wise0855" }, options));
    expect(error.code).toBe("bad_frames");
  });
});

describe("checkFrames", () => {
  it("accepts a file of exactly planes x ny x nx x 2 bytes", () => {
    expect(() => checkFrames(synthetic_manifest, new ArrayBuffer(8))).not.toThrow();
  });

  it("rejects a manifest whose byte count disagrees with its planes", () => {
    const inconsistent: Manifest = {
      ...synthetic_manifest,
      frames: { url: "", dtype: "float16", byteorder: "little", nbytes: 16, sha256: "" },
    };
    expect(() => checkFrames(inconsistent, new ArrayBuffer(16))).toThrow(/1 planes of 2 x 2/);
  });
});

describe("the engine's address", () => {
  it("keeps /api paths on the page's own origin by default", () => {
    expect(engineUrl("/api/fields?fixture=wise0855", "")).toBe("/api/fields?fixture=wise0855");
  });

  it("puts /api paths on VITE_ENGINE_URL when it is set", () => {
    expect(engineUrl("/api/status", "https://engine.example")).toBe(
      "https://engine.example/api/status",
    );
    expect(engineUrl("/api/status", "https://engine.example/")).toBe(
      "https://engine.example/api/status",
    );
  });

  it("leaves full URLs and other paths as they are", () => {
    expect(engineUrl("https://other.example/x", "https://engine.example")).toBe(
      "https://other.example/x",
    );
    expect(engineUrl("//cdn.example/x", "https://engine.example")).toBe("//cdn.example/x");
    expect(engineUrl("fixtures/a.json", "https://engine.example")).toBe("fixtures/a.json");
  });

  it("loads the manifest and the frame file from the engine, the bundled copy from the page", async () => {
    const { urls, options } = harness((url) =>
      url.endsWith("frames.bin") ? binary(synthetic_frames()) : json(synthetic_manifest),
    );
    await loadField({ ra: 10, dec: 20, fov: 6 }, { ...options, engine: "https://engine.example" });
    expect(urls).toEqual([
      "https://engine.example/api/fields?ra=10&dec=20&fov=6",
      "https://engine.example/api/fields/0123456789abcdef/frames.bin",
    ]);

    const offlineEngine = harness((url) => {
      if (url.startsWith("https://engine.example/")) throw new TypeError("fetch failed");
      return url.endsWith("manifest.json") ? json(synthetic_manifest) : binary(synthetic_frames());
    });
    const field = await loadField(
      { fixture: "wise0855" },
      { ...offlineEngine.options, engine: "https://engine.example" },
    );
    expect(field.source).toBe("bundled");
    expect(offlineEngine.urls.slice(3)).toEqual([
      "/fixtures/wise0855/manifest.json",
      "/fixtures/wise0855/frames.bin",
    ]);
  });
});

describe("loadStatus", () => {
  const status = {
    contract: "1.0",
    status: "ok",
    pipeline_version: "0.2.0",
    newest_exposure: { mjd: 61318.0, date: "2026-10-05" },
    upstreams: {},
    cache: { used_mb: 1, free_mb: 2 },
    builds: { active: 0, queued: 0 },
  };

  it("returns the engine's status", async () => {
    const { urls, options } = harness(() => json(status));
    const answer = await loadStatus(options);
    expect(answer?.newest_exposure.date).toBe("2026-10-05");
    expect(urls).toEqual(["/api/status"]);
  });

  it("asks the configured engine", async () => {
    const { urls, options } = harness(() => json(status));
    await loadStatus({ ...options, engine: "https://engine.example" });
    expect(urls).toEqual(["https://engine.example/api/status"]);
  });

  it.each<[string, Handler]>([
    ["nothing answers", offline],
    ["a static host's HTML page", () => html(200)],
    ["a 404 page", () => html(404)],
    ["the site's own proxy", () => proxyError("origin_unreachable")],
    ["an error from the API", () => apiError(500, "internal", "broken")],
  ])("resolves to null when %s, after one attempt", async (_what, handler) => {
    const { urls, options } = harness(handler);
    expect(await loadStatus(options)).toBeNull();
    expect(urls).toHaveLength(1);
  });

  it("rejects when aborted", async () => {
    const controller = new AbortController();
    const { options } = harness(() => {
      controller.abort();
      throw new DOMException("The operation was aborted.", "AbortError");
    });
    await expect(loadStatus({ ...options, signal: controller.signal })).rejects.toMatchObject({
      name: "AbortError",
    });
  });
});

describe("loadBundledField", () => {
  it("takes the bundled copy without asking the engine", async () => {
    const { urls, options } = harness((url) =>
      url.endsWith("manifest.json") ? json(synthetic_manifest) : binary(synthetic_frames()),
    );
    const field = await loadBundledField("wise0855", options);
    expect(field.source).toBe("bundled");
    expect(urls).toEqual(["/fixtures/wise0855/manifest.json", "/fixtures/wise0855/frames.bin"]);
  });

  it("says so when the recorded field is not bundled", async () => {
    const { options } = harness(() => html(404));
    const error = await failure(loadBundledField("barnard", options));
    expect(error.code).toBe("fixture_missing");
  });

  it("refuses a name that is not a recorded field's", async () => {
    const { urls, options } = harness(offline);
    const error = await failure(loadBundledField("../x", options));
    expect(error.code).toBe("bad_request");
    expect(urls).toEqual([]);
  });
});

/** The harness's options without its build-progress callback (the extras report their own). */
const quiet = ({ onProgress: _progress, ...rest }: ReturnType<typeof harness>["options"]) => rest;

// The shapes of sections 7.1 and 7.3, with no sources and no points: only statuses matter here.
const synthetic_overlays = {
  contract: "1.0",
  status: "ok",
  gaia: [],
  catwise: [],
  upstreams: { gaia: "ok", catwise: "stale" },
};

const synthetic_spectrum = {
  contract: "1.0",
  status: "ok",
  state: "no_data",
  target: { ra: 10, dec: 20 },
  neighbours: [],
  method: {
    kind: "aperture",
    radius_px: 2,
    encircled_energy: 0.9,
    annulus_px: [5, 9],
    systematic_floor: 0.03,
  },
  time_span: null,
  points: [],
  binned: [],
};

describe("loadOverlays", () => {
  it("asks the engine for the field's catalogue sources", async () => {
    const { urls, options } = harness(() => json(synthetic_overlays));
    const answer = await loadOverlays("0123456789abcdef", {
      ...quiet(options),
      engine: "https://e.x",
    });
    expect(urls).toEqual(["https://e.x/api/fields/0123456789abcdef/overlays"]);
    expect(answer.upstreams).toEqual({ gaia: "ok", catwise: "stale" });
  });

  it("polls while the engine answers 202", async () => {
    const { urls, options } = harness((_url, call) =>
      call === 1 ? building("discover", 0, 1) : json(synthetic_overlays),
    );
    await loadOverlays("0123456789abcdef", quiet(options));
    expect(urls).toHaveLength(2);
  });

  it("carries the engine's code and sentence when the route is missing", async () => {
    const { options } = harness(() =>
      apiError(404, "not_found", "The overlays endpoint is not built yet."),
    );
    const error = await failure(loadOverlays("0123456789abcdef", quiet(options)));
    expect(error.code).toBe("not_found");
    expect(error.message).toBe("The overlays endpoint is not built yet.");
  });

  it("says the engine is unreachable when nothing that speaks the contract answers", async () => {
    const { options } = harness(() => html(502));
    expect((await failure(loadOverlays("0123456789abcdef", quiet(options)))).code).toBe(
      "unreachable",
    );
    const offlineRun = harness(offline);
    const error = await failure(loadOverlays("0123456789abcdef", quiet(offlineRun.options)));
    expect(error.code).toBe("unreachable");
  });

  it("refuses an answer of another shape, and a key that is not a key", async () => {
    const { options } = harness(() => json({ contract: "1.0", status: "ok", gaia: [] }));
    expect((await failure(loadOverlays("0123456789abcdef", quiet(options)))).code).toBe(
      "bad_response",
    );
    const { urls, options: none } = harness(() => json(synthetic_overlays));
    expect((await failure(loadOverlays("../status", quiet(none)))).code).toBe("bad_request");
    expect(urls).toEqual([]);
  });
});

describe("loadSpectrum", () => {
  it("asks for the position inside the field", async () => {
    expect(spectrumUrl("abc", 133.75977, -7.2418)).toBe(
      "/api/fields/abc/spectrum?ra=133.75977&dec=-7.2418",
    );
    const { urls, options } = harness(() => json(synthetic_spectrum));
    const answer = await loadSpectrum("abc", 133.75977, -7.2418, quiet(options));
    expect(urls).toEqual(["/api/fields/abc/spectrum?ra=133.75977&dec=-7.2418"]);
    expect(answer.state).toBe("no_data");
  });

  it("reports how far a measurement got while the engine answers 202", async () => {
    const steps: MeasureProgress[] = [];
    const { options } = harness((_url, call) =>
      call === 1 ? building("fetch", 120, 258) : json(synthetic_spectrum),
    );
    await loadSpectrum("abc", 1, 2, { ...quiet(options), onProgress: (step) => steps.push(step) });
    expect(steps).toEqual([{ done: 120, total: 258 }]);
  });

  it("refuses a state the contract does not name, and a position off the sky", async () => {
    const { options } = harness(() => json({ ...synthetic_spectrum, state: "great" }));
    expect((await failure(loadSpectrum("abc", 1, 2, quiet(options)))).code).toBe("bad_response");
    expect((await failure(loadSpectrum("abc", 361, 2, quiet(options)))).code).toBe("bad_request");
  });

  it("passes the engine's X-Tombaugh-Incomplete header on with the answer", async () => {
    const { options } = harness(() =>
      json(synthetic_spectrum, 200, {
        "X-Tombaugh-Incomplete": "12 of 258 exposures not measured; not cached",
      }),
    );
    const answer = await loadSpectrum("abc", 1, 2, quiet(options));
    expect(answer.incomplete).toBe("12 of 258 exposures not measured; not cached");
    const whole = await loadSpectrum(
      "abc",
      1,
      2,
      quiet(harness(() => json(synthetic_spectrum)).options),
    );
    expect(whole.incomplete).toBeUndefined();
  });
});

describe("where a frame file may come from", () => {
  it("allows the page's own origin and the configured engine, nothing else", () => {
    const page = "https://tombaugh.example/look/?target=wise0855";
    expect(isEngineOrigin("/api/fields/k/frames.bin?v=1", "", page)).toBe(true);
    expect(isEngineOrigin("frames.bin", "", page)).toBe(true);
    expect(isEngineOrigin("https://tombaugh.example/api/x", "", page)).toBe(true);
    expect(isEngineOrigin("https://engine.example/api/x", "https://engine.example", page)).toBe(
      true,
    );
    expect(isEngineOrigin("https://other.example/x", "https://engine.example", page)).toBe(false);
    expect(isEngineOrigin("//cdn.example/x", "https://engine.example", page)).toBe(false);
    expect(isEngineOrigin("https://other.example/x", "", null)).toBe(false);
  });

  it("judges an address by how the browser reads it, not by how it looks", () => {
    const page = "https://tombaugh.example/look/?target=wise0855";
    // Each of these looks like a path or like nothing at all, and the URL parser takes every one
    // of them to other.example: a backslash counts as a slash, leading spaces and control
    // characters are dropped, and tabs and line breaks are removed wherever they are.
    const disguised = [
      "/\\other.example/frames.bin",
      "\\\\other.example/frames.bin",
      "\\/other.example/frames.bin",
      " //other.example/frames.bin",
      "\t//other.example/frames.bin",
      "/\t/other.example/frames.bin",
      "ht\ntp://other.example/frames.bin",
      "\u0001https://other.example/frames.bin",
    ];
    for (const url of disguised) {
      expect(new URL(url, page).hostname, url).toBe("other.example");
      expect(isEngineOrigin(url, "", page), url).toBe(false);
      expect(isEngineOrigin(url, "https://engine.example", page), url).toBe(false);
      expect(isEngineOrigin(url, "", null), url).toBe(false);
    }
    // Addresses that cannot leave the page or the engine stay allowed, with or without a page.
    expect(isEngineOrigin("/api/fields/k/frames.bin?v=1", "", null)).toBe(true);
    expect(isEngineOrigin("frames.bin", "https://engine.example", null)).toBe(true);
    expect(isEngineOrigin("https://engine.example/api/x", "https://engine.example", null)).toBe(
      true,
    );
    expect(isEngineOrigin("/api/x", "/", page)).toBe(true);
    // Opaque origins are never the page or the engine.
    expect(isEngineOrigin("data:application/octet-stream,AAAA", "", page)).toBe(false);
    expect(isEngineOrigin("file:///etc/hosts", "", page)).toBe(false);
  });

  it("refuses a disguised address in a manifest before fetching it", async () => {
    const { frames } = synthetic_manifest;
    if (!frames) throw new Error("the synthetic manifest has a frame file");
    for (const url of ["/\\other.example/frames.bin", "\t//other.example/frames.bin"]) {
      const manifest: Manifest = { ...synthetic_manifest, frames: { ...frames, url } };
      const { urls, options } = harness(() => json(manifest));
      const error = await failure(
        loadField({ ra: 10, dec: 20, fov: 6 }, { ...options, engine: "" }),
      );
      expect(error.code, url).toBe("bad_response");
      expect(urls, url).toEqual(["/api/fields?ra=10&dec=20&fov=6"]);
    }
  });

  it("refuses a manifest whose frame file is on another site, before fetching it", async () => {
    const { frames } = synthetic_manifest;
    if (!frames) throw new Error("the synthetic manifest has a frame file");
    const manifest: Manifest = {
      ...synthetic_manifest,
      frames: { ...frames, url: "https://other.example/frames.bin" },
    };
    const { urls, options } = harness(() => json(manifest));
    const error = await failure(
      loadField({ ra: 10, dec: 20, fov: 6 }, { ...options, engine: "https://engine.example" }),
    );
    expect(error.code).toBe("bad_response");
    expect(urls).toEqual(["https://engine.example/api/fields?ra=10&dec=20&fov=6"]);
  });
});

// ---------------------------------------------------------------------------------------------
// Recorded answers: the real files shipped with the recorded fields (public/fixtures, copied from
// cache/fixtures by scripts/sync-contract.mjs). The variants that must be refused are stand-ins
// made from them, named synthetic_*.
// ---------------------------------------------------------------------------------------------

const fixturesDir = fileURLToPath(new URL("../public/fixtures/", import.meta.url));

/** A recorded field's manifest key and its two recorded answers as text, or null when not bundled. */
function recordedFiles(name: string) {
  const read = (file: string) => {
    const path = join(fixturesDir, name, file);
    return existsSync(path) ? readFileSync(path, "utf8") : null;
  };
  const manifest = read("manifest.json");
  const overlays = read("overlays.json");
  const spectrum = read("spectrum.json");
  if (manifest === null || overlays === null || spectrum === null) return null;
  return { name, key: (JSON.parse(manifest) as Manifest).key, overlays, spectrum };
}

const wiseFiles = recordedFiles("wise0855");
const barnardFiles = recordedFiles("barnard");

/** A file as a static host serves it. */
const served = (text: string, status = 200) =>
  new Response(text, { status, headers: { "Content-Type": "application/json" } });

/** A recorded answer's text with some of its envelope's fields changed: a stand-in, not real. */
const synthetic_envelope = (text: string, change: Record<string, unknown>) =>
  JSON.stringify({ ...JSON.parse(text), ...change });

// Parsed JSON, read as objects, for making stand-ins of real answers.
type Obj = Record<string, unknown>;
const obj = (value: unknown) => value as Obj;
const objs = (value: unknown) => value as Array<Obj | null>;
/** Takes `name` out of a JSON object. */
const drop = (value: unknown, name: string) => {
  Reflect.deleteProperty(obj(value), name);
};
/** Sets `name` (a point's quality, unless named) of a JSON object to `text`. */
const put = (value: unknown, text: string, name = "quality") => {
  obj(value)[name] = text;
};

describe.skipIf(wiseFiles === null || barnardFiles === null)(
  "loadRecordedOverlays and loadRecordedSpectrum",
  () => {
    type Files = NonNullable<typeof wiseFiles>;
    const wise = () => wiseFiles as Files;
    const barnard = () => barnardFiles as Files;

    /** Serves `text` as every file asked for. */
    const serving = (text: string, status = 200) => harness(() => served(text, status));

    it("reads both answers of each recorded field from the site's own folder, as they are", async () => {
      for (const files of [wise(), barnard()]) {
        const { urls, options } = harness((url) =>
          served(url.endsWith("/overlays.json") ? files.overlays : files.spectrum),
        );
        const overlays = await loadRecordedOverlays(files.name, files.key, options);
        const spectrum = await loadRecordedSpectrum(files.name, files.key, options);
        // Same origin, static files: never the engine.
        expect(urls).toEqual([
          `/fixtures/${files.name}/overlays.json`,
          `/fixtures/${files.name}/spectrum.json`,
        ]);
        expect(overlays).toEqual(JSON.parse(files.overlays) as RecordedAnswer<"overlays">);
        expect(spectrum).toEqual(JSON.parse(files.spectrum) as RecordedAnswer<"spectrum">);
        expect([overlays?.route, spectrum?.route]).toEqual(["overlays", "spectrum"]);
        expect([overlays?.key, spectrum?.key]).toEqual([files.key, files.key]);
      }
    });

    it("gives null for an answer of another field: wrong key, or wrong field name", async () => {
      const { options } = serving(wise().overlays);
      expect(await loadRecordedOverlays("wise0855", barnard().key, options)).toBeNull();
      expect(await loadRecordedOverlays("barnard", wise().key, options)).toBeNull();
      const renamed = serving(synthetic_envelope(wise().overlays, { field: "barnard" }));
      expect(await loadRecordedOverlays("wise0855", wise().key, renamed.options)).toBeNull();
    });

    it("gives null for an answer of the other route", async () => {
      const spectrumAsOverlays = serving(wise().spectrum);
      expect(
        await loadRecordedOverlays("wise0855", wise().key, spectrumAsOverlays.options),
      ).toBeNull();
      const overlaysAsSpectrum = serving(wise().overlays);
      expect(
        await loadRecordedSpectrum("wise0855", wise().key, overlaysAsSpectrum.options),
      ).toBeNull();
      const relabelled = serving(synthetic_envelope(wise().spectrum, { route: "overlays" }));
      expect(await loadRecordedOverlays("wise0855", wise().key, relabelled.options)).toBeNull();
    });

    it.each<[string, Record<string, unknown>]>([
      ["another kind", { kind: "manifest" }],
      ["no kind", { kind: undefined }],
      ["another contract", { contract: "2.0" }],
      ["no contract", { contract: undefined }],
      ["no pipeline version", { pipeline_version: undefined }],
      ["a recording time in another form", { recorded_at: "14 Nov 2026" }],
      ["a recording time that is not a real time", { recorded_at: "2026-02-31T00:00:00Z" }],
      ["no response", { response: undefined }],
      ["a response of another shape", { response: { contract: "1.0", status: "ok", gaia: [] } }],
      ["a response without the contract's key", { response: { status: "ok" } }],
      ["no request", { request: null }],
    ])("gives null for an overlays envelope with %s", async (_what, change) => {
      const { options } = serving(synthetic_envelope(wise().overlays, change));
      expect(await loadRecordedOverlays("wise0855", wise().key, options)).toBeNull();
    });

    it.each<[string, Record<string, unknown>]>([
      ["another kind", { kind: "recorded" }],
      ["a position off the sky", { request: { ra: 400, dec: -7.2422 } }],
      ["no position", { request: {} }],
      ["a state the contract does not name", { response: { status: "ok", state: "great" } }],
    ])("gives null for a spectrum envelope with %s", async (_what, change) => {
      const base = JSON.parse(wise().spectrum) as RecordedAnswer<"spectrum">;
      const response =
        "response" in change
          ? { ...base.response, ...(change.response as Record<string, unknown>) }
          : base.response;
      const { options } = serving(synthetic_envelope(wise().spectrum, { ...change, response }));
      expect(await loadRecordedSpectrum("wise0855", wise().key, options)).toBeNull();
    });

    it.each<[string, () => Response]>([
      ["no file (404 page)", () => html(404)],
      ["no file (404 with a body)", () => served(wise().overlays, 404)],
      ["a static host's HTML page with status 200", () => html(200)],
      ["malformed JSON", () => served('{"contract": "1.0", "kind": ')],
      ["JSON that is not an object", () => served("[]")],
    ])("gives null, never an error, for %s", async (_what, answer) => {
      const { options } = harness(answer);
      expect(await loadRecordedOverlays("wise0855", wise().key, options)).toBeNull();
      expect(await loadRecordedSpectrum("wise0855", wise().key, options)).toBeNull();
    });

    it("rejects, to be asked again, when the site does not answer or answers 429 or 5xx", async () => {
      // Not an answer about the file: the caller keeps nothing and may ask again later.
      const { urls, sleeps, options } = harness(offline);
      await expect(loadRecordedOverlays("wise0855", wise().key, options)).rejects.toMatchObject({
        code: "unreachable",
      });
      expect(urls).toHaveLength(3);
      expect(sleeps).toEqual([300, 900]);
      for (const status of [429, 500, 502, 503]) {
        const { options: failing } = serving(wise().overlays, status);
        await expect(
          loadRecordedOverlays("wise0855", wise().key, failing),
          String(status),
        ).rejects.toBeInstanceOf(FieldError);
        await expect(
          loadRecordedSpectrum("wise0855", wise().key, failing),
          String(status),
        ).rejects.toBeInstanceOf(FieldError);
      }
      // A 4xx is an answer about the file: there is none (R5).
      for (const status of [403, 404, 410]) {
        const { options: missing } = serving(wise().overlays, status);
        expect(await loadRecordedOverlays("wise0855", wise().key, missing)).toBeNull();
      }
    });

    /** A real recorded answer's text with its response changed: a stand-in, not real. */
    const synthetic_response = (text: string, change: (response: Obj) => void) => {
      const envelope = JSON.parse(text) as { response: Obj };
      change(envelope.response);
      return JSON.stringify(envelope);
    };

    it.each<[string, (response: Obj) => void]>([
      ["no target", (r) => drop(r, "target")],
      ["a target without its position", (r) => drop(r.target, "ra")],
      ["no method", (r) => drop(r, "method")],
      ["no neighbours", (r) => drop(r, "neighbours")],
      ["no time span", (r) => drop(r, "time_span")],
      ["a time span without its end", (r) => drop(r.time_span, "mjd_max")],
      ["a point that is null", (r) => objs(r.points).push(null)],
      ["a point without its wavelength", (r) => drop(objs(r.points)[0], "lam")],
      ["a point of a quality the contract does not name", (r) => put(objs(r.points)[0], "fine")],
      ["a binned value without its flux", (r) => drop(objs(r.binned)[0], "flux_ujy")],
    ])("gives null for WISE 0855's recorded spectrum with %s", async (_what, change) => {
      const { options } = serving(synthetic_response(wise().spectrum, change));
      expect(await loadRecordedSpectrum("wise0855", wise().key, options)).toBeNull();
    });

    it.each<[string, (response: Obj) => void]>([
      ["a Gaia entry that is null", (r) => objs(r.gaia).push(null)],
      ["a Gaia source without its position", (r) => drop(objs(r.gaia)[0], "ra")],
      ["a Gaia source without its id", (r) => drop(objs(r.gaia)[0], "source_id")],
      ["a CatWISE source without its position", (r) => drop(objs(r.catwise)[0], "dec")],
      [
        "track points without their position",
        (r) => {
          for (const source of [...objs(r.gaia), ...objs(r.catwise)]) {
            for (const point of objs(obj(source).track ?? [])) drop(point, "ra");
          }
        },
      ],
      ["no Gaia upstream", (r) => drop(r.upstreams, "gaia")],
      ["an upstream state the contract does not name", (r) => put(r.upstreams, "down", "catwise")],
    ])("gives null for a recorded overlays answer with %s", async (_what, change) => {
      for (const files of [wise(), barnard()]) {
        const { options } = serving(synthetic_response(files.overlays, change));
        expect(await loadRecordedOverlays(files.name, files.key, options), files.name).toBeNull();
      }
    });

    it("takes the real recorded responses as live answers, and refuses them broken", async () => {
      // The response's bytes as recorded (re-serialising would turn a recorded -0.0 into 0).
      const bytesOf = (text: string) =>
        text.slice(text.indexOf(',"response":') + ',"response":'.length, text.lastIndexOf("}"));
      for (const files of [wise(), barnard()]) {
        const overlays = JSON.parse(bytesOf(files.overlays)) as Obj;
        const spectrum = JSON.parse(bytesOf(files.spectrum)) as Obj;
        const live = harness(() => served(bytesOf(files.overlays)));
        expect(await loadOverlays(files.key, quiet(live.options))).toEqual(overlays);
        const measured = harness(() => served(bytesOf(files.spectrum)));
        expect(await loadSpectrum(files.key, 1, 2, quiet(measured.options))).toEqual(spectrum);
        // What the page could not draw is refused at the door, live as recorded: "bad_response".
        const nullSource = harness(() =>
          json({ ...overlays, gaia: [...objs(overlays.gaia), null] }),
        );
        const noTarget = harness(() => json({ ...spectrum, target: undefined }));
        expect((await failure(loadOverlays(files.key, quiet(nullSource.options)))).code).toBe(
          "bad_response",
        );
        expect((await failure(loadSpectrum(files.key, 1, 2, quiet(noTarget.options)))).code).toBe(
          "bad_response",
        );
      }
    });

    it("asks nothing for a name or a key that is not one", async () => {
      const { urls, options } = serving(wise().overlays);
      expect(await loadRecordedOverlays("../wise0855", wise().key, options)).toBeNull();
      expect(await loadRecordedSpectrum("wise0855", "../status", options)).toBeNull();
      expect(urls).toEqual([]);
    });

    it("rejects only when aborted", async () => {
      const controller = new AbortController();
      const { options } = harness(() => {
        controller.abort();
        throw new DOMException("The operation was aborted.", "AbortError");
      });
      await expect(
        loadRecordedOverlays("wise0855", wise().key, { ...options, signal: controller.signal }),
      ).rejects.toMatchObject({ name: "AbortError" });
    });
  },
);
